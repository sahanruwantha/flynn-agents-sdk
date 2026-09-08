import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from flynn_agents_sdk import (
    ContractError,
    InferenceConfiguration,
    InferenceRequest,
    InferenceUsage,
    State,
    ToolSpec,
)
from flynn_agents_sdk.deepseek import DeepSeekAdapter, ProviderResponseRejected


def request():
    return InferenceRequest(
        "read",
        State(0, "facts"),
        ("read",),
        "observation",
        (ToolSpec("read", "Read", '{"type":"object"}'),),
        max_output_tokens=100,
    )


@pytest.mark.parametrize("rejected", [False, True])
def test_configuration_is_captured_from_dispatched_payload_despite_later_mutation(rejected):
    sent = []

    async def scenario():
        def handler(req):
            sent.append(json.loads(req.content))
            adapter.system_instruction = "changed after dispatch"
            adapter.model = "changed-after-dispatch"
            return httpx.Response(
                200,
                json={
                    "model": "served-version",
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "tool_calls": [
                                    {
                                        "type": "function",
                                        "function": {
                                            "name": "read",
                                            "arguments": "bad" if rejected else "{}",
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                },
            )

        async with DeepSeekAdapter(
            api_key="private-test-key",
            system_instruction="judge only form",
            transport=httpx.MockTransport(handler),
        ) as adapter:
            configured = adapter.configuration(request())
            assert sent == []
            if rejected:
                with pytest.raises(ProviderResponseRejected) as error:
                    await adapter.generate(request())
                usage = error.value.usage
            else:
                usage = (await adapter.generate(request())).usage
            assert usage.configuration_sha256 == configured.sha256
            assert usage.model == configured.model
            assert adapter.configuration(request()).sha256 != configured.sha256
            return configured

    configured = asyncio.run(scenario())
    settings = json.loads(configured.settings_json)
    assert settings["system_instruction"] == sent[0]["messages"][0]["content"]
    assert settings["max_tokens"] == sent[0]["max_tokens"] == 100
    assert "private-test-key" not in configured.settings_json
    assert "facts" not in configured.settings_json


def test_configuration_distinguishes_settings_but_not_changing_evidence():
    async def scenario():
        async with DeepSeekAdapter(api_key="offline") as adapter:
            base = adapter.configuration(request())
            assert (
                adapter.configuration(replace(request(), observation="different pixels")).sha256
                == base.sha256
            )
            assert (
                adapter.configuration(replace(request(), max_output_tokens=80)).sha256
                != base.sha256
            )
            adapter.reasoning_effort = "high"
            reasoning = adapter.configuration(request())
            assert reasoning.sha256 != base.sha256
            assert "tool_choice" not in json.loads(reasoning.settings_json)
            adapter.system_instruction = "different instructions"
            assert adapter.configuration(request()).sha256 != reasoning.sha256

    asyncio.run(scenario())


def test_configuration_canonicalizes_settings():
    a = InferenceConfiguration("provider", "model", "protocol/v1", '{"b":2,"a":1}')
    b = InferenceConfiguration("provider", "model", "protocol/v1", '{"a": 1, "b": 2}')
    assert a.sha256 == b.sha256


@pytest.mark.parametrize("value", ["null", "[]", "bad", '{"n":NaN}', '{"n":Infinity}'])
def test_configuration_rejects_invalid_settings(value):
    with pytest.raises(ContractError):
        InferenceConfiguration("provider", "model", "protocol/v1", value)


def test_scripted_usage_cannot_claim_configuration():
    with pytest.raises(ContractError, match="Scripted"):
        replace(InferenceUsage.scripted(), configuration_sha256="a" * 64)
