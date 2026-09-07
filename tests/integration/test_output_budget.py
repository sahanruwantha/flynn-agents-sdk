"""Output admission survives rejection, uncertainty and process death."""

import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import httpx
import pytest

from flynn_agents_sdk import (
    BudgetExhausted,
    ContractError,
    Evaluation,
    InferenceRequest,
    OutputReservation,
    RunLimits,
    Runtime,
    ScriptedAdapter,
    SQLiteRun,
    Tool,
    ToolBroker,
    ToolCall,
    Verdict,
    summarize_usage,
)
from flynn_agents_sdk.deepseek import DeepSeekAdapter, ProviderError


class Observe:
    async def evaluate(self, candidate):
        return Evaluation(candidate, "output-fixture/v1", "observation", Verdict.SATISFIED, "read")


def runtime(run, adapter):
    async def read(arguments):
        return arguments

    return Runtime(
        run=run,
        inference=adapter,
        evaluator=Observe(),
        grants=("read",),
        tools=ToolBroker([Tool("read", lambda _: None, read, observation=True)]),
    )


def body(*, valid=True, usage):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {"name": "read", "arguments": "{}" if valid else "bad"},
                        }
                    ]
                },
            }
        ],
        "usage": usage,
    }


def create(path, limit=7):
    return SQLiteRun.create(
        path, run_id="output", initial_state="base", limits=RunLimits(9, 9, 9, output_tokens=limit)
    )


def test_known_output_settles_reservation_and_scripted_work_survives_exhaustion(tmp_path):
    path = tmp_path / "run.db"
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        records = SQLiteRun.inspect(path)
        assert records["output_reservations"][-1]["tokens"] == sent[-1]["max_tokens"]
        assert records["operations"][-1]["stage"] == "inference"
        return httpx.Response(
            200,
            json=body(
                usage={
                    "prompt_tokens": 1000,
                    "completion_tokens": 3 if len(sent) == 1 else 4,
                }
            ),
        )

    async def scenario():
        with create(path) as run:
            async with DeepSeekAdapter(
                api_key="secret", max_tokens=5, transport=httpx.MockTransport(handler)
            ) as adapter:
                task = runtime(run, adapter)
                await task.step("first")
                assert run.output_budget().available == 4
                await task.step("second")
                assert run.output_budget().spent == 7
                before = run.records()
                with pytest.raises(BudgetExhausted):
                    await task.step("refused before request")
                assert run.records() == before
            await runtime(run, ScriptedAdapter([ToolCall("read", "{}")])).step("canonical")
            assert run.output_budget().available == 0
            assert run.usage_summary()["model_requests"] == 2
        with SQLiteRun.open(path) as run:
            assert run.output_budget().spent == 7
            assert run.output_budget().available == 0

    asyncio.run(scenario())
    assert [item["max_tokens"] for item in sent] == [5, 4]


@pytest.mark.parametrize("failure", ["malformed", "unknown", "partial_input", "timeout", "breach"])
def test_failed_or_partial_response_cannot_reset_output_spend(tmp_path, failure):
    path = tmp_path / "run.db"
    sent = []

    def handler(request):
        sent.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline timeout")
        usage = {"prompt_tokens": 11, "completion_tokens": 3}
        if failure == "unknown":
            usage.pop("completion_tokens")
        if failure == "partial_input":
            usage.pop("prompt_tokens")
        if failure == "breach":
            usage["completion_tokens"] = 6
        return httpx.Response(200, json=body(valid=failure != "malformed", usage=usage))

    async def scenario():
        with create(path) as run:
            async with DeepSeekAdapter(
                api_key="secret", max_tokens=5, transport=httpx.MockTransport(handler)
            ) as adapter:
                task = runtime(run, adapter)
                if failure in ("malformed", "timeout", "breach"):
                    with pytest.raises(ProviderError if failure != "breach" else ContractError):
                        await task.step("read")
                    assert run.remaining()["tool"] == 9
                else:
                    await task.step("read")
        with SQLiteRun.open(path) as run:
            budget = run.output_budget()
            if failure in ("unknown", "timeout"):
                assert (budget.held, budget.unresolved, budget.available) == (5, 1, 2)
            elif failure == "breach":
                assert (budget.spent, budget.breached, budget.available) == (6, 1, 1)
            else:
                assert (budget.spent, budget.held, budget.available) == (3, 0, 4)
            if failure in ("unknown", "timeout", "breach"):
                async with DeepSeekAdapter(
                    api_key="secret", max_tokens=5, transport=httpx.MockTransport(handler)
                ) as adapter:
                    before = run.records()
                    with pytest.raises(BudgetExhausted, match="unresolved|breached"):
                        await runtime(run, adapter).step("do not retry")
                    assert run.records() == before
                # No more model spend is authorized, but deterministic work is permitted.
                await runtime(run, ScriptedAdapter([ToolCall("read", "{}")])).step("scripted")
            assert len(run.records()["inference_usage"]) >= 1

    asyncio.run(scenario())
    assert len(sent) == 1


