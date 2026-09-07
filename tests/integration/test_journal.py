"""Schema-2 replacements for the schema-1 journal invariants, plus durable commits."""

import asyncio
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace

import pytest

from flynn_agents_sdk import (
    BudgetExhausted,
    ContractError,
    Evaluation,
    InferenceRequest,
    RunLimits,
    SQLiteRun,
    State,
    ToolCall,
    UnresolvedEffect,
    Verdict,
)


def create(path, limits=None):
    return SQLiteRun.create(
        path,
        run_id="test",
        initial_state="base",
        initial_observation="frame",
        limits=limits or RunLimits(3, 3, 2),
    )


def dispatch(run, name="a", *, observation=True, external=False):
    run.start(name, InferenceRequest("test", run.read(), ("act",)))
    run.proposed(name, ToolCall("act", "{}"))
    run.dispatch(name, observation=observation, external_action=external)


def test_reopen_restores_state_evidence_and_budget(tmp_path):
    path = tmp_path / "run.db"
    with create(path) as run:
        dispatch(run, external=True)
        candidate = run.returned("a", "observed")
        run.complete(
            Evaluation(candidate, "test/v1", "update", Verdict.SATISFIED, "checked", "new state")
        )
    with SQLiteRun.open(path) as run:
        assert run.read() == State(1, "new state")
        assert run.latest_observation() == "observed"
        assert run.remaining() == {"inference": 2, "tool": 2, "external": 1}
        assert run.pending() is None
        with pytest.raises(ContractError):
            run.complete(
                Evaluation(
                    candidate, "test/v1", "update", Verdict.SATISFIED, "checked", "new state"
                )
            )
        assert len(run.records()["commits"]) == 1


def test_failed_prediction_and_internal_diagnostic_preserve_observation(tmp_path):
    with create(tmp_path / "run.db") as run:
        dispatch(run)
        candidate = run.returned("a", "new frame")
        run.complete(Evaluation(candidate, "prediction/v1", "prediction", Verdict.FAILED, "wrong"))
        dispatch(run, "b", observation=False)
        candidate = run.returned("b", "diagnostic")
        run.complete(
            Evaluation(candidate, "diagnostic/v1", "diagnostic", Verdict.SATISFIED, "valid")
        )
        assert run.latest_observation() == "new frame"
        assert run.read().revision == 0
        assert len(run.records()["evaluations"]) == 2


def test_atomic_commit_rolls_back_evaluation_on_failure(tmp_path):
    path = tmp_path / "run.db"
    with create(path) as run:
        dispatch(run)
        candidate = run.returned("a", "observed")
        # Inject failure after evaluation insertion but before commit insertion.
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TRIGGER injected BEFORE INSERT ON commits "
                "BEGIN SELECT RAISE(ABORT,'injected'); END"
            )
        evaluation = Evaluation(candidate, "test/v1", "test", Verdict.SATISFIED, "checked", "next")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            run.complete(evaluation)
        assert run.read() == State(0, "base")
        assert run.records()["evaluations"] == []
        assert run.pending().stage == "returned"
        with sqlite3.connect(path) as db:
            db.execute("DROP TRIGGER injected")
        assert run.complete(evaluation).state == State(1, "next")


@pytest.mark.parametrize(
    "limits,kind",
    [
        (RunLimits(0, 3, 2), "inference"),
        (RunLimits(3, 0, 2), "tool"),
        (RunLimits(3, 3, 0), "external"),
    ],
)
def test_budget_failure_is_atomic(tmp_path, limits, kind):
    with create(tmp_path / "run.db", limits) as run:
        with pytest.raises(BudgetExhausted, match=kind):
            dispatch(run, external=True)
        remaining = run.remaining()
        assert remaining["tool"] == limits.tool_calls
        assert remaining["external"] == limits.external_actions


def test_duplicate_result_and_pending_attempt_refused(tmp_path):
    with create(tmp_path / "run.db") as run:
        dispatch(run)
        with pytest.raises(UnresolvedEffect):
            dispatch(run, "b")
        run.returned("a", "one")
        with pytest.raises(ContractError):
            run.returned("a", "two")
        with pytest.raises(ContractError, match="recovery"):
            dispatch(run, "b")


def test_live_owner_blocks_second_writer(tmp_path):
    path = tmp_path / "run.db"
    with create(path):
        with pytest.raises(ContractError, match="live owner"):
            SQLiteRun.open(path)
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                "from flynn_agents_sdk import SQLiteRun; import sys; SQLiteRun.open(sys.argv[1])",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        assert process.returncode != 0 and "live owner" in process.stderr
    with SQLiteRun.open(path):
        pass


