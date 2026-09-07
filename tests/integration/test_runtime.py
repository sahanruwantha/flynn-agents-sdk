import asyncio
from dataclasses import replace

import pytest

from flynn_agents_sdk import (
    BudgetExhausted,
    ContractError,
    Evaluation,
    InferenceResult,
    RunLimits,
    Runtime,
    ScriptedAdapter,
    SQLiteRun,
    Tool,
    ToolBroker,
    ToolCall,
    ToolSpec,
    UnresolvedEffect,
    Verdict,
)


class Check:
    async def evaluate(self, candidate):
        return Evaluation(
            candidate, "successor/v1", "integer", Verdict.SATISFIED, "Checked", "accepted:5"
        )


@pytest.fixture
def run(tmp_path):
    with SQLiteRun.create(
        tmp_path / "run.db", run_id="test", initial_state="4", limits=RunLimits(3, 3, 2)
    ) as value:
        yield value


def make(run, *, adapter=None, evaluator=None, execute=None, grants=("increment",), prepare=None):
    async def increment(arguments):
        return "5"

    def validate(arguments):
        if arguments != "4":
            raise ValueError("Expected 4")

    return Runtime(
        inference=adapter or ScriptedAdapter([ToolCall("increment", "4")] * 3),
        tools=ToolBroker([Tool("increment", validate, execute or increment, observation=True)]),
        evaluator=evaluator or Check(),
        run=run,
        grants=grants,
        prepare_request=prepare,
    )


def test_observation_and_state_update_are_independent(run):
    result = asyncio.run(make(run).step("increment"))
    assert result.committed and result.state.revision == 1
    assert result.candidate.output == "5"
    assert run.latest_observation() == "5"
    assert run.read().value == "accepted:5"
    assert len(run.records()["commits"]) == 1


@pytest.mark.parametrize("verdict", list(Verdict))
@pytest.mark.parametrize("update", [None, "proposed"])
def test_assessment_does_not_erase_observation_or_imply_commit(run, verdict, update):
    class Assess:
        async def evaluate(self, candidate):
            return Evaluation(candidate, "test/v1", "test", verdict, "Checked", update)

    result = asyncio.run(make(run, evaluator=Assess()).step("test"))
    assert result.committed == (verdict is Verdict.SATISFIED and update is not None)
    assert run.latest_observation() == "5"
    assert len(run.records()["evaluations"]) == 1
    assert run.pending() is None


@pytest.mark.parametrize(
    "call,grants",
    [
        (ToolCall("increment", "wrong"), ("increment",)),
        (ToolCall("missing", "4"), ("missing",)),
        (ToolCall("increment", "4"), ()),
        ("SUCCESS", ("increment",)),
        (ToolCall("increment", {}), ("increment",)),
    ],
)
def test_invalid_proposals_never_dispatch(run, call, grants):
    async def forbidden(_):
        pytest.fail("Invalid proposal executed")

    with pytest.raises(ContractError):
        asyncio.run(
            make(run, adapter=ScriptedAdapter([call]), grants=grants, execute=forbidden).step(
                "test"
            )
        )
    assert run.remaining() == {"inference": 2, "tool": 3, "external": 2}
    assert run.read().revision == 0
    assert run.pending() is None


@pytest.mark.parametrize(
    "change", [{"output": "other"}, {"id": "other"}, {"call": ToolCall("other", "4")}]
)
def test_mismatched_evaluation_cannot_commit(run, change):
    class Wrong:
        async def evaluate(self, candidate):
            return await Check().evaluate(replace(candidate, **change))

    with pytest.raises(ContractError):
        asyncio.run(make(run, evaluator=Wrong()).step("test"))
    assert run.read().revision == 0
    assert run.pending().stage == "returned"
    assert run.records()["evaluations"] == []


def test_explicit_recovery_evaluates_returned_result_without_repeating_tool(run):
    class Broken:
        async def evaluate(self, candidate):
            raise RuntimeError("evaluator crashed")

    with pytest.raises(RuntimeError):
        asyncio.run(make(run, evaluator=Broken()).step("test"))
    counts = run.remaining()
    with pytest.raises(ContractError, match="recovery"):
        asyncio.run(make(run).step("test"))
    result = asyncio.run(make(run).recover())
    assert result.committed and run.remaining() == counts
    assert asyncio.run(make(run).recover()) is None