def test_death_keeps_reservation_held_even_after_explicit_recovery(tmp_path):
    path = tmp_path / "run.db"
    with create(path):
        pass
    pid = os.fork()
    if pid == 0:
        with SQLiteRun.open(path) as run:
            run.start(
                "died",
                InferenceRequest(
                    "read",
                    run.read(),
                    ("read",),
                    max_output_tokens=4,
                ),
                OutputReservation("model", 4),
            )
            os._exit(23)
    assert os.waitpid(pid, 0)[1] == 23 << 8
    with SQLiteRun.open(path) as run:
        asyncio.run(runtime(run, ScriptedAdapter([])).recover())
        assert (run.output_budget().held, run.output_budget().available) == (4, 3)
        assert run.output_budget().unresolved == 1
        assert run.usage_summary()["unreported_invocations"] == 1
        with pytest.raises(BudgetExhausted, match="unresolved"):
            run.start(
                "new",
                InferenceRequest(
                    "read",
                    run.read(),
                    ("read",),
                    max_output_tokens=1,
                ),
                OutputReservation("model", 1),
            )
    with sqlite3.connect(path) as db:
        for sql in ("DELETE FROM output_reservations", "UPDATE output_reservations SET tokens=0"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(sql)


def test_admission_is_atomic_and_requires_a_capable_adapter(tmp_path):
    class Unsupported:
        async def generate(self, request):
            pytest.fail("uncapped adapter invoked")

    with create(tmp_path / "run.db", limit=0) as run:
        with pytest.raises(ContractError, match="plan_output"):
            asyncio.run(runtime(run, Unsupported()).step("refuse"))
        with pytest.raises(BudgetExhausted):
            run.start(
                "oversized",
                InferenceRequest(
                    "read",
                    run.read(),
                    ("read",),
                    max_output_tokens=1,
                ),
                OutputReservation("model", 1),
            )
        assert run.records()["operations"] == []
        assert run.records()["reservations"] == []
        asyncio.run(runtime(run, ScriptedAdapter([ToolCall("read", "{}")])).step("scripted"))


def test_schema_three_golden_keeps_known_usage_but_cannot_execute(tmp_path):
    path = tmp_path / "historical.db"
    fixture = Path(__file__).parents[1] / "fixtures" / "schema_v3.sql"
    with sqlite3.connect(path) as db:
        db.executescript(fixture.read_text())
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    records = SQLiteRun.inspect(path)
    assert summarize_usage(records)["known_output_tokens"] == 5
    assert records["output_reservations"] == []
    assert "max_output_tokens" not in json.loads(records["operations"][0]["request"])
    with pytest.raises(ContractError, match="schema-4"):
        SQLiteRun.open(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_adapter_kind_breach_preserves_usage_and_refuses_dispatch(tmp_path):
    from flynn_agents_sdk import InferenceResult, InferenceUsage, UsageStatus

    class WrongKind:
        def plan_output(self, request, available):
            return OutputReservation("scripted", 0)

        async def generate(self, request):
            return InferenceResult(
                ToolCall("read", "{}"),
                InferenceUsage(
                    "model",
                    UsageStatus.KNOWN,
                    True,
                    "fixture",
                    "model",
                    input_tokens=1,
                    output_tokens=2,
                ),
            )

    with create(tmp_path / "run.db") as run:
        with pytest.raises(ContractError, match="breached"):
            asyncio.run(runtime(run, WrongKind()).step("read"))
        assert run.remaining()["tool"] == 9
        assert run.usage_summary()["known_output_tokens"] == 2
        assert run.output_budget().breached == 1


def test_reservation_and_inference_capacity_publish_atomically(tmp_path):
    path = tmp_path / "run.db"
    with SQLiteRun.create(
        path,
        run_id="empty",
        initial_state="base",
        limits=RunLimits(0, 1, 1, output_tokens=7),
    ) as run:
        with pytest.raises(BudgetExhausted, match="inference"):
            run.start(
                "not-admitted",
                InferenceRequest(
                    "read",
                    run.read(),
                    ("read",),
                    max_output_tokens=4,
                ),
                OutputReservation("model", 4),
            )
        assert run.records()["output_reservations"] == []
        assert run.records()["operations"] == []
        assert run.output_budget().available == 7


@pytest.mark.parametrize("value", ["missing", True, -1, 1.5, "7"])
def test_invalid_durable_output_limit_never_becomes_uncapped(tmp_path, value):
    path = tmp_path / "run.db"
    with create(path):
        pass
    with sqlite3.connect(path) as db:
        limits = json.loads(db.execute("SELECT limits FROM run").fetchone()[0])
        if value == "missing":
            limits.pop("output_tokens")
        else:
            limits["output_tokens"] = value
        db.execute("UPDATE run SET limits=?", (json.dumps(limits),))
    with SQLiteRun.open(path) as run:
        with pytest.raises(ContractError, match="limits"):
            asyncio.run(runtime(run, ScriptedAdapter([ToolCall("read", "{}")])).step("refuse"))
        assert run.records()["operations"] == []
        assert run.records()["reservations"] == []