@pytest.mark.parametrize(
    "point,stage,revision",
    [
        ("reserved", "inference", 0),
        ("proposed", "proposed", 0),
        ("dispatched", "dispatched", 0),
        ("returned", "returned", 0),
        ("committed", None, 1),
    ],
)
def test_process_death_reopens_exact_durable_boundary(tmp_path, point, stage, revision):
    path = tmp_path / "run.db"
    script = """
import os,sys
from flynn_agents_sdk import *
p,point=sys.argv[1:]
r=SQLiteRun.create(p,run_id='crash',initial_state='old',limits=RunLimits(3,3,3))
r.start('a',InferenceRequest('test',r.read(),('act',)))
if point=='reserved': os._exit(23)
r.proposed('a',ToolCall('act','{}'))
if point=='proposed': os._exit(23)
r.dispatch('a',observation=True,external_action=True)
if point=='dispatched': os._exit(23)
c=r.returned('a','observed')
if point=='returned': os._exit(23)
r.complete(Evaluation(c,'test/v1','test',Verdict.SATISFIED,'checked','new'))
os._exit(23)
"""
    assert subprocess.run([sys.executable, "-c", script, str(path), point]).returncode == 23
    with SQLiteRun.open(path) as run:
        assert run.read().revision == revision
        assert (run.pending().stage if run.pending() else None) == stage
        assert run.remaining()["inference"] == 2
        assert len(run.records()["evaluations"]) == revision
        if stage in ("inference", "proposed"):
            run.abandon_undispatched("a")
            assert run.pending() is None
            assert run.remaining()["inference"] == 2
        elif stage == "dispatched":
            with pytest.raises(UnresolvedEffect):
                run.check_ready()


def test_unsupported_schema_and_existing_create_refused(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=1")
    with pytest.raises(ContractError, match="Unsupported"):
        SQLiteRun.open(path)
    with pytest.raises(FileExistsError):
        create(path)
    with pytest.raises(FileNotFoundError):
        SQLiteRun.open(tmp_path / "missing")


def test_terminal_state_survives_and_cannot_be_overwritten(tmp_path):
    path = tmp_path / "run.db"
    with create(path) as run:
        run.finish("completed")
        with pytest.raises(ContractError):
            run.finish("failed")
    with SQLiteRun.open(path) as run:
        assert run.outcome() == "completed"
        with pytest.raises(ContractError, match="already ended"):
            dispatch(run)


def test_forged_or_stale_evaluation_does_not_publish(tmp_path):
    with create(tmp_path / "run.db") as run:
        dispatch(run)
        candidate = run.returned("a", "observed")
        wrong = replace(candidate, base=State(99, "forged"))
        with pytest.raises(ContractError, match="exact candidate"):
            run.complete(Evaluation(wrong, "test/v1", "test", Verdict.SATISFIED, "checked", "bad"))
        assert run.read().revision == 0


def test_timeout_preserves_unknown_effect(tmp_path, monkeypatch):
    from flynn_agents_sdk import Runtime, ScriptedAdapter, Tool, ToolBroker

    class Check:
        async def evaluate(self, candidate):
            pytest.fail("Unreturned action evaluated")

    # Exercise the runtime's real timeout after dispatch, rather than racing
    # synchronous SQLite fsync against a 100ms pre-dispatch budget on a busy host.
    original_timeout = asyncio.timeout
    deadlines = []

    def capture_timeout(delay):
        deadline = original_timeout(delay)
        deadlines.append(deadline)
        return deadline

    monkeypatch.setattr(asyncio, "timeout", capture_timeout)

    async def stalled(_):
        deadlines[0].reschedule(asyncio.get_running_loop().time())
        await asyncio.Event().wait()

    with create(tmp_path / "run.db", RunLimits(1, 1, 1, 60)) as run:
        runtime = Runtime(
            inference=ScriptedAdapter([ToolCall("act", "{}")]),
            tools=ToolBroker([Tool("act", lambda _: None, stalled)]),
            evaluator=Check(),
            run=run,
            grants=("act",),
        )
        with pytest.raises(TimeoutError):
            asyncio.run(runtime.step("test"))
        assert run.pending().stage == "dispatched"
        assert run.remaining()["tool"] == 0


def test_process_death_inside_publication_rolls_back_both_records(tmp_path):
    path = tmp_path / "run.db"
    script = """
import os,sys
from flynn_agents_sdk import *
r=SQLiteRun.create(sys.argv[1],run_id='crash',initial_state='old',limits=RunLimits(1,1,1))
r.start('a',InferenceRequest('test',r.read(),('act',)))
r.proposed('a',ToolCall('act','{}'))
r.dispatch('a',observation=True,external_action=True)
c=r.returned('a','observed')
r._db.create_function('die',0,lambda:os._exit(24))
r._db.execute('CREATE TEMP TRIGGER die BEFORE INSERT ON commits BEGIN SELECT die(); END')
r.complete(Evaluation(c,'test/v1','test',Verdict.SATISFIED,'checked','new'))
"""
    assert subprocess.run([sys.executable, "-c", script, str(path)]).returncode == 24
    with SQLiteRun.open(path) as run:
        assert run.read() == State(0, "old")
        assert run.records()["evaluations"] == []
        assert run.records()["commits"] == []
        assert run.pending().candidate.output == "observed"
        assert run.remaining() == {"inference": 0, "tool": 0, "external": 0}


def test_fork_cannot_reuse_inherited_owner(tmp_path):
    with create(tmp_path / "run.db") as run:
        pid = os.fork()
        if pid == 0:
            try:
                run.finish("forged child outcome")
            except ContractError:
                os._exit(0)
            os._exit(1)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert run.outcome() is None
