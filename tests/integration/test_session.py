import asyncio
import json
from dataclasses import replace

import pytest

from flynn_agents_sdk import (
    BudgetExhausted,
    ContractError,
    Evaluation,
    RunLimits,
    Runtime,
    ScriptedAdapter,
    Session,
    SessionStep,
    SessionStop,
    SessionTermination,
    SQLiteRun,
    TextContent,
    Tool,
    ToolBroker,
    ToolCall,
    ToolResult,
    UnresolvedEffect,
    Verdict,
)


class Observe:
    async def evaluate(self, candidate):
        return Evaluation(candidate, "fixture", "observation", Verdict.SATISFIED, "recorded")


def build(run, policy, *, handler=None, on_step=None):
    async def default_handler(args):
        return ToolResult((TextContent("measurement"),))

    tool = Tool.structured(
        "measure",
        description="Read a measurement",
        parameters_json='{"type":"object"}',
        validate=lambda args: None,
        execute=handler or default_handler,
        external_action=True,
    )
    return Session(
        inference=ScriptedAdapter([ToolCall("measure", "{}")] * 3),
        tools=ToolBroker([tool]),
        evaluator=Observe(),
        run=run,
        grants=("measure",),
        policy=policy,
        on_step=on_step,
        prepare_request=lambda request: replace(request, observation="selected feedback"),
    )


def test_explicit_stop_is_durable_without_domain_commit(tmp_path):
    seen = []
    events = []

    def policy(view):
        seen.append(view)
        return (
            SessionStep("measure", ("measure",))
            if view.last_step is None
            else SessionStop("evidence collected")
        )

    path = tmp_path / "run.sqlite"
    with SQLiteRun.create(
        path, run_id="session", initial_state="unaccepted", limits=RunLimits(3, 3, 3)
    ) as run:
        session = build(run, policy, on_step=events.append)
        terminal = asyncio.run(session.execute())
        assert terminal == SessionTermination("stopped", "evidence collected", 1)
        assert len(events) == 1
        assert seen[1].completed_steps == 1
        assert seen[1].last_step is events[0]
        assert seen[1].observation == events[0].candidate.output
        request = json.loads(run.records()["operations"][0]["request"])
        assert request["observation"] == "selected feedback"
        with pytest.raises(ContractError, match="already ended"):
            asyncio.run(session.execute())
        assert len(seen) == 2
    with SQLiteRun.open(path) as run:
        assert SessionTermination.from_json(run.outcome()) == terminal
        assert run.read().revision == 0
        assert run.read().value == "unaccepted"


def test_budget_exhaustion_records_termination_and_propagates(tmp_path):
    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="cap", initial_state="x", limits=RunLimits(1, 1, 1)
    ) as run:
        with pytest.raises(BudgetExhausted):
            asyncio.run(build(run, lambda view: SessionStep("measure", ("measure",))).execute())
        terminal = SessionTermination.from_json(run.outcome())
        assert terminal.kind == "budget_exhausted"
        assert terminal.completed_steps == 1
        assert len(run.records()["operations"]) == 1


@pytest.mark.parametrize("stage", ["policy", "handler", "observer"])
def test_failures_are_not_retried_or_flattened(tmp_path, stage):
    calls = []

    def fail():
        calls.append(stage)
        raise ValueError("sensitive error payload")

    def policy(view):
        if stage == "policy":
            fail()
        return SessionStep("measure", ("measure",))

    async def handler(args):
        if stage == "handler":
            fail()
        return ToolResult()

    def observer(step):
        fail()

    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="failure", initial_state="x", limits=RunLimits(3, 3, 3)
    ) as run:
        with pytest.raises(ValueError, match="sensitive error payload"):
            asyncio.run(
                build(
                    run, policy, handler=handler, on_step=observer if stage == "observer" else None
                ).execute()
            )
        assert calls == [stage]
        terminal = SessionTermination.from_json(run.outcome())
        assert terminal.kind == "failed"
        assert terminal.reason == "ValueError"
        assert "sensitive" not in run.outcome()
        assert (run.pending() is not None) == (stage == "handler")


@pytest.mark.parametrize("cancel", [True, False])
def test_cancellation_and_timeout_preserve_unknown_effect(tmp_path, cancel):
    started = asyncio.Event()

    async def handler(args):
        started.set()
        await asyncio.sleep(60)
        return ToolResult()

    async def execute(session):
        task = asyncio.create_task(session.execute())
        await asyncio.wait_for(started.wait(), timeout=3)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task

    with SQLiteRun.create(
        tmp_path / "run.sqlite",
        run_id="interrupt",
        initial_state="x",
        limits=RunLimits(3, 3, 3, wall_time_seconds=2),
    ) as run:
        asyncio.run(
            execute(build(run, lambda view: SessionStep("act", ("measure",)), handler=handler))
        )
        assert SessionTermination.from_json(run.outcome()).kind == (
            "cancelled" if cancel else "timed_out"
        )
        assert run.pending() is not None
        assert run.remaining()["external"] == 2


def test_pending_run_refused_before_policy(tmp_path):
    calls = []

    async def fail(args):
        raise RuntimeError("effect uncertain")

    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="pending", initial_state="x", limits=RunLimits(2, 2, 2)
    ) as run:
        tool = Tool("act", lambda raw: None, fail, observation=True, external_action=True)
        runtime = Runtime(
            inference=ScriptedAdapter([ToolCall("act", "{}")]),
            tools=ToolBroker([tool]),
            evaluator=Observe(),
            run=run,
            grants=("act",),
        )
        with pytest.raises(RuntimeError):
            asyncio.run(runtime.step("act"))
        with pytest.raises(UnresolvedEffect):
            asyncio.run(build(run, calls.append).execute())
        assert calls == []
        assert run.outcome() is None


def test_grants_cannot_expand_and_no_tool_executes(tmp_path):
    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="grants", initial_state="x", limits=RunLimits(2, 2, 2)
    ) as run:
        with pytest.raises(ContractError, match="expand"):
            asyncio.run(build(run, lambda view: SessionStep("act", ("unauthorized",))).execute())
        assert run.records()["operations"] == []
        assert SessionTermination.from_json(run.outcome()).kind == "failed"


def test_stop_before_any_inference_and_strict_terminal_record(tmp_path):
    with SQLiteRun.create(
        tmp_path / "run.sqlite", run_id="empty", initial_state="x", limits=RunLimits(0, 0, 0)
    ) as run:
        terminal = asyncio.run(build(run, lambda view: SessionStop("nothing due")).execute())
        assert terminal.completed_steps == 0
        assert run.records()["operations"] == []
        record = json.loads(run.outcome())
        for change in (
            {"kind": "success"},
            {"completed_steps": True},
            {"schema": "unknown"},
            {"extra": 1},
        ):
            with pytest.raises(ContractError):
                SessionTermination.from_json(json.dumps({**record, **change}))


def test_expired_initial_deadline_records_budget_stop_before_policy(tmp_path):
    import time

    calls = []
    with SQLiteRun.create(
        tmp_path / "run.sqlite",
        run_id="expired",
        initial_state="x",
        limits=RunLimits(1, 1, 1, wall_time_seconds=0.001),
    ) as run:
        time.sleep(0.01)
        with pytest.raises(BudgetExhausted):
            asyncio.run(build(run, calls.append).execute())
        assert calls == []
        assert SessionTermination.from_json(run.outcome()).kind == "budget_exhausted"
