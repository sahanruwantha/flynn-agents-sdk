"""Direct DeepSeek inference transport. No agent framework, retries, or hidden history."""

import asyncio
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal

import httpx

from flynn_agents_sdk.contracts import (
    BudgetExhausted,
    InferenceCancelled,
    InferenceFailure,
    InferenceRejected,
    InferenceRequest,
    InferenceResult,
    InferenceUsage,
    OutputReservation,
    ToolCall,
    UsageStatus,
)

VISION_MODEL = "deepseek-v4-flash-vision-exp"
DEFAULT_INSTRUCTION = (
    "Choose exactly one permitted tool call for the objective. "
    "Use the latest observation and attached images as evidence. "
    "Accepted state may lag behind observations. Do not declare completion. "
    "Return only ONE tool call total, including internal tools. "
    "If several steps are useful, choose the first and wait for its result."
)


class ProviderError(InferenceFailure):
    """Provider failure with a safe message that excludes credentials and response bodies."""


class ProviderResponseRejected(ProviderError, InferenceRejected):
    """A received response violated the tool-call contract; no call was returned.

    Applications choose whether to request a correction. Transport, HTTP, timeout,
    cancellation and request-configuration errors do not use this type.
    """

    def __init__(
        self, reason: str, *, choice_count: int | None, tool_call_count: int | None
    ) -> None:
        self.reason = reason
        self.choice_count = choice_count
        self.tool_call_count = tool_call_count
        super().__init__(
            "DeepSeek did not return one complete, permitted JSON tool call: " + reason
        )


@dataclass(frozen=True)
class InferenceTrace:
    model: str
    response_id: str | None
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    elapsed_seconds: float
    outcome: str
    call: ToolCall | None = None
    rejection_reason: str | None = None
    choice_count: int | None = None
    tool_call_count: int | None = None
    rejected_arguments: str | None = None
    rejected_calls: tuple[ToolCall, ...] = ()


