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
    assert call.call.name == "move"
    assert call.usage.input_tokens == 100
    assert call.usage.output_tokens == 20
    assert len(sent) == 1
    assert sent[0]["messages"][1]["content"][1]["type"] == "image_url"
    assert sent[0]["tools"][0]["function"]["name"] == "move"
    assert sent[0]["max_tokens"] == 512
    assert sent[0]["thinking"] == {"type": "disabled"}
    assert sent[0]["tool_choice"] == "required"
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


@pytest.mark.parametrize("capture", [False, True])
def test_multiple_rejected_calls_preserve_each_model_argument(capture):
    body = response(arguments='{"first":1}')
    body["choices"][0]["message"]["tool_calls"].append(
        {"type": "function", "function": {"name": "move", "arguments": "malformed"}}
    )
    traces = []

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test-secret",
            capture_rejected_arguments=capture,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
            on_trace=traces.append,
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderResponseRejected):
        asyncio.run(scenario())
    assert traces[0].rejection_reason == "expected_one_tool_call"
    assert [call.arguments for call in traces[0].rejected_calls] == (
        ['{"first":1}', "malformed"] if capture else []
    )
    assert traces[0].call is None


@pytest.mark.parametrize("effort", ["low", "high", "max"])
def test_reasoning_is_explicit_bounded_and_independent(effort):
    sent, traces = [], []

    def handler(req):
        sent.append(json.loads(req.content))
        body = response()
        body["choices"][0]["message"]["reasoning_content"] = "private model deliberation"
        body["usage"] = {
            "prompt_tokens": 100,
            "completion_tokens": 4096,
            "completion_tokens_details": {"reasoning_tokens": 4000},
        }
        return httpx.Response(200, json=body)

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test",
            reasoning_effort=effort,
            max_tokens=4096,
            system_instruction="Infer a program; submit one tool call.",
            transport=httpx.MockTransport(handler),
            on_trace=traces.append,
        ) as adapter:
            first = await adapter.generate(request())
            await adapter.generate(request())
            return first

    result = asyncio.run(scenario())
    assert sent[0] == sent[1]  # No hidden provider conversation or reasoning replay.
    assert sent[0]["thinking"] == {"type": "enabled"}
    assert sent[0]["reasoning_effort"] == effort
    assert "tool_choice" not in sent[0]
    assert sent[0]["max_tokens"] == 4096
    assert sent[0]["messages"][0]["content"] == "Infer a program; submit one tool call."
    assert result.usage.output_tokens == 4096  # Includes reasoning, not just visible text.
    assert "private model deliberation" not in repr(traces)


@pytest.mark.parametrize(
    "options",
    [
        {"reasoning_effort": "medium"},
        {"reasoning_effort": True},
        {"system_instruction": " "},
        {"system_instruction": None},
    ],
)
def test_invalid_reasoning_and_instruction_fail_before_client(options):
    with pytest.raises(ValueError):
        DeepSeekAdapter(api_key="test", **options)


def test_thinking_without_forced_tool_still_rejects_plain_answer():
    sent, traces = [], []

    def handler(req):
        sent.append(json.loads(req.content))
        body = response(finish="stop")
        body["choices"][0]["message"] = {
            "content": "No tool needed",
            "reasoning_content": "private",
        }
        return httpx.Response(200, json=body)

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test",
            reasoning_effort="high",
            transport=httpx.MockTransport(handler),
            on_trace=traces.append,
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderResponseRejected) as error:
        asyncio.run(scenario())
    assert len(sent) == 1 and "tool_choice" not in sent[0]
    assert error.value.usage.output_tokens == 20
    assert traces[0].call is None


@pytest.mark.parametrize("encoding", ["literal", "unicode", "url", "base64", "mixed"])
def test_http_error_capture_redacts_credentials_and_keeps_reason(encoding):
    import base64
    from urllib.parse import quote

    secret = "sk-Test-123"
    variants = {
        "literal": secret,
        "unicode": "".join(f"\\u{ord(c):04x}" for c in secret),
        "url": "".join(f"%{ord(c):02x}" for c in secret),
        "base64": base64.b64encode(secret.encode()).decode(),
        "mixed": "".join(c if i % 2 else f"\\u{ord(c):04x}" for i, c in enumerate(secret)),
    }
    echo = variants[encoding]
    body = (
        '{"error":{"message":"thinking rejects tool_choice; echoed '
        + echo
        + '","param":"tool_choice","type":"invalid_request_error"},'
        + '"api_key":"other-credential","Authorization":"Bearer other-bearer"}'
    )
    traces, sent = [], []

    def handler(req):
        sent.append(req)
        return httpx.Response(400, content=body.encode())

    async def scenario():
        async with DeepSeekAdapter(
            api_key=secret,
            capture_error_body=True,
            on_trace=traces.append,
            transport=httpx.MockTransport(handler),
        ) as adapter:
            await adapter.generate(request())

    with pytest.raises(ProviderError) as error:
        asyncio.run(scenario())
    assert len(sent) == 1
    trace = traces[0]
    assert trace.http_status == 400
    assert trace.error_body.redacted and not trace.error_body.truncated
    assert trace.error_body.original_bytes == len(body.encode())
    retained = json.loads(trace.error_body.text)
    assert retained["error"]["param"] == "tool_choice"
    assert "thinking rejects tool_choice" in retained["error"]["message"]
    for value in (secret, echo, quote(secret), "other-credential", "other-bearer"):
        assert value not in repr(trace) + str(error.value)
    assert error.value.usage.output_tokens is None
    assert trace.completion_tokens is None  # A 400 is not proof of zero spend.


def test_non_json_error_and_redaction_before_truncation():
    from flynn_agents_sdk.deepseek import _error_body

    secret = "sk-sensitive-credential"
    prefix = "x" * (65536 - len(secret) // 2)
    body = (prefix + secret + "y" * 100).encode()
    captured = _error_body(body, secret)
    assert captured.truncated and captured.redacted
    assert len(captured.text) == 65536 and secret[: len(secret) // 2] not in captured.text
    error = _error_body(b"<html>bad request</html>\nAuthorization: Bearer token-value", secret)
    assert "bad request" in error.text and "token-value" not in error.text


def test_error_body_capture_is_off_by_default():
    traces = []

    async def scenario():
        async with DeepSeekAdapter(
            api_key="test-key",
            on_trace=traces.append,
            transport=httpx.MockTransport(lambda _: httpx.Response(500, text="diagnostic")),
        ) as a:
            await a.generate(request())

    with pytest.raises(ProviderError):
        asyncio.run(scenario())
    assert traces[0].http_status == 500 and traces[0].error_body is None


@pytest.mark.parametrize("reported", ["resolved-model-version", None, "", "   ", 42, {}])
@pytest.mark.parametrize("rejected", [False, True])
def test_response_model_identity_survives_without_request_fallback(reported, rejected):
    payload = response(arguments="bad" if rejected else "{}")
    if reported is None:
        payload.pop("model")
    else:
        payload["model"] = reported

    async def scenario():
        async with DeepSeekAdapter(
            api_key="offline",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        ) as adapter:
            if rejected:
                with pytest.raises(ProviderResponseRejected) as error:
                    await adapter.generate(request())
                return error.value.usage
            return (await adapter.generate(request())).usage

    usage = asyncio.run(scenario())
    assert usage.model == "deepseek-v4-flash-vision-exp"
    expected = reported if isinstance(reported, str) and reported.strip() else None
    assert usage.response_model == expected
    assert usage.output_tokens == 20