@pytest.mark.parametrize("exception", [OSError("lost result"), asyncio.CancelledError()])
def test_unknown_effect_stays_blocked(run, exception):
    async def broken(_):
        raise exception

    with pytest.raises(type(exception)):
        asyncio.run(make(run, execute=broken).step("test"))
    assert run.pending().stage == "dispatched"
    assert run.remaining()["tool"] == 2
    with pytest.raises(UnresolvedEffect):
        asyncio.run(make(run).recover())
    with pytest.raises(UnresolvedEffect):
        asyncio.run(make(run).step("retry"))


def test_cancellation_before_dispatch_preserves_spend_without_unknown_effect(run):
    class Cancel:
        async def generate(self, request):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(make(run, adapter=Cancel()).step("test"))
    assert run.pending() is None
    assert run.remaining() == {"inference": 2, "tool": 3, "external": 2}


@pytest.mark.parametrize("reopen", [False, True])
def test_terminal_run_never_spends(run, reopen):
    run.finish("completed")
    path = run.path
    if reopen:
        run.close()
        run = SQLiteRun.open(path)
    try:
        with pytest.raises(ContractError, match="already ended"):
            asyncio.run(make(run).step("test"))
        assert run.remaining() == {"inference": 3, "tool": 3, "external": 2}
        assert run.records()["operations"] == []
    finally:
        if reopen:
            run.close()


def test_finishing_during_inference_still_blocks_dispatch(run):
    class End:
        async def generate(self, request):
            run.finish("cancelled")
            return InferenceResult.scripted(ToolCall("increment", "4"))

    with pytest.raises(ContractError, match="already ended"):
        asyncio.run(make(run, adapter=End()).step("test"))
    assert run.remaining()["tool"] == 3


def test_grants_are_narrowed_and_not_restored_by_preparation(run):
    runtime = make(run, prepare=lambda request: replace(request, allowed_tools=("increment",)))
    with pytest.raises(ContractError, match="expand"):
        asyncio.run(runtime.step("test", grants=()))
    assert run.remaining()["inference"] == 3
    with pytest.raises(ContractError, match="expand"):
        asyncio.run(runtime.step("test", grants=("other",)))
    assert asyncio.run(runtime.step("test")).committed


def test_prepared_narrowing_is_enforced_at_dispatch(run):
    runtime = make(run, prepare=lambda request: replace(request, allowed_tools=()))
    with pytest.raises(ContractError, match="not granted"):
        asyncio.run(runtime.step("test"))
    assert run.remaining()["tool"] == 3


def test_prepared_domain_schema_reaches_inference(run):
    schema = ToolSpec("increment", "Only the current legal move", '{"const":4}')

    class Inspect:
        async def generate(self, request):
            assert request.tools == (schema,)
            return InferenceResult.scripted(ToolCall("increment", "4"))

    runtime = make(
        run, adapter=Inspect(), prepare=lambda request: replace(request, tools=(schema,))
    )
    assert asyncio.run(runtime.step("test")).committed


def test_prepared_state_cannot_be_substituted(run):
    runtime = make(
        run, prepare=lambda request: replace(request, base=replace(request.base, value="forged"))
    )
    with pytest.raises(ContractError, match="substitute"):
        asyncio.run(runtime.step("test"))
    assert run.remaining()["inference"] == 3


def test_two_runtimes_cannot_mutate_one_run_concurrently(run):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow(_):
            entered.set()
            await release.wait()
            return "5"

        first = asyncio.create_task(make(run, execute=slow).step("first"))
        await entered.wait()
        with pytest.raises(UnresolvedEffect):
            await make(run).step("second")
        release.set()
        await first

    asyncio.run(scenario())


def test_exhausted_inference_budget_blocks_provider(run):
    runtime = make(run)
    for _ in range(3):
        asyncio.run(runtime.step("test"))
    with pytest.raises(BudgetExhausted):
        asyncio.run(runtime.step("test"))
    assert len(run.records()["operations"]) == 3
