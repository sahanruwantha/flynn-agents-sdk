import asyncio
import json

import httpx
import pytest

from flynn_agents_sdk import ImageInput, InferenceRequest, State, ToolSpec
from flynn_agents_sdk.deepseek import DeepSeekAdapter, ProviderError, ProviderResponseRejected


def request():
    return InferenceRequest(
        "test",
        State(0, "base"),
        ("move",),
        "frame",
        (ToolSpec("move", "Move", '{"type":"object"}'),),
        (ImageInput("data:image/png;base64,aGVsbG8="),),
    )


def response(*, finish="tool_calls", arguments='{"direction":"up"}', name="move"):
    return {
        "id": "request-1",
        "model": "deepseek-v4-flash-vision-exp",
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "tool_calls": [
                        {"type": "function", "function": {"name": name, "arguments": arguments}}
                    ]
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def test_explicit_vision_tool_payload_and_usage():
    traces = []
    sent = []

    def handler(req):
        assert str(req.url) == "https://api.deepseek.com/chat/completions"
        assert req.headers["authorization"] == "Bearer test-secret"
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=response())

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler), on_trace=traces.append
        ) as adapter:
            return await adapter.generate(request())

    call = asyncio.run(scenario())
    assert call.name == "move"
    assert len(sent) == 1
    assert sent[0]["messages"][1]["content"][1]["type"] == "image_url"
    assert sent[0]["tools"][0]["function"]["name"] == "move"
    assert sent[0]["max_tokens"] == 512
    assert sent[0]["thinking"] == {"type": "disabled"}
    assert traces[0].prompt_tokens == 100
    assert traces[0].completion_tokens == 20
    assert "test-secret" not in repr(traces)


@pytest.mark.parametrize(
    "body",
    [
        response(finish="length"),
        response(arguments="not-json"),
        response(arguments="[]"),
        response(name="ungranted"),
        {"choices": []},
        {"choices": [None]},
        ["not an object"],
    ],
)
def test_invalid_output_is_refused(body):
    async def scenario():
        async with DeepSeekAdapter(
            api_key="test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderError, match="complete, permitted"):
        asyncio.run(scenario())


@pytest.mark.parametrize("status", [401, 429, 500, 302])
def test_errors_never_retry_or_expose_response_body(status):
    sent = []
    traces = []

    def handler(req):
        sent.append(req)
        return httpx.Response(
            status, text="test-secret", headers={"location": "https://other.test"}
        )

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler), on_trace=traces.append
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderError) as error:
        asyncio.run(scenario())
    assert not isinstance(error.value, ProviderResponseRejected)
    assert "test-secret" not in str(error.value)
    assert len(sent) == 1
    assert traces[0].prompt_tokens is None


def test_total_timeout_records_unknown_usage():
    async def handler(req):
        await asyncio.Event().wait()

    traces = []

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test",
            transport=httpx.MockTransport(handler),
            timeout_seconds=0.02,
            on_trace=traces.append,
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderError, match="timed out"):
        asyncio.run(scenario())
    assert traces[0].outcome == "timeout"
    assert traces[0].prompt_tokens is None


def test_text_model_refuses_image_without_network():
    async def scenario():
        async with DeepSeekAdapter(
            api_key="test",
            model="deepseek-v4-flash",
            transport=httpx.MockTransport(lambda _: pytest.fail("sent")),
        ) as a:
            await a.generate(request())

    with pytest.raises(ProviderError, match="vision model"):
        asyncio.run(scenario())


@pytest.mark.parametrize(
    ("body", "reason", "choices", "calls"),
    [
        ({"choices": []}, "expected_one_choice", 0, None),
        ({"choices": [None]}, "choice_not_object", 1, None),
        (response(finish="length"), "finish_reason_not_tool_calls", 1, 1),
        (response(arguments="secret-invalid-json"), "arguments_invalid_json", 1, 1),
        (response(arguments="[]"), "arguments_not_object", 1, 1),
        (response(arguments={}), "arguments_not_string", 1, 1),
        (response(name="secret-ungranted"), "tool_not_permitted", 1, 1),
        (["secret-body"], "response_not_object", None, None),
        ({"choices": {}}, "choices_not_list", None, None),
        ({"choices": [{"finish_reason": "tool_calls"}]}, "message_not_object", 1, None),
    ],
)
def test_rejection_diagnostics_are_structural(body, reason, choices, calls):
    traces, sent = [], []

    def handler(req):
        sent.append(req)
        return httpx.Response(200, json=body)

    async def scenario():
        async with DeepSeekAdapter(
            api_key="secret-key", transport=httpx.MockTransport(handler), on_trace=traces.append
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderResponseRejected, match=reason) as exc:
        asyncio.run(scenario())
    trace = traces[0]
    assert exc.value.reason == reason
    assert exc.value.choice_count == choices
    assert exc.value.tool_call_count == calls
    assert trace.rejection_reason == reason
    assert trace.choice_count == choices
    assert trace.tool_call_count == calls
    assert trace.call is None
    assert "secret" not in str(exc.value) + repr(trace)
    assert len(sent) == 1


def test_multiple_calls_are_not_partially_accepted():
    body = response()
    body["choices"][0]["message"]["tool_calls"] *= 2
    traces = []

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
            on_trace=traces.append,
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderError, match="expected_one_tool_call"):
        asyncio.run(scenario())
    assert traces[0].tool_call_count == 2
    assert traces[0].call is None
    assert traces[0].prompt_tokens == 100
    assert traces[0].completion_tokens == 20


def test_non_json_response_is_diagnosed_without_body():
    traces = []

    async def scenario():
        async with DeepSeekAdapter(
            api_key="secret-key",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="secret-body")),
            on_trace=traces.append,
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderError, match="invalid_json") as exc:
        asyncio.run(scenario())
    assert traces[0].rejection_reason == "invalid_json"
    assert "secret" not in str(exc.value) + repr(traces)


@pytest.mark.parametrize("capture", [False, True])
def test_rejected_arguments_capture_is_exact_and_opt_in(capture):
    raw = '{"note":"unescaped\nnewline"}'
    traces = []

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test-secret",
            capture_rejected_arguments=capture,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=response(arguments=raw))
            ),
            on_trace=traces.append,
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderResponseRejected):
        asyncio.run(scenario())
    assert traces[0].rejection_reason == "arguments_invalid_json"
    assert traces[0].rejected_arguments == (raw if capture else None)
    assert traces[0].call is None
    assert "test-secret" not in repr(traces)
