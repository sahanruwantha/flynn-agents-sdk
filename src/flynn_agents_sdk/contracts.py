"""Immutable contracts for the experimental single-step runtime.

Payloads are strings so records cannot retain caller-owned mutable objects.
Applications define payload formats and validate tool arguments.
"""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ContractError(ValueError):
    """An operation violates an execution or publication contract."""


class ProposalRejected(ContractError):
    """Tool arguments rejected by validation before any tool dispatch."""


class BudgetExhausted(ContractError):
    """No operation capacity remains; no dispatch is authorized."""


class Verdict(StrEnum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class State:
    revision: int
    value: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: str


class UsageStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class InferenceUsage:
    """Neutral accounting, excluding prices and raw provider payloads.

    Unknown usage may retain either known token count. request_started means dispatch
    was attempted, not that the remote provider received or billed the request.
    model is requested identity; response_model is provider-reported identity, or
    None when absent. Neither proves a provider actually served those weights.
    """

    kind: str
    status: UsageStatus
    request_started: bool = False
    provider: str | None = None
    model: str | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_model: str | None = None
    configuration_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("model", "scripted") or not isinstance(self.status, UsageStatus):
            raise ContractError("Usage requires model/scripted kind and a UsageStatus")
        if type(self.request_started) is not bool:
            raise ContractError("request_started must be a boolean")
        for value in (
            self.provider, self.model, self.response_id, self.finish_reason, self.response_model
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ContractError("Usage identity fields must be nonempty strings or None")
        if self.configuration_sha256 is not None and (
            not isinstance(self.configuration_sha256, str)
            or len(self.configuration_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.configuration_sha256)
        ):
            raise ContractError("Inference configuration digest must be lowercase SHA-256 or None")
        for count in (self.input_tokens, self.output_tokens):
            if count is not None and (type(count) is not int or not 0 <= count < 2**63):
                raise ContractError("Token counts must be nonnegative SQLite integers or None")
        if self.kind == "scripted":
            if (
                self.status != UsageStatus.NOT_APPLICABLE
                or self.request_started
                or any(
                    value is not None
                    for value in (
                        self.provider,
                        self.model,
                        self.response_id,
                        self.finish_reason,
                        self.response_model,
                        self.configuration_sha256,
                        self.input_tokens,
                        self.output_tokens,
                    )
                )
            ):
                raise ContractError("Scripted usage must be not_applicable with no model metadata")
        else:
            if self.provider is None or self.model is None:
                raise ContractError("Model usage requires provider and model identity")
            complete = self.input_tokens is not None and self.output_tokens is not None
            if self.status == UsageStatus.NOT_APPLICABLE or (
                (self.status == UsageStatus.KNOWN) != complete
            ):
                raise ContractError("Model usage is known exactly when both token counts are known")
            if not self.request_started and (self.input_tokens, self.output_tokens) != (0, 0):
                raise ContractError("An undispatched model request must report known zero tokens")

    @classmethod
    def scripted(cls) -> "InferenceUsage":
        return cls("scripted", UsageStatus.NOT_APPLICABLE)


@dataclass(frozen=True)
class InferenceResult:
    call: ToolCall
    usage: InferenceUsage

    @classmethod
    def scripted(cls, call: ToolCall) -> "InferenceResult":
        return cls(call, InferenceUsage.scripted())


class InferenceFailure(ContractError):
    """A failed invocation may still carry accounting for a consumed response."""

    def __init__(self, message: str, *, usage: InferenceUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class InferenceRejected(InferenceFailure):
    """A received response violated the proposal contract before tool dispatch."""


class InferenceCancelled(asyncio.CancelledError):
    """Preserve cooperative cancellation while transporting available usage."""

    def __init__(self, usage: InferenceUsage) -> None:
        super().__init__("Inference cancelled")
        self.usage = usage


@dataclass(frozen=True)
class ToolSpec:
    """Provider-facing description; application validators still authorize arguments."""

    name: str
    description: str
    parameters_json: str


@dataclass(frozen=True)
class ImageInput:
    """An explicit image URL or inline data URL, never an implicit filesystem read."""

    url: str
    detail: str = "original"


@dataclass(frozen=True)
class OutputReservation:
    """Adapter's no-I/O plan for one request's enforceable output ceiling."""

    kind: str
    tokens: int

    def __post_init__(self) -> None:
        if type(self.tokens) is not int or not 0 <= self.tokens < 2**63:
            raise ContractError("Output reservation must be a nonnegative SQLite integer")
        if self.kind not in ("model", "scripted") or (
            (self.kind == "scripted") != (self.tokens == 0)
        ):
            raise ContractError(
                "Scripted output reserves zero; model output reserves positive tokens"
            )


@dataclass(frozen=True)
class OutputBudget:
    limit: int | None
    available: int | None
    spent: int = 0
    held: int = 0
    unresolved: int = 0
    breached: int = 0


@dataclass(frozen=True)
class InferenceRequest:
    objective: str
    base: State
    allowed_tools: tuple[str, ...]
    observation: str | None = None
    tools: tuple[ToolSpec, ...] = ()
    images: tuple[ImageInput, ...] = ()
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class Candidate:
    id: str
    base: State
    call: ToolCall
    output: str


@dataclass(frozen=True)
class Evaluation:
    candidate: Candidate
    evaluator: str
    scope: str
    verdict: Verdict
    reason: str
    state_update: str | None = None


@dataclass(frozen=True)
class StepResult:
    candidate: Candidate
    evaluation: Evaluation
    state: State
    committed: bool


@dataclass(frozen=True)
class Event:
    step_id: str
    stage: str
    detail: str


class InferenceAdapter(Protocol):
    async def generate(self, request: InferenceRequest) -> InferenceResult:
        """Return one proposal without executing tools or retrying internally."""
        ...


@runtime_checkable
class OutputBoundedInference(Protocol):
    def plan_output(self, request: InferenceRequest, available: int) -> OutputReservation:
        """No I/O: propose a bound; generate must honor request.max_output_tokens."""
        ...


class Evaluator(Protocol):
    async def evaluate(self, candidate: Candidate) -> Evaluation:
        """Evaluate frozen input using application-owned checks."""
        ...


def check_evaluation(candidate: Candidate, evaluation: Evaluation) -> None:
    """Check full input binding, including rejected and unavailable evaluations."""
    if not isinstance(evaluation, Evaluation) or evaluation.candidate != candidate:
        raise ContractError("Evaluation does not bind the exact candidate")
    if not isinstance(evaluation.verdict, Verdict):
        raise ContractError("Evaluation verdict must be a Verdict member")
    if evaluation.state_update is not None and not isinstance(evaluation.state_update, str):
        raise ContractError("State update must be a string or None for observation-only work")
    for field in (evaluation.evaluator, evaluation.scope, evaluation.reason):
        if not isinstance(field, str) or not field.strip():
            raise ContractError("Evaluation requires nonempty evaluator, scope, and reason")


class UnresolvedEffect(ContractError):
    """A prior dispatch has no recorded result; external reconciliation is required."""


@dataclass(frozen=True)
class RunLimits:
    inference_calls: int
    tool_calls: int
    external_actions: int
    wall_time_seconds: float | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (self.inference_calls, self.tool_calls, self.external_actions):
            if type(value) is not int or not 0 <= value < 2**63:
                raise ValueError("Operation limits must be nonnegative SQLite integers")
        if self.output_tokens is not None and (
            type(self.output_tokens) is not int or not 0 <= self.output_tokens < 2**63
        ):
            raise ValueError("Output-token limit must be a nonnegative SQLite integer or None")
        if self.wall_time_seconds is not None and (
            not math.isfinite(self.wall_time_seconds) or self.wall_time_seconds <= 0
        ):
            raise ValueError("Wall time must be finite and positive")


@dataclass(frozen=True)
class PendingOperation:
    id: str
    stage: str
    candidate: Candidate | None


class DispatchDenied(ContractError):
    """An application guard refused a validated call before tool dispatch."""


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str

    def __post_init__(self) -> None:
        if (
            type(self.allowed) is not bool
            or not isinstance(self.reason, str)
            or not self.reason.strip()
        ):
            raise ContractError("Guard decisions require a boolean and nonempty reason")


@dataclass(frozen=True)
class GuardContext:
    operation_id: str
    request: InferenceRequest
    call: ToolCall


@dataclass(frozen=True)
class DispatchGuard:
    id: str
    check: Callable[[GuardContext], Awaitable[GuardDecision]]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip() or not callable(self.check):
            raise ContractError("Dispatch guard requires a nonempty identity and callable check")


class RunStore(Protocol):
    """One exclusively owned durable run; implementations own atomic publication."""

    def read(self) -> State: ...
    def outcome(self) -> str | None: ...
    def latest_observation(self) -> str | None: ...
    def pending(self) -> PendingOperation | None: ...
    @property
    def seconds_remaining(self) -> float | None: ...
    def check_ready(self) -> None: ...
    def finish(self, outcome: str) -> None: ...
    def completed_operations(self) -> int: ...
    def output_budget(self) -> OutputBudget: ...
    def start(
        self,
        operation_id: str,
        request: InferenceRequest,
        output: OutputReservation | None = None,
        *,
        guards: tuple[str, ...] = (),
    ) -> None: ...
    def record_guard(self, operation_id: str, guard_id: str, decision: GuardDecision) -> None: ...
    def record_event(self, event: Event) -> None: ...
    def record_usage(self, operation_id: str, usage: InferenceUsage) -> None: ...
    def proposed(self, operation_id: str, call: ToolCall) -> None: ...
    def dispatch(self, operation_id: str, *, observation: bool, external_action: bool) -> None: ...
    def returned(self, operation_id: str, output: str) -> Candidate: ...
    def complete(self, evaluation: Evaluation) -> StepResult: ...
    def failed(self, operation_id: str, error: str) -> None: ...
    def abandon_undispatched(self, operation_id: str) -> None: ...
