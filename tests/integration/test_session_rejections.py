import asyncio

import pytest

from flynn_agents_sdk import (
    BudgetExhausted,
    Evaluation,
    InferenceRejected,
    ProposalRejected,
    RunLimits,
    ScriptedAdapter,
    Session,
    SessionStep,
    SessionStop,
    SQLiteRun,
    Tool,
    ToolBroker,
    ToolCall,
    Verdict,
)


class Observe:
    async def evaluate(self, candidate):
        return Evaluation(candidate, "test", "observation", Verdict.SATISFIED, "recorded")


@pytest.mark.parametrize("source", ["validation", "provider", "handler", "notification", "guard"])
def test_only_certified_predispatch_rejections_reach_policy(tmp_path, source):
    seen = []
    executed = []

    class Adapter:
        calls = 0

        async def generate(self, request):
            self.calls += 1
            if source == "provider" and self.calls == 1:
                raise InferenceRejected("bad response")
            from flynn_agents_sdk import InferenceResult

            return InferenceResult.scripted(ToolCall("act", "{}" if self.calls > 1 else "bad"))

    def validate(raw):
        if source == "validation" and raw == "bad":
            raise ValueError("bad arguments")

    async def execute(raw):
        executed.append(raw)
        if source == "handler":
            raise ProposalRejected("handler is not a validator")
        return "{}"

    def notification(event):
        if source == "notification" and event.stage == "inference_returned":
            raise ProposalRejected("observer failure")

    async def guard(context):
        raise ProposalRejected("guard failure")

    def rejected(error, view):
        seen.append((type(error), view.completed_steps, view.observation))
        return SessionStep("correct", ("act",))

    from flynn_agents_sdk import DispatchGuard

    with SQLiteRun.create(
        tmp_path / "run.db", run_id="test", initial_state="", limits=RunLimits(3, 2, 2)
    ) as run:
        session = Session(
            inference=Adapter(),
            tools=ToolBroker(
                [Tool("act", validate, execute, external_action=True, observation=True)]
            ),
            evaluator=Observe(),
            run=run,
            grants=("act",),
            policy=lambda view: (
                SessionStop("done") if view.last_step else SessionStep("act", ("act",))
            ),
            on_rejection=rejected,
            on_event=notification,
            guards=(DispatchGuard("test", guard),) if source == "guard" else (),
        )
        if source in ("validation", "provider"):
            result = asyncio.run(session.execute())
            assert result.completed_steps == 1
            assert len(seen) == 1 and seen[0][1:] == (0, None)
            assert len(executed) == 1
            assert len(run.records()["operations"]) == 2
        else:
            with pytest.raises(ProposalRejected):
                asyncio.run(session.execute())
            assert not seen
            assert bool(run.pending()) == (source == "handler")


def test_corrections_spend_existing_budget(tmp_path):
    async def execute(raw):
        pytest.fail("invalid call dispatched")

    def validate(raw):
        raise ValueError("invalid")

    with SQLiteRun.create(
        tmp_path / "run.db", run_id="budget", initial_state="", limits=RunLimits(2, 2, 2)
    ) as run:
        session = Session(
            inference=ScriptedAdapter([ToolCall("act", "{}")] * 3),
            tools=ToolBroker([Tool("act", validate, execute)]),
            evaluator=Observe(),
            run=run,
            grants=("act",),
            policy=lambda view: SessionStep("act", ("act",)),
            on_rejection=lambda error, view: SessionStep("correct", ("act",)),
        )
        with pytest.raises(BudgetExhausted):
            asyncio.run(session.execute())
        assert len(run.records()["operations"]) == 2
        assert not run.pending()
