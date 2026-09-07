import asyncio
from dataclasses import replace

import pytest

from flynn_agents_sdk import (
    Budget,
    BudgetExhausted,
    Candidate,
    ContractError,
    Evaluation,
    InMemoryStore,
    Runtime,
    ScriptedAdapter,
    Tool,
    ToolBroker,
    ToolCall,
    Verdict,
)


def validate(arguments):
    if arguments != "4":
        raise ValueError("expected 4")


class Check:
    async def evaluate(self, candidate):
        return Evaluation(
            candidate,
            "successor/v1",
            "integer successor",
            Verdict.SATISFIED if candidate.output == "5" else Verdict.FAILED,
            "Expected output 5",
        )


def setup(
    *,
    call=None,
    budget=None,
    evaluator=None,
    execute=None,
    grants=("increment",),
):
    executions = []

    async def increment(arguments):
        executions.append(arguments)
        return "5"

    store = InMemoryStore("4")
    runtime = Runtime(
        inference=ScriptedAdapter([ToolCall("increment", "4") if call is None else call]),
        tools=ToolBroker([Tool("increment", validate, execute or increment)]),
        evaluator=evaluator or Check(),
        store=store,
        budget=budget or Budget(inference_calls=1, tool_calls=1),
        grants=grants,
    )
    return runtime, store, executions


def test_complete_step():
    runtime, store, executions = setup()
    result = asyncio.run(runtime.step("increment"))
    assert result.committed
    assert store.read().value == "5"
    assert store.read().revision == 1
    assert executions == ["4"]
    assert [event.stage for event in runtime.events] == [
        "started",
        "tool_dispatched",
        "tool_returned",
        "committed",
    ]


@pytest.mark.parametrize(
    ("call", "grants", "message"),
    [
        (ToolCall("increment", "4"), (), "not granted"),
        (ToolCall("missing", "4"), ("missing",), "not registered"),
        (ToolCall("increment", "wrong"), ("increment",), "Invalid arguments"),
        ("I succeeded", ("increment",), "ToolCall"),
        (ToolCall("increment", {"x": 4}), ("increment",), "must be strings"),
    ],
)
def test_invalid_proposal_cannot_execute(call, grants, message):
    runtime, store, executions = setup(call=call, grants=grants)
    with pytest.raises(ContractError, match=message):
        asyncio.run(runtime.step("increment"))
    assert executions == []
    assert store.read().revision == 0


@pytest.mark.parametrize(("inference", "tools"), [(0, 1), (1, 0)])
def test_exhausted_budget_prevents_dispatch(inference, tools):
    runtime, store, executions = setup(budget=Budget(inference_calls=inference, tool_calls=tools))
    with pytest.raises(BudgetExhausted):
        asyncio.run(runtime.step("increment"))
    assert executions == []
    assert store.read().revision == 0


@pytest.mark.parametrize("verdict", [Verdict.FAILED, Verdict.UNAVAILABLE])
def test_nonpassing_evaluation_is_recorded_without_commit(verdict):
    class Reject:
        async def evaluate(self, candidate):
            return Evaluation(candidate, "test/v1", "test", verdict, "No support")

    runtime, store, _ = setup(evaluator=Reject())
    result = asyncio.run(runtime.step("increment"))
    assert not result.committed
    assert store.read().revision == 0
    assert runtime.events[-1].stage == "not_accepted"


def test_success_string_is_not_evidence():
    async def forged(arguments):
        return "SUCCESS: task completed"

    runtime, store, _ = setup(execute=forged)
    assert not asyncio.run(runtime.step("increment")).committed
    assert store.read().value == "4"


@pytest.mark.parametrize(
    "change",
    [
        {"output": "different"},
        {"id": "other"},
        {"call": ToolCall("other", "4")},
    ],
)
def test_mismatched_evaluation_rejected(change):
    class Mismatch:
        async def evaluate(self, candidate):
            return await Check().evaluate(replace(candidate, **change))

    runtime, store, _ = setup(evaluator=Mismatch())
    with pytest.raises(ContractError, match="exact candidate"):
        asyncio.run(runtime.step("increment"))
    assert store.read().revision == 0


def test_stale_revision_during_evaluation_is_rejected():
    class ConcurrentUpdate:
        async def evaluate(self, candidate):
            other = replace(candidate, id="other")
            store.commit(other, await Check().evaluate(other))
            return await Check().evaluate(candidate)

    runtime, store, _ = setup(evaluator=ConcurrentUpdate())
    with pytest.raises(ContractError, match="Stale candidate"):
        asyncio.run(runtime.step("increment"))
    assert store.read().revision == 1
    assert runtime.events[-1].detail == "commit: ContractError"


