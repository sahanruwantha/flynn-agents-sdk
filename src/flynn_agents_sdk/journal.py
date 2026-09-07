"""SQLite evidence journal for a single episode; never replays external actions."""

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType

from flynn_agents_sdk.contracts import (
    Candidate,
    ContractError,
    Evaluation,
    State,
    ToolCall,
    UnresolvedEffect,
    check_evaluation,
)


@dataclass(frozen=True)
class JournalEntry:
    sequence: int
    step_id: str
    base: State
    call: ToolCall
    output: str | None
    evaluation: str | None
    observation: bool


class SQLiteJournal:
    """Own a journal connection. Use a separate database for every fresh episode.

    A committed intent without a returned result blocks further dispatch, including
    after reopening. There is deliberately no clear/retry operation: reconciliation
    requires authoritative evidence. Evaluation records do not claim state commit.
    """

    def __init__(self, path: str | Path, *, initial_observation: str | None = None) -> None:
        if initial_observation is not None and not isinstance(initial_observation, str):
            raise ContractError("Initial observation must be a string")
        self._db = sqlite3.connect(str(path), isolation_level=None)
        try:
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("BEGIN IMMEDIATE")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ContractError(f"Unsupported journal schema: {version}")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS episode (id INTEGER PRIMARY KEY CHECK(id=1), "
                "observation TEXT, outcome TEXT)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS steps (sequence INTEGER PRIMARY KEY, "
                "step_id TEXT UNIQUE NOT NULL, revision INTEGER NOT NULL, base TEXT NOT NULL, "
                "tool TEXT NOT NULL, arguments TEXT NOT NULL, output TEXT, evaluation TEXT, "
                "observation INTEGER NOT NULL)"
            )
            existing = self._db.execute("SELECT observation FROM episode WHERE id=1").fetchone()
            if existing is None:
                self._db.execute("INSERT INTO episode VALUES (1, ?, NULL)", (initial_observation,))
            elif initial_observation is not None and existing[0] != initial_observation:
                raise ContractError("Journal belongs to a different initial observation")
            self._db.execute("PRAGMA user_version=1")
            self._db.execute("COMMIT")
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> "SQLiteJournal":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def outcome(self) -> str | None:
        """Return the application-declared ending; this is not an SDK success verdict."""
        value: str | None = self._db.execute("SELECT outcome FROM episode WHERE id=1").fetchone()[0]
        return value

    def finish(self, outcome: str) -> None:
        """Record a terminal outcome exactly once and refuse future dispatches."""
        if not isinstance(outcome, str) or not outcome.strip():
            raise ContractError("Episode outcome must be nonempty text")
        cursor = self._db.execute(
            "UPDATE episode SET outcome=? WHERE id=1 AND outcome IS NULL", (outcome,)
        )
        if cursor.rowcount != 1:
            raise ContractError("Episode already ended")

    def latest_observation(self) -> str | None:
        row = self._db.execute(
            "SELECT output FROM steps WHERE output IS NOT NULL AND observation=1 "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            row = self._db.execute("SELECT observation FROM episode WHERE id=1").fetchone()
        value: str | None = row[0]
        return value

    def unresolved(self) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in self._db.execute(
                "SELECT step_id FROM steps WHERE output IS NULL ORDER BY sequence"
            )
        )

    def begin(
        self, step_id: str, base: State, call: ToolCall, *, observation: bool = False
    ) -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if self.outcome() is not None:
                raise ContractError("Episode already ended; use a fresh journal")
            if self.unresolved():
                raise UnresolvedEffect("Prior action has no recorded result; stop and reconcile")
            self._db.execute(
                "INSERT INTO steps(step_id, revision, base, tool, arguments, observation) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (step_id, base.revision, base.value, call.name, call.arguments, int(observation)),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def returned(self, step_id: str, output: str) -> None:
        if not isinstance(output, str):
            raise ContractError("Observation must be a string")
        cursor = self._db.execute(
            "UPDATE steps SET output=? WHERE step_id=? AND output IS NULL", (output, step_id)
        )
        if cursor.rowcount != 1:
            raise ContractError("Unknown dispatch or result already recorded")

    def evaluated(self, step_id: str, evaluation: Evaluation) -> None:
        row = self._db.execute(
            "SELECT revision, base, tool, arguments, output FROM steps WHERE step_id=?", (step_id,)
        ).fetchone()
        if row is None or row[4] is None:
            raise ContractError("Evaluation requires a recorded result")
        candidate = Candidate(step_id, State(row[0], row[1]), ToolCall(row[2], row[3]), row[4])
        check_evaluation(candidate, evaluation)
        payload = json.dumps(asdict(evaluation), sort_keys=True)
        cursor = self._db.execute(
            "UPDATE steps SET evaluation=? WHERE step_id=? AND evaluation IS NULL",
            (payload, step_id),
        )
        if cursor.rowcount != 1:
            raise ContractError("Evaluation already recorded")

    def entries(self) -> tuple[JournalEntry, ...]:
        """Return exact ordered transitions, including failed and unfinished work."""
        return tuple(
            JournalEntry(
                row[0],
                row[1],
                State(row[2], row[3]),
                ToolCall(row[4], row[5]),
                row[6],
                row[7],
                bool(row[8]),
            )
            for row in self._db.execute("SELECT * FROM steps ORDER BY sequence")
        )
