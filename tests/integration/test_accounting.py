"""Accounting survives refused calls, cancellation, reopening and historical inspection."""

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from flynn_agents_sdk import (
    ContractError,
    Evaluation,
    InferenceRequest,
    InferenceResult,
    InferenceUsage,
    RunLimits,
    Runtime,
    ScriptedAdapter,
    SQLiteRun,
    Tool,
    ToolBroker,
    ToolCall,
    UsageStatus,
    Verdict,
    summarize_usage,
)
from flynn_agents_sdk.deepseek import DeepSeekAdapter, ProviderError


class Accept:
    async def evaluate(self, candidate):
        return Evaluation(candidate, "fixture/v1", "observation", Verdict.SATISFIED, "checked")


def runtime(run, adapter, *, validate=lambda _: None):
    async def execute(arguments):
        return arguments

    return Runtime(
        run=run,
        inference=adapter,
        evaluator=Accept(),
        grants=("read",),
        tools=ToolBroker([Tool("read", validate, execute, observation=True)]),
    )


def create(path):
    return SQLiteRun.create(path, run_id="usage", initial_state="base", limits=RunLimits(8, 8, 8))


def body(*, valid=True, usage=None):
    return {
        "id": "response-1",
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
        "usage": usage if usage is not None else {"prompt_tokens": 17, "completion_tokens": 5},
    }


@pytest.mark.parametrize("mode", ["returned", "rejected", "http", "timeout", "cancelled"])
def test_model_accounting_persists_before_any_dispatch(tmp_path, mode):
    path = tmp_path / "run.db"

    async def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("private transport detail")
        if mode == "cancelled":
            raise asyncio.CancelledError
        return httpx.Response(503 if mode == "http" else 200, json=body(valid=mode != "rejected"))

    async def scenario():
        async with DeepSeekAdapter(
            api_key="secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            with create(path) as run:
                task = runtime(run, adapter)
                if mode == "returned":
                    await task.step("read")
                else:
                    with pytest.raises(
                        asyncio.CancelledError if mode == "cancelled" else ProviderError
                    ):
                        await task.step("read")
                    assert run.remaining()["tool"] == 8

    asyncio.run(scenario())
    with SQLiteRun.open(path) as run:
        usage = run.usage_summary()
        assert usage["model_requests"] == 1
        assert usage["unreported_invocations"] == 0
        known = mode in ("returned", "rejected")
        assert usage["usage_complete"] is known
        assert usage["known_input_tokens"] == (17 if known else 0)
        assert usage["known_output_tokens"] == (5 if known else 0)
        report = json.loads(run.records()["inference_usage"][0]["payload"])
        assert report["status"] == ("known" if known else "unknown")
        assert "secret" not in json.dumps(run.records())


def test_scripted_and_unreported_are_distinct_and_history_is_immutable(tmp_path):
    path = tmp_path / "run.db"
    with create(path) as run:
        asyncio.run(runtime(run, ScriptedAdapter([ToolCall("read", "{}")])).step("read"))
        run.start("died", InferenceRequest("read", run.read(), ("read",)))
        summary = run.usage_summary()
        assert summary["scripted_invocations"] == 1
        assert summary["unknown_usage_invocations"] == 0
        assert summary["unreported_invocations"] == 1
        assert summary["model_requests"] == 0
        assert summary["usage_complete"] is False
    with sqlite3.connect(path) as db:
        for sql in ("DELETE FROM inference_usage", "UPDATE inference_usage SET payload='{}'"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(sql)
    assert summarize_usage(SQLiteRun.inspect(path)) == summary


def test_validator_rejection_still_retains_usage(tmp_path):
    class Model:
        async def generate(self, request):
            return InferenceResult(
                ToolCall("read", "bad"),
                InferenceUsage(
                    "model",
                    UsageStatus.KNOWN,
                    True,
                    "fixture",
                    "model",
                    input_tokens=11,
                    output_tokens=3,
                ),
            )

    def reject(arguments):
        raise ValueError("invalid application arguments")

    with create(tmp_path / "run.db") as run:
        with pytest.raises(ContractError):
            asyncio.run(runtime(run, Model(), validate=reject).step("read"))
        assert run.usage_summary()["known_input_tokens"] == 11
        assert run.remaining()["tool"] == 8


def test_previous_schema_golden_reads_without_mutation_but_cannot_execute(tmp_path):
    path = tmp_path / "historical.db"
    fixture = Path(__file__).parents[1] / "fixtures" / "schema_v2.sql"
    with sqlite3.connect(path) as db:
        db.executescript(fixture.read_text())
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    records = SQLiteRun.inspect(path)
    assert records["commits"][0]["value"] == "updated"
    assert records["operations"][0]["output"] == "observation"
    assert summarize_usage(records)["unreported_invocations"] == 2
    assert summarize_usage(records)["usage_complete"] is False
    with pytest.raises(ContractError, match="schema-5"):
        SQLiteRun.open(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_preflight_failure_is_known_zero_and_partial_usage_is_unknown(tmp_path):
    async def scenario():
        with create(tmp_path / "run.db") as run:
            async with DeepSeekAdapter(
                api_key="secret",
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json=body(usage={"prompt_tokens": 9})),
                ),
            ) as adapter:
                await runtime(run, adapter).step("read")
                adapter.model = "text-only"
                # Missing specs are rejected before any HTTP dispatch.

                request = InferenceRequest("read", run.read(), ("read",))
                with pytest.raises(ProviderError) as caught:
                    await adapter.generate(replace(request, tools=()))
                assert caught.value.usage.status == UsageStatus.KNOWN
                assert caught.value.usage.input_tokens == 0
                assert caught.value.usage.request_started is False
            summary = run.usage_summary()
            assert summary["known_input_tokens"] == 9
            assert summary["unknown_usage_invocations"] == 1
            assert summary["usage_complete"] is False

    asyncio.run(scenario())


def test_diagnostic_sink_failure_does_not_erase_consumed_usage(tmp_path):
    def broken_sink(trace):
        raise OSError("sink unavailable")

    async def scenario():
        with create(tmp_path / "run.db") as run:
            async with DeepSeekAdapter(
                api_key="secret",
                on_trace=broken_sink,
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body())),
            ) as adapter:
                with pytest.raises(ContractError, match="diagnostic callback failed"):
                    await runtime(run, adapter).step("read")
            assert run.usage_summary()["known_input_tokens"] == 17
            assert run.usage_summary()["usage_complete"] is True
            assert run.remaining()["tool"] == 8

    asyncio.run(scenario())