class DeepSeekAdapter:
    """Make one bounded async Chat Completions request per generate call.

    Install flynn-agents-sdk[deepseek]. The application supplies the credential;
    this provider neither reads .env nor executes tools. The endpoint is fixed to
    DeepSeek so a configuration typo cannot redirect the bearer token elsewhere.
    An optional HTTP transport supports offline conformance tests.
    Opt-in capture_rejected_arguments retains the exact rejected model string in
    traces, never headers or HTTP error bodies. Treat this as untrusted, potentially
    sensitive output; applications choose retention and access policies.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = VISION_MODEL,
        max_tokens: int = 512,
        timeout_seconds: float = 45,
        on_trace: Callable[[InferenceTrace], None] | None = None,
        capture_rejected_arguments: bool = False,
        reasoning_effort: Literal["low", "high", "max"] | None = None,
        system_instruction: str = DEFAULT_INSTRUCTION,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip() or "\n" in api_key or "\r" in api_key:
            raise ValueError("A nonempty DeepSeek API key is required")
        if not model.strip():
            raise ValueError("A model ID is required")
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if reasoning_effort not in (None, "low", "high", "max"):
            raise ValueError("reasoning_effort must be low, high, max, or None (disabled)")
        if not isinstance(system_instruction, str) or not system_instruction.strip():
            raise ValueError("system_instruction must be nonempty text")
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self._on_trace = on_trace
        self._capture_rejected_arguments = capture_rejected_arguments
        self.reasoning_effort = reasoning_effort
        self.system_instruction = system_instruction
        self._client = httpx.AsyncClient(
            base_url="https://api.deepseek.com",
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> "DeepSeekAdapter":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _trace(self, trace: InferenceTrace, usage: InferenceUsage) -> None:
        assert self._on_trace is not None
        try:
            self._on_trace(trace)
        except Exception as error:
            # A diagnostic sink is an application boundary: preserve consumed usage
            # while failing explicitly, retaining the sink exception as the cause.
            raise InferenceFailure("Inference diagnostic callback failed", usage=usage) from error

    def plan_output(self, request: InferenceRequest, available: int) -> OutputReservation:
        if available <= 0:
            raise BudgetExhausted("Output-token budget exhausted; no model request authorized")
        return OutputReservation("model", min(available, self._output_limit(request)))

    def _output_limit(self, request: InferenceRequest) -> int:
        limit = request.max_output_tokens
        if limit is None:
            return self.max_tokens
        if type(limit) is not int or limit <= 0:
            raise ProviderError("A model request requires a positive output-token ceiling")
        return min(self.max_tokens, limit)

    def _payload(self, request: InferenceRequest) -> dict[str, Any]:
        if request.images and self.model != VISION_MODEL:
            raise ProviderError("Image input requires the DeepSeek vision model")
        specs = {spec.name: spec for spec in request.tools}
        if not request.allowed_tools or len(specs) != len(request.tools):
            raise ProviderError("Supply unique tool specifications and at least one granted tool")
        functions = []
        for name in dict.fromkeys(request.allowed_tools):
            if name not in specs:
                raise ProviderError("Every granted tool requires a specification")
            spec = specs[name]
            try:
                schema = json.loads(spec.parameters_json)
            except ValueError:
                raise ProviderError("Tool parameters must be a JSON object schema") from None
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise ProviderError("Tool parameters must be a JSON object schema")
            functions.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": spec.description,
                        "parameters": schema,
                    },
                }
            )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "objective": request.objective,
                        "accepted_state": {
                            "revision": request.base.revision,
                            "value": request.base.value,
                        },
                        "observation": request.observation,
                    }
                ),
            }
        ]
        for image in request.images:
            if image.detail not in ("low", "high", "original", "auto") or not image.url.startswith(
                ("https://", "http://", "data:image/")
            ):
                raise ProviderError("Invalid explicit image URL or detail")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image.url,
                        "detail": image.detail,
                    },
                }
            )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": self.system_instruction,
                },
                {"role": "user", "content": content},
            ],
            "tools": functions,
            "tool_choice": "required",
            "stream": False,
            "max_tokens": self._output_limit(request),
            "thinking": {"type": "disabled" if self.reasoning_effort is None else "enabled"},
        }
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        reports: list[InferenceUsage] = []
        try:
            call = await self._generate(request, reports)
        except ProviderError as error:
            error.usage = reports[-1]
            raise
        except asyncio.CancelledError as error:
            raise InferenceCancelled(reports[-1]) from error
        return InferenceResult(call, reports[-1])

    async def _generate(self, request: InferenceRequest, reports: list[InferenceUsage]) -> ToolCall:
        request_started = False
        started = time.monotonic()
        data: dict[str, Any] = {}
        finish: str | None = None
        call: ToolCall | None = None
        rejection: str | None = None
        choice_count: int | None = None
        tool_call_count: int | None = None
        rejected_arguments: str | None = None
        rejected_calls: tuple[ToolCall, ...] = ()
        outcome = "provider_error"
        try:
            payload = self._payload(request)
            async with asyncio.timeout(self.timeout_seconds):
                request_started = True
                response = await self._client.post("/chat/completions", json=payload)
            if response.status_code != 200:
                raise ProviderError(
                    f"DeepSeek HTTP {response.status_code}; request was not retried"
                )
            try:
                body = response.json()
            except ValueError:
                body = None
                rejection = "invalid_json"
            if rejection is None and not isinstance(body, dict):
                rejection = "response_not_object"
            if isinstance(body, dict):
                data = body
            choices = data.get("choices")
            if rejection is None:
                if not isinstance(choices, list):
                    rejection = "choices_not_list"
                else:
                    choice_count = len(choices)
                    if choice_count != 1:
                        rejection = "expected_one_choice"
            choice = choices[0] if rejection is None and isinstance(choices, list) else None
            if rejection is None and not isinstance(choice, dict):
                rejection = "choice_not_object"
            if isinstance(choice, dict):
                finish = choice.get("finish_reason")
                if finish != "tool_calls":
                    rejection = "finish_reason_not_tool_calls"
            message = choice.get("message") if isinstance(choice, dict) else None
            if rejection is None and not isinstance(message, dict):
                rejection = "message_not_object"
            calls = message.get("tool_calls") if isinstance(message, dict) else None
            if isinstance(calls, list):
                tool_call_count = len(calls)
            if rejection is None:
                if not isinstance(calls, list):
                    rejection = "tool_calls_not_list"
                elif len(calls) != 1:
                    rejection = "expected_one_tool_call"
            item = calls[0] if rejection is None and isinstance(calls, list) else None
            if rejection is None and (not isinstance(item, dict) or item.get("type") != "function"):
                rejection = "invalid_tool_type"
            function = item.get("function") if isinstance(item, dict) else None
            if rejection is None and not isinstance(function, dict):
                rejection = "function_not_object"
            name = function.get("name") if isinstance(function, dict) else None
            arguments = function.get("arguments") if isinstance(function, dict) else None
            if rejection is None and (
                not isinstance(name, str) or name not in request.allowed_tools
            ):
                rejection = "tool_not_permitted"
            if rejection is None:
                if not isinstance(arguments, str):
                    rejection = "arguments_not_string"
                else:
                    try:
                        decoded = json.loads(arguments)
                    except ValueError:
                        rejection = "arguments_invalid_json"
                    else:
                        if not isinstance(decoded, dict):
                            rejection = "arguments_not_object"
            if rejection is not None:
                if self._capture_rejected_arguments:
                    if isinstance(arguments, str):
                        rejected_arguments = arguments
                    if isinstance(calls, list):
                        rejected_calls = tuple(
                            ToolCall(fn["name"], fn["arguments"])
                            for raw_call in calls
                            if isinstance(raw_call, dict)
                            and isinstance(fn := raw_call.get("function"), dict)
                            and isinstance(fn.get("name"), str)
                            and isinstance(fn.get("arguments"), str)
                        )
                outcome = "invalid_response"
                raise ProviderResponseRejected(
                    rejection, choice_count=choice_count, tool_call_count=tool_call_count
                )
            assert isinstance(name, str) and isinstance(arguments, str)
            call = ToolCall(name, arguments)
            outcome = "returned"
            return call
        except (httpx.TimeoutException, TimeoutError):
            outcome = "timeout"
            raise ProviderError(
                "DeepSeek request timed out; not retried, usage may be unknown"
            ) from None
        except httpx.RequestError:
            raise ProviderError(
                "DeepSeek transport failed; not retried, usage may be unknown"
            ) from None
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            raw_usage = data.get("usage")
            raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
            prompt = raw_usage.get("prompt_tokens")
            completion = raw_usage.get("completion_tokens")
            prompt = prompt if type(prompt) is int and 0 <= prompt < 2**63 else None
            completion = completion if type(completion) is int and 0 <= completion < 2**63 else None
            if not request_started:
                prompt, completion = 0, 0
            response_id = data.get("id")
            reports.append(
                InferenceUsage(
                    kind="model",
                    status=UsageStatus.KNOWN
                    if prompt is not None and completion is not None
                    else UsageStatus.UNKNOWN,
                    request_started=request_started,
                    provider="deepseek",
                    model=self.model,
                    response_id=response_id
                    if isinstance(response_id, str) and response_id.strip()
                    else None,
                    finish_reason=finish if isinstance(finish, str) and finish.strip() else None,
                    input_tokens=prompt,
                    output_tokens=completion,
                )
            )
            if self._on_trace is not None:
                usage = data.get("usage")
                usage = usage if isinstance(usage, dict) else {}
                prompt = usage.get("prompt_tokens")
                completion = usage.get("completion_tokens")
                response_id = data.get("id")
                self._trace(
                    InferenceTrace(
                        self.model,
                        response_id if isinstance(response_id, str) else None,
                        finish if isinstance(finish, str) else None,
                        prompt if type(prompt) is int and prompt >= 0 else None,
                        completion if type(completion) is int and completion >= 0 else None,
                        time.monotonic() - started,
                        outcome,
                        call,
                        rejection,
                        choice_count,
                        tool_call_count,
                        rejected_arguments,
                        rejected_calls,
                    ),
                    reports[-1],
                )
