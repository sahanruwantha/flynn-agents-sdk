"""SQLite control state for one exclusively owned local POSIX run.

Large artifacts remain external. A database commit proves recorded state, not an
external effect or the truth of an application evaluator. Schema 1 journals are refused.
"""

import fcntl
import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import TracebackType
from typing import Any

from flynn_agents_sdk.accounting import summarize_usage
from flynn_agents_sdk.contracts import (
    BudgetExhausted,
    Candidate,
    ContractError,
    Evaluation,
    InferenceRequest,
    InferenceUsage,
    OutputBudget,
    OutputReservation,
    PendingOperation,
    RunLimits,
    State,
    StepResult,
    ToolCall,
    UnresolvedEffect,
    check_evaluation,
)
from flynn_agents_sdk.output_budget import output_budget

APPLICATION_ID = 0x464C594E
SCHEMA_VERSION = 4


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class SQLiteRun:
    """Own state, evidence and budgets together. Use create() or open().

    The ownership flock is held for this object's lifetime, including across awaits;
    read-only SQLite clients may inspect the database concurrently. This is a local
    trusted-application boundary, not a sandbox or a network-filesystem protocol.
    """

    def __init__(self, path: Path, *, create: bool) -> None:
        self.path = path.resolve()
        flags = os.O_RDWR | (os.O_CREAT | os.O_EXCL if create else 0)
        self._fd = os.open(self.path, flags, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(self._fd)
            raise ContractError(
                "Run has a live owner; inspect read-only or wait for release"
            ) from error
        try:
            self._db = sqlite3.connect(
                self.path.as_uri() + "?mode=rw", uri=True, isolation_level=None
            )
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA busy_timeout=5000")
        except BaseException:
            os.close(self._fd)
            raise
        self._closed = False
        self._owner_pid = os.getpid()
        self._monotonic_deadline: float | None = None

    @classmethod
    def create(
        cls,
        path: str | Path,
        *,
        run_id: str,
        initial_state: str,
        limits: RunLimits,
        initial_observation: str | None = None,
    ) -> "SQLiteRun":
        if not isinstance(run_id, str) or not run_id.strip():
            raise ContractError("Run identity must be nonempty")
        if not isinstance(initial_state, str) or (
            initial_observation is not None and not isinstance(initial_observation, str)
        ):
            raise ContractError("Initial state and observation must be strings")
        run = cls(Path(path), create=True)
        try:
            with run._transaction():
                run._db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                run._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                run._db.execute(
                    "CREATE TABLE run (id TEXT PRIMARY KEY, initial_state TEXT NOT NULL, "
                    "initial_observation TEXT, limits TEXT NOT NULL, deadline REAL, "
                    "last_clock REAL NOT NULL, outcome TEXT)"
                )
                run._db.execute(
                    "CREATE TABLE operations (sequence INTEGER PRIMARY KEY, "
                    "id TEXT UNIQUE NOT NULL, "
                    "stage TEXT NOT NULL CHECK(stage IN "
                    "('inference','proposed','dispatched','returned','completed','failed')), "
                    "request TEXT NOT NULL, call TEXT, observation INTEGER NOT NULL DEFAULT 0, "
                    "output TEXT, error TEXT)"
                )
                run._db.execute(
                    "CREATE TABLE reservations (sequence INTEGER PRIMARY KEY, "
                    "operation_id TEXT NOT NULL REFERENCES operations(id), "
                    "kind TEXT NOT NULL CHECK(kind IN ('inference','tool','external')), "
                    "UNIQUE(operation_id,kind))"
                )
                run._db.execute(
                    "CREATE TABLE evaluations (operation_id TEXT PRIMARY KEY REFERENCES "
                    "operations(id), payload TEXT NOT NULL, digest TEXT NOT NULL)"
                )
                run._db.execute(
                    "CREATE TABLE commits (revision INTEGER PRIMARY KEY CHECK(revision>0), "
                    "operation_id TEXT UNIQUE NOT NULL REFERENCES evaluations(operation_id), "
                    "base_revision INTEGER NOT NULL, value TEXT NOT NULL, "
                    "evaluation_digest TEXT NOT NULL)"
                )
                run._db.execute(
                    "CREATE TABLE inference_usage (operation_id TEXT PRIMARY KEY NOT NULL "
                    "REFERENCES operations(id), payload TEXT NOT NULL)"
                )
                run._db.execute(
                    "CREATE TABLE output_reservations (operation_id TEXT PRIMARY KEY NOT NULL "
                    "REFERENCES operations(id), kind TEXT NOT NULL "
                    "CHECK(kind IN ('model','scripted')), "
                    "tokens INTEGER NOT NULL CHECK(tokens>=0))"
                )
                for table in (
                    "reservations",
                    "evaluations",
                    "commits",
                    "inference_usage",
                    "output_reservations",
                ):
                    for verb in ("UPDATE", "DELETE"):
                        run._db.execute(
                            f"CREATE TRIGGER immutable_{table}_{verb} BEFORE {verb} ON {table} "
                            "BEGIN SELECT RAISE(ABORT,'immutable history'); END"
                        )
                now = time.time()
                deadline = (
                    None if limits.wall_time_seconds is None else now + limits.wall_time_seconds
                )
                run._db.execute(
                    "INSERT INTO run VALUES (?,?,?,?,?,?,NULL)",
                    (
                        run_id,
                        initial_state,
                        initial_observation,
                        _json(asdict(limits)),
                        deadline,
                        now,
                    ),
                )
            run._bind_clock()
            return run
        except BaseException:
            run.close()
            raise

    @classmethod
    def open(cls, path: str | Path) -> "SQLiteRun":
        run = cls(Path(path), create=False)
        try:
            app = run._db.execute("PRAGMA application_id").fetchone()[0]
            version = run._db.execute("PRAGMA user_version").fetchone()[0]
            if app != APPLICATION_ID or version != SCHEMA_VERSION:
                raise ContractError(
                    f"Unsupported Flynn database application/schema {app}/{version}; "
                    "archive old evidence and create a new schema-4 run"
                )
            if run._db.execute("SELECT count(*) FROM run").fetchone()[0] != 1:
                raise ContractError("Database must contain exactly one run")
            run._bind_clock()
            return run
        except BaseException:
            run.close()
            raise

    def _bind_clock(self) -> None:
        row = self._run()
        now = time.time()
        if now < row["last_clock"]:
            raise ContractError("Wall clock moved backwards; restore the clock before reopening")
        if row["deadline"] is not None:
            self._monotonic_deadline = time.monotonic() + max(0.0, row["deadline"] - now)

    def __enter__(self) -> "SQLiteRun":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._db.close()
            os.close(self._fd)
            self._closed = True

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if os.getpid() != self._owner_pid:
            raise ContractError("Inherited SQLite owner cannot write; open a new run after fork")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def _run(self) -> sqlite3.Row:
        return self._db.execute("SELECT * FROM run").fetchone()  # type: ignore[no-any-return]

    @property
    def seconds_remaining(self) -> float | None:
        if self._monotonic_deadline is None:
            return None
        return max(0.0, self._monotonic_deadline - time.monotonic())

    def _require_open(self) -> None:
        if self.outcome() is not None:
            raise ContractError("Run already ended; create a fresh run")

    def _require_time(self) -> None:
        self._require_open()
        now = time.time()
        if now < self._run()["last_clock"]:
            raise ContractError("Wall clock moved backwards; no operation authorized")
        if self.seconds_remaining == 0:
            raise BudgetExhausted("Run wall-time budget exhausted")
        self._db.execute("UPDATE run SET last_clock=?", (now,))

    def outcome(self) -> str | None:
        value: str | None = self._run()["outcome"]
        return value

    def finish(self, outcome: str) -> None:
        if not isinstance(outcome, str) or not outcome.strip():
            raise ContractError("Terminal outcome must be nonempty application-owned text")
        with self._transaction():
            self._require_open()
            self._db.execute("UPDATE run SET outcome=?", (outcome,))

    def read(self) -> State:
        row = self._db.execute(
            "SELECT revision,value FROM commits ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        return (
            State(row["revision"], row["value"]) if row else State(0, self._run()["initial_state"])
        )

    def latest_observation(self) -> str | None:
        row = self._db.execute(
            "SELECT output FROM operations WHERE observation=1 AND output IS NOT NULL "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        value: str | None = row[0] if row else self._run()["initial_observation"]
        return value

    def remaining(self) -> dict[str, int]:
        limits = json.loads(self._run()["limits"])
        used = dict(self._db.execute("SELECT kind,count(*) FROM reservations GROUP BY kind"))
        return {
            kind: limits[field] - used.get(kind, 0)
            for kind, field in (
                ("inference", "inference_calls"),
                ("tool", "tool_calls"),
                ("external", "external_actions"),
            )
        }

    def _reserve(self, operation_id: str, kind: str) -> None:
        if self.remaining()[kind] <= 0:
            raise BudgetExhausted(f"{kind} budget exhausted; no operation authorized")
        self._db.execute(
            "INSERT INTO reservations(operation_id,kind) VALUES (?,?)", (operation_id, kind)
        )

    def _operation(self, operation_id: str, stage: str | None = None) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        if row is None or (stage is not None and row["stage"] != stage):
            found = None if row is None else row["stage"]
            raise ContractError(
                f"Operation {operation_id!r} requires stage {stage!r}; found {found!r}"
            )
        return row  # type: ignore[no-any-return]

    def _candidate(self, row: sqlite3.Row) -> Candidate:
        request = json.loads(row["request"])
        call = json.loads(row["call"])
        return Candidate(row["id"], State(**request["base"]), ToolCall(**call), row["output"])

    def pending(self) -> PendingOperation | None:
        row = self._db.execute(
            "SELECT * FROM operations WHERE stage NOT IN ('completed','failed') ORDER BY sequence"
        ).fetchone()
        if row is None:
            return None
        return PendingOperation(
            row["id"], row["stage"], self._candidate(row) if row["stage"] == "returned" else None
        )

    def check_ready(self) -> None:
        self._require_open()
        pending = self.pending()
        if pending is not None:
            if pending.stage == "dispatched":
                raise UnresolvedEffect(
                    "Dispatched effect has no result; never repeat it automatically"
                )
            raise ContractError(
                f"Operation {pending.id} needs explicit recovery from {pending.stage}"
            )

    def output_budget(self) -> OutputBudget:
        row = dict(self._run())
        limits = json.loads(row["limits"])
        if not isinstance(limits, dict) or "output_tokens" not in limits:
            raise ContractError(
                "Schema-4 run limits require output_tokens; "
                "preserve this journal and create a new run"
            )
        try:
            configured = RunLimits(**limits)
        except (TypeError, ValueError) as error:
            raise ContractError(
                "Invalid durable run limits; preserve this journal and create a new run"
            ) from error
        if configured.output_tokens is None:
            return OutputBudget(None, None)
        # Admission needs compact accounting, never accumulated tool output or state.
        return output_budget(
            {
                "run": [row],
                "inference_usage": [
                    dict(item) for item in self._db.execute("SELECT * FROM inference_usage")
                ],
                "output_reservations": [
                    dict(item) for item in self._db.execute("SELECT * FROM output_reservations")
                ],
            }
        )

    def start(
        self,
        operation_id: str,
        request: InferenceRequest,
        output: OutputReservation | None = None,
    ) -> None:
        with self._transaction():
            self.check_ready()
            self._require_time()
            budget = self.output_budget()
            if budget.limit is not None:
                if not isinstance(output, OutputReservation):
                    raise ContractError("Output-limited run requires an explicit reservation")
                if request.max_output_tokens != output.tokens:
                    raise ContractError("Request output ceiling must match its reservation")
                if output.kind == "model":
                    if budget.unresolved or budget.breached:
                        raise BudgetExhausted(
                            "Output usage is unresolved or its bound was breached; "
                            "no further model request authorized"
                        )
                    if budget.available is None or output.tokens > budget.available:
                        raise BudgetExhausted("Output reservation exceeds remaining token budget")
            elif output is not None:
                raise ContractError("Output reservation requires an output-limited run")
            if request.base != self.read():
                raise ContractError("Inference request has a stale state revision")
            if not operation_id:
                raise ContractError("Operation identity must be nonempty")
            self._db.execute(
                "INSERT INTO operations(id,stage,request) VALUES (?,'inference',?)",
                (operation_id, _json(asdict(request))),
            )
            self._reserve(operation_id, "inference")
            if output is not None:
                self._db.execute(
                    "INSERT INTO output_reservations VALUES (?,?,?)",
                    (operation_id, output.kind, output.tokens),
                )

    def record_usage(self, operation_id: str, usage: InferenceUsage) -> None:
        """Append accounting before proposal validation, including failed inference.

        This write deliberately accepts expired time budgets: receiving an accounting
        report never authorizes another request and must not erase consumed usage.
        """
        if not isinstance(usage, InferenceUsage):
            raise ContractError("Inference accounting must be an InferenceUsage")
        with self._transaction():
            self._require_open()
            self._operation(operation_id, "inference")
            self._db.execute(
                "INSERT INTO inference_usage VALUES (?,?)", (operation_id, _json(asdict(usage)))
            )

        # Preserve the report even when it proves the adapter violated its promise.
        reserved = self._db.execute(
            "SELECT kind,tokens FROM output_reservations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if reserved is not None and (
            usage.kind != reserved["kind"]
            or (usage.output_tokens is not None and usage.output_tokens > reserved["tokens"])
        ):
            raise ContractError(
                "Inference output reservation was breached; usage retained, dispatch refused"
            )

    def usage_summary(self) -> dict[str, int | bool]:
        return summarize_usage(self.records())

    @classmethod
    def inspect(cls, path: str | Path) -> dict[str, list[dict[str, Any]]]:
        """Read a coherent audit snapshot without ownership, migration or clock updates.

        Schema 2 has no usage reports: its invocations remain unreported, never zero.
        Historical readability does not authorize execution or recovery.
        """
        db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")
            app = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if app != APPLICATION_ID or version not in (2, 3, SCHEMA_VERSION):
                raise ContractError(f"Unsupported Flynn audit application/schema {app}/{version}")
            tables: tuple[str, ...] = (
                "run",
                "operations",
                "reservations",
                "evaluations",
                "commits",
            )
            if version >= 3:
                tables += ("inference_usage",)
            if version == SCHEMA_VERSION:
                tables += ("output_reservations",)
            records = {
                table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in tables
            }
            records.setdefault("inference_usage", [])
            records.setdefault("output_reservations", [])
            return records
        finally:
            db.close()

    def proposed(self, operation_id: str, call: ToolCall) -> None:
        if (
            not isinstance(call, ToolCall)
            or not isinstance(call.name, str)
            or not isinstance(call.arguments, str)
        ):
            raise ContractError("Inference must return a ToolCall with string name and arguments")
        with self._transaction():
            self._require_open()
            self._operation(operation_id, "inference")
            self._db.execute(
                "UPDATE operations SET stage='proposed',call=? WHERE id=?",
                (_json(asdict(call)), operation_id),
            )

    def dispatch(self, operation_id: str, *, observation: bool, external_action: bool) -> None:
        with self._transaction():
            self._require_time()
            self._operation(operation_id, "proposed")
            self._reserve(operation_id, "tool")
            if external_action:
                self._reserve(operation_id, "external")
            self._db.execute(
                "UPDATE operations SET stage='dispatched',observation=? WHERE id=?",
                (int(observation), operation_id),
            )

    def returned(self, operation_id: str, output: str) -> Candidate:
        if not isinstance(output, str):
            raise ContractError("Tool output must be a string")
        with self._transaction():
            self._operation(operation_id, "dispatched")
            self._db.execute(
                "UPDATE operations SET stage='returned',output=? WHERE id=?", (output, operation_id)
            )
        return self._candidate(self._operation(operation_id))

    def complete(self, evaluation: Evaluation) -> StepResult:
        with self._transaction():
            self._require_open()
            row = self._operation(evaluation.candidate.id, "returned")
            candidate = self._candidate(row)
            check_evaluation(candidate, evaluation)
            current = self.read()
            if current != candidate.base:
                raise ContractError("Stale candidate base; publication refused")
            payload = _json(asdict(evaluation))
            digest = hashlib.sha256(payload.encode()).hexdigest()
            self._db.execute(
                "INSERT INTO evaluations VALUES (?,?,?)", (candidate.id, payload, digest)
            )
            committed = (
                evaluation.verdict.value == "satisfied" and evaluation.state_update is not None
            )
            if committed:
                assert evaluation.state_update is not None
                current = State(current.revision + 1, evaluation.state_update)
                self._db.execute(
                    "INSERT INTO commits VALUES (?,?,?,?,?)",
                    (
                        current.revision,
                        candidate.id,
                        candidate.base.revision,
                        current.value,
                        digest,
                    ),
                )
            self._db.execute("UPDATE operations SET stage='completed' WHERE id=?", (candidate.id,))
        return StepResult(candidate, evaluation, current, committed)

    def failed(self, operation_id: str, error: str) -> None:
        """Record diagnostics without erasing unknown effects or returned evidence."""
        with self._transaction():
            row = self._operation(operation_id)
            stage = "failed" if row["stage"] in ("inference", "proposed") else row["stage"]
            self._db.execute(
                "UPDATE operations SET stage=?,error=? WHERE id=?", (stage, error, operation_id)
            )

    def abandon_undispatched(self, operation_id: str) -> None:
        with self._transaction():
            self._require_open()
            row = self._operation(operation_id)
            if row["stage"] not in ("inference", "proposed"):
                raise ContractError("Only an undispatched operation may be abandoned")
            self._db.execute(
                "UPDATE operations SET stage='failed',error='recovered before dispatch' WHERE id=?",
                (operation_id,),
            )

    def records(self) -> dict[str, list[dict[str, Any]]]:
        """A derived inspection export, never an import or second state authority."""
        return {
            table: [dict(row) for row in self._db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in (
                "run",
                "operations",
                "reservations",
                "evaluations",
                "commits",
                "inference_usage",
                "output_reservations",
            )
        }
