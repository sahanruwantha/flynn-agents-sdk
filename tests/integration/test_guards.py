import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from flynn_agents_sdk import (
    ContractError,
    DispatchDenied,
    DispatchGuard,
    Evaluation,
    GuardDecision,
    InferenceRequest,
    RunLimits,
    Runtime,
    ScriptedAdapter,
    Session,
    SessionStep,
    SessionStop,
    SessionTermination,
    SQLiteRun,
    Tool,
    ToolBroker,
    ToolCall,
    Verdict,
)


class Evaluate:
    async def evaluate(self, candidate):
        return Evaluation(candidate, "fixture", "observation", Verdict.SATISFIED, "evidence only")


def runtime(run, check, calls, *, on_event=None):
    async def execute(raw):
        calls.append("tool")
        return "observed"

    return Runtime(
        inference=ScriptedAdapter([ToolCall("act", "{}")]),
        tools=ToolBroker(
            [Tool("act", lambda raw: None, execute, observation=True, external_action=True)]
        ),
        evaluator=Evaluate(),
        run=run,
        grants=("act",),
        guards=(DispatchGuard("scope", check),),
        on_event=on_event,
    )


@pytest.mark.parametrize("allow", [False, True])
def test_guard_decision_precedes_dispatch_and_is_immutable(tmp_path, allow):
    calls, events = [], []
    path = tmp_path / "run.sqlite"

    async def check(context):
        calls.append("guard")
        assert context.call == ToolCall("act", "{}")
        assert context.request.base.value == "original"
        assert context.request.allowed_tools == ("act",)
        return GuardDecision(allow, "scope current" if allow else "authority revoked")

    with SQLiteRun.create(
        path, run_id="guard", initial_state="original", limits=RunLimits(1, 1, 1)
    ) as run:

        def event(row):
            persisted = run.records()["lifecycle_events"][-1]
            assert persisted["stage"] == row.stage
            events.append(row.stage)

        rt = runtime(run, check, calls, on_event=event)
        if allow:
            assert not asyncio.run(rt.step("act")).committed
        else:
            with pytest.raises(DispatchDenied, match="authority revoked"):
                asyncio.run(rt.step("act"))
        assert calls == (["guard", "tool"] if allow else ["guard"])
        assert run.remaining()["tool"] == (0 if allow else 1)
        assert run.remaining()["inference"] == 0
        assert run.remaining()["external"] == (0 if allow else 1)
        assert ("tool_dispatched" in events) == allow
        guard = run.records()["guard_decisions"][0]
        assert json.loads(guard["payload"])["allowed"] is allow
        with sqlite3.connect(path) as db:
            for table in ("guard_requirements", "guard_decisions", "lifecycle_events"):
                with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                    db.execute(f"DELETE FROM {table}")
        run.finish("fixture ended")
    records = SQLiteRun.inspect(path)
    assert json.loads(records["guard_decisions"][0]["payload"])["allowed"] is allow


@pytest.mark.parametrize("decision", [None, False])
def test_store_refuses_missing_or_denied_guard_without_tool_reservation(tmp_path, decision):
    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="raw", initial_state="x", limits=RunLimits(1, 1, 1)
    ) as run:
        run.start("op", InferenceRequest("act", run.read(), ("act",)), guards=("scope",))
        run.proposed("op", ToolCall("act", "{}"))
        if decision is False:
            run.record_guard("op", "scope", GuardDecision(False, "revoked"))
        with pytest.raises(DispatchDenied):
            run.dispatch("op", observation=True, external_action=True)
        assert run.remaining()["tool"] == 1
        assert run.remaining()["external"] == 1