def test_tool_failure_consumes_budget_and_marks_unknown_effect():
    attempts = []

    async def fails(arguments):
        attempts.append(arguments)
        raise OSError("lost response")

    budget = Budget(inference_calls=1, tool_calls=1)
    runtime, store, _ = setup(execute=fails, budget=budget)
    with pytest.raises(OSError, match="lost response"):
        asyncio.run(runtime.step("increment"))
    assert attempts == ["4"]
    assert budget.tools_remaining == 0
    assert budget.inference_remaining == 0
    assert store.read().revision == 0
    assert runtime.events[-1].stage == "effect_unknown"


def test_cancellation_during_dispatch_is_not_retried():
    async def scenario():
        entered = asyncio.Event()
        attempts = []

        async def slow(arguments):
            attempts.append(arguments)
            entered.set()
            await asyncio.Event().wait()

        budget = Budget(inference_calls=1, tool_calls=1)
        runtime, store, _ = setup(execute=slow, budget=budget)
        task = asyncio.create_task(runtime.step("increment"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.events[-1].stage == "effect_unknown"
        assert store.read().revision == 0
        assert attempts == ["4"]
        assert budget.tools_remaining == 0

    asyncio.run(scenario())


def test_cancellation_before_dispatch_has_no_tool_effect():
    class CancelInference:
        async def generate(self, request):
            raise asyncio.CancelledError

    store = InMemoryStore()
    runtime = Runtime(
        inference=CancelInference(),
        tools=ToolBroker([]),
        evaluator=Check(),
        store=store,
        budget=Budget(inference_calls=1, tool_calls=1),
        grants=(),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.step("test"))
    assert runtime.events[-1].stage == "cancelled"
    assert store.read().revision == 0


def test_steps_on_one_runtime_are_serialized():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        bases = []

        class Adapter:
            async def generate(self, request):
                bases.append(request.base.revision)
                return ToolCall("increment", "4")

        async def slow(arguments):
            entered.set()
            await release.wait()
            return "5"

        store = InMemoryStore("4")
        runtime = Runtime(
            inference=Adapter(),
            tools=ToolBroker([Tool("increment", validate, slow)]),
            evaluator=Check(),
            store=store,
            budget=Budget(inference_calls=2, tool_calls=2),
            grants=("increment",),
        )
        first = asyncio.create_task(runtime.step("one"))
        await entered.wait()
        second = asyncio.create_task(runtime.step("two"))
        release.set()
        results = await asyncio.gather(first, second)
        assert bases == [0, 1]
        assert [result.state.revision for result in results] == [1, 2]

    asyncio.run(scenario())


def test_store_refuses_nonpassing_direct_publication():
    store = InMemoryStore("4")
    candidate = Candidate("id", store.read(), ToolCall("increment", "4"), "5")
    evaluation = Evaluation(candidate, "test/v1", "test", Verdict.FAILED, "Rejected")
    with pytest.raises(ContractError, match="satisfied"):
        store.commit(candidate, evaluation)
    assert store.read().revision == 0


def test_step_grants_cannot_expand_or_be_ignored():
    runtime, _, executions = setup()
    with pytest.raises(ContractError, match="expand"):
        asyncio.run(runtime.step("test", grants=("other",)))
    assert executions == []
    with pytest.raises(ContractError, match="not granted"):
        asyncio.run(runtime.step("test", grants=()))
    assert executions == []


def test_prepared_request_narrowing_is_enforced():
    runtime, _, executions = setup()
    runtime._prepare_request = lambda request: replace(request, allowed_tools=())
    with pytest.raises(ContractError, match="not granted"):
        asyncio.run(runtime.step("test"))
    assert executions == []


def test_prepared_request_cannot_restore_removed_grants():
    runtime, _, executions = setup()
    runtime._prepare_request = lambda request: replace(request, allowed_tools=("increment",))
    with pytest.raises(ContractError, match="expand"):
        asyncio.run(runtime.step("test", grants=()))
    assert executions == []


def test_step_override_does_not_change_later_authority():
    runtime, _, executions = setup(
        budget=Budget(inference_calls=2, tool_calls=1),
    )
    # Expansion is refused before inference, leaving the scripted call available.
    with pytest.raises(ContractError):
        asyncio.run(runtime.step("test", grants=("other",)))
    assert asyncio.run(runtime.step("test")).committed
    assert executions == ["4"]
