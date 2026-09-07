import asyncio
import json
import subprocess
import sys

import pytest

from flynn_agents_sdk import (
    Budget,
    BudgetExhausted,
    ContractError,
    Evaluation,
    InMemoryStore,
    Runtime,
    ScriptedAdapter,
    SQLiteJournal,
    State,
    Tool,
    ToolBroker,
    ToolCall,
    UnresolvedEffect,
    Verdict,
)


class Reject:
    async def evaluate(self, candidate):
        return Evaluation(
            candidate, "prediction/v1", "prediction", Verdict.FAILED, "Wrong prediction"
        )


def make_runtime(journal, execute, *, inference=None, budget=None, observation=True):
    return Runtime(
        inference=inference or ScriptedAdapter([ToolCall("act", "next")] * 3),
        tools=ToolBroker([Tool("act", lambda _: None, execute, True, observation)]),
        evaluator=Reject(),
        store=InMemoryStore("initial accepted state"),
        budget=budget or Budget(inference_calls=3, tool_calls=3),
        grants=("act",),
        journal=journal,
    )


def test_rejected_prediction_preserves_observation_and_next_context(tmp_path):
    requests = []

    class Adapter:
        async def generate(self, request):
            requests.append(request)
            return ToolCall("act", "next")

    async def action(_):
        return "new observation"

    path = tmp_path / "episode.sqlite"
    with SQLiteJournal(path, initial_observation="initial observation") as journal:
        runtime = make_runtime(journal, action, inference=Adapter())
        first = asyncio.run(runtime.step("test"))
        assert not first.committed
        asyncio.run(runtime.step("test"))
    assert requests[0].observation == "initial observation"
    assert requests[1].observation == "new observation"
    assert requests[1].base.value == "initial accepted state"
    with SQLiteJournal(path) as journal:
        assert journal.latest_observation() == "new observation"
        assert json.loads(journal.entries()[0].evaluation)["verdict"] == "failed"


def test_internal_tool_result_does_not_replace_environment_observation(tmp_path):
    async def action(_):
        return "hypothesis"

    with SQLiteJournal(tmp_path / "episode.sqlite", initial_observation="frame") as journal:
        asyncio.run(make_runtime(journal, action, observation=False).step("think"))
        assert journal.latest_observation() == "frame"
        assert journal.entries()[0].output == "hypothesis"


def test_process_death_after_external_effect_blocks_dispatch_on_reopen(tmp_path):
    path = tmp_path / "episode.sqlite"
    effect = tmp_path / "external-effect"
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys\n"
            "from pathlib import Path\n"
            "from flynn_agents_sdk import SQLiteJournal, State, ToolCall\n"
            "journal = SQLiteJournal(sys.argv[1])\n"
            "journal.begin('crashed', State(0, ''), ToolCall('act', 'next'))\n"
            "Path(sys.argv[2]).write_text('action happened')\n"
            "os._exit(23)\n",
            str(path),
            str(effect),
        ],
        check=False,
    )
    assert process.returncode == 23
    assert effect.read_text() == "action happened"

    async def forbidden(_):
        pytest.fail("Unresolved action was repeated")

    with SQLiteJournal(path) as journal:
        with pytest.raises(UnresolvedEffect):
            asyncio.run(make_runtime(journal, forbidden).step("retry"))
        assert journal.unresolved() == ("crashed",)
        assert len(journal.entries()) == 1


def test_timeout_during_action_preserves_unknown_effect(tmp_path):
    async def action(_):
        await asyncio.Event().wait()
        return "unreachable"

    path = tmp_path / "timeout.sqlite"
    with SQLiteJournal(path) as journal:
        runtime = make_runtime(
            journal,
            action,
            budget=Budget(inference_calls=3, tool_calls=3, wall_time_seconds=0.1),
        )
        with pytest.raises(TimeoutError):
            asyncio.run(runtime.step("test"))
        assert runtime.events[-1].stage == "effect_unknown"
    with SQLiteJournal(path) as journal:
        assert len(journal.unresolved()) == 1


def test_action_budget_refuses_dispatch_without_creating_intent(tmp_path):
    async def forbidden(_):
        pytest.fail("Budget should prevent dispatch")

    with SQLiteJournal(tmp_path / "budget.sqlite") as journal:
        budget = Budget(inference_calls=2, tool_calls=2, external_actions=0)
        with pytest.raises(BudgetExhausted, match="External action"):
            asyncio.run(make_runtime(journal, forbidden, budget=budget).step("test"))
        assert journal.entries() == ()
        assert budget.tools_remaining == 2


def test_journal_refuses_overwrite_and_competing_dispatch(tmp_path):
    path = tmp_path / "episode.sqlite"
    with SQLiteJournal(path) as first, SQLiteJournal(path) as second:
        first.begin("a", State(0, "base"), ToolCall("act", "next"))
        with pytest.raises(UnresolvedEffect):
            second.begin("b", State(0, "base"), ToolCall("act", "next"))
        first.returned("a", "result")
        with pytest.raises(ContractError):
            first.returned("a", "altered history")


def test_terminal_outcome_survives_reopen_and_prevents_new_dispatch(tmp_path):
    path = tmp_path / "finished.sqlite"
    with SQLiteJournal(path) as journal:
        journal.finish("budget_exhausted")
        with pytest.raises(ContractError, match="already ended"):
            journal.finish("completed")
    with SQLiteJournal(path) as journal:
        assert journal.outcome() == "budget_exhausted"
        with pytest.raises(ContractError, match="already ended"):
            journal.begin("new", State(0, ""), ToolCall("act", "next"))


def test_cancellation_after_action_does_not_allow_another_dispatch(tmp_path):
    async def action(_):
        raise asyncio.CancelledError

    path = tmp_path / "cancelled.sqlite"
    with SQLiteJournal(path) as journal:
        runtime = make_runtime(journal, action)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(runtime.step("act"))
    with SQLiteJournal(path) as journal:
        with pytest.raises(UnresolvedEffect):
            asyncio.run(make_runtime(journal, action).step("act"))


def test_evaluator_crash_does_not_erase_returned_result(tmp_path):
    class Broken:
        async def evaluate(self, candidate):
            raise RuntimeError("broken evaluator")

    async def action(_):
        return "observed"

    with SQLiteJournal(tmp_path / "evaluation.sqlite") as journal:
        runtime = Runtime(
            inference=ScriptedAdapter([ToolCall("act", "next")]),
            tools=ToolBroker([Tool("act", lambda _: None, action, observation=True)]),
            evaluator=Broken(),
            store=InMemoryStore(),
            budget=Budget(inference_calls=1, tool_calls=1),
            grants=("act",),
            journal=journal,
        )
        with pytest.raises(RuntimeError, match="broken evaluator"):
            asyncio.run(runtime.step("test"))
        assert journal.latest_observation() == "observed"
        assert journal.unresolved() == ()
        assert journal.entries()[0].evaluation is None