@pytest.mark.parametrize("failure", ["exception", "invalid", "cancel"])
def test_guard_failure_never_executes_tool(tmp_path, failure):
    calls = []

    async def check(context):
        if failure == "exception":
            raise RuntimeError("guard defect")
        if failure == "cancel":
            raise asyncio.CancelledError()
        return True

    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="bad", initial_state="x", limits=RunLimits(1, 1, 1)
    ) as run:
        error = {
            "exception": RuntimeError,
            "cancel": asyncio.CancelledError,
            "invalid": ContractError,
        }[failure]
        with pytest.raises(error):
            asyncio.run(runtime(run, check, calls).step("act"))
        assert calls == []
        assert run.pending() is None
        assert run.records()["guard_decisions"] == []
        assert run.remaining()["external"] == 1


@pytest.mark.parametrize(
    "stage", ["started", "guard_allowed", "tool_dispatched", "tool_returned", "observed"]
)
def test_notification_failure_stops_without_retry_and_preserves_durable_progress(tmp_path, stage):
    calls = []

    async def allow(context):
        return GuardDecision(True, "allowed")

    def event(row):
        if row.stage == stage:
            raise RuntimeError("notification unavailable")

    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="notify", initial_state="x", limits=RunLimits(1, 1, 1)
    ) as run:
        with pytest.raises(RuntimeError, match="notification unavailable"):
            asyncio.run(runtime(run, allow, calls, on_event=event).step("act"))
        assert calls == (["tool"] if stage in ("tool_returned", "observed") else [])
        record = run.records()["operations"][0]
        assert (
            record["stage"]
            == {
                "started": "failed",
                "guard_allowed": "failed",
                "tool_dispatched": "dispatched",
                "tool_returned": "returned",
                "observed": "completed",
            }[stage]
        )
        assert run.records()["lifecycle_events"][-1]["stage"] in ("failed", "effect_unknown")


def test_session_forwards_guards_and_notifications(tmp_path):
    events = []

    async def deny(context):
        return GuardDecision(False, "harness policy")

    async def never(raw):
        pytest.fail("Denied tool executed")

    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="session", initial_state="x", limits=RunLimits(1, 1, 1)
    ) as run:
        session = Session(
            inference=ScriptedAdapter([ToolCall("act", "{}")]),
            tools=ToolBroker([Tool("act", lambda raw: None, never)]),
            evaluator=Evaluate(),
            run=run,
            grants=("act",),
            guards=(DispatchGuard("scope", deny),),
            on_event=events.append,
            policy=lambda view: (
                SessionStep("act", ("act",)) if view.last_step is None else SessionStop("done")
            ),
        )
        with pytest.raises(DispatchDenied):
            asyncio.run(session.execute())
        assert SessionTermination.from_json(run.outcome()).kind == "failed"
        assert [event.stage for event in events] == [
            "started",
            "inference_returned",
            "guard_denied",
        ]


def test_schema_four_remains_read_only_audit_evidence(tmp_path):
    path = tmp_path / "historical.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript((Path(__file__).parents[1] / "fixtures/schema_v4.sql").read_text())
    before = path.read_bytes()
    records = SQLiteRun.inspect(path)
    assert records["run"][0]["outcome"] == "historical stop"
    assert (
        records["guard_requirements"]
        == records["guard_decisions"]
        == records["lifecycle_events"]
        == []
    )
    assert path.read_bytes() == before
    with pytest.raises(ContractError, match="schema-5"):
        SQLiteRun.open(path)


def test_session_counts_durable_completion_when_final_notification_fails(tmp_path):
    async def execute(raw):
        return "observed"

    def notify(event):
        if event.stage == "observed":
            raise RuntimeError("notification failed after evaluation")

    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="notify-count", initial_state="x", limits=RunLimits(1, 1, 1)
    ) as run:
        session = Session(
            inference=ScriptedAdapter([ToolCall("act", "{}")]),
            tools=ToolBroker([Tool("act", lambda raw: None, execute, observation=True)]),
            evaluator=Evaluate(),
            run=run,
            grants=("act",),
            on_event=notify,
            policy=lambda view: SessionStep("act", ("act",)),
        )
        with pytest.raises(RuntimeError):
            asyncio.run(session.execute())
        assert SessionTermination.from_json(run.outcome()).completed_steps == 1
        assert run.completed_operations() == 1
        assert run.read().revision == 0
