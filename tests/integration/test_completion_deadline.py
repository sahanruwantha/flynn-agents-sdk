import asyncio

import pytest

from flynn_agents_sdk import (
    BudgetExhausted,
    Evaluation,
    InferenceRequest,
    RunLimits,
    Runtime,
    ScriptedAdapter,
    SQLiteRun,
    Tool,
    ToolBroker,
    ToolCall,
    Verdict,
    sqlite_run,
)


@pytest.mark.parametrize("expires_in", ["tool", "evaluator", "recovery", "direct"])
def test_expired_execution_retains_returned_evidence_without_publishing(
    tmp_path, monkeypatch, expires_in
):
    clock = [0.0]
    monkeypatch.setattr(sqlite_run.time, "monotonic", lambda: clock[0])
    evaluated = []

    async def execute(arguments):
        if expires_in == "tool":
            clock[0] = 2.0
        return "measured result"

    class Evaluator:
        async def evaluate(self, candidate):
            evaluated.append(candidate)
            if expires_in == "evaluator":
                clock[0] = 2.0
            return Evaluation(candidate, "test", "check", Verdict.SATISFIED, "checked", "next")

    with SQLiteRun.create(
        tmp_path / "run.sqlite",
        run_id="deadline",
        initial_state="base",
        limits=RunLimits(1, 1, 1, 1),
    ) as run:
        runtime = Runtime(
            inference=ScriptedAdapter([ToolCall("act", "{}")]),
            tools=ToolBroker([Tool("act", lambda _: None, execute, external_action=True)]),
            evaluator=Evaluator(),
            run=run,
            grants=("act",),
        )
        if expires_in in {"direct", "recovery"}:
            run.start("op", InferenceRequest("objective", run.read(), ("act",)))
            run.proposed("op", ToolCall("act", "{}"))
            run.dispatch("op", observation=False, external_action=True)
            candidate = run.returned("op", "measured result")
            clock[0] = 2.0
        with pytest.raises(BudgetExhausted):
            if expires_in == "direct":
                run.complete(
                    Evaluation(candidate, "test", "check", Verdict.SATISFIED, "checked", "next")
                )
            elif expires_in == "recovery":
                asyncio.run(runtime.recover())
            else:
                asyncio.run(runtime.step("objective"))
        assert len(evaluated) == (1 if expires_in == "evaluator" else 0)
        assert run.read().value == "base"
        assert run.read().revision == 0
        assert not run.records()["commits"]
        assert not run.records()["evaluations"]
        assert run.pending().stage == "returned"
        assert run.pending().candidate.output == "measured result"
        assert run.remaining() == {"inference": 0, "tool": 0, "external": 0}
