"""Immutable contracts for the experimental single-step runtime.

Payloads are strings so records cannot retain caller-owned mutable objects.
Applications define payload formats and validate tool arguments.
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


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
class InferenceRequest:
    objective: str
    base: State
    allowed_tools: tuple[str, ...]
    observation: str | None = None
    tools: tuple[ToolSpec, ...] = ()
    images: tuple[ImageInput, ...] = ()


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
    async def generate(self, request: InferenceRequest) -> ToolCall:
        """Return one proposal without executing tools or retrying internally."""
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

    def __post_init__(self) -> None:
        for value in (self.inference_calls, self.tool_calls, self.external_actions):
            if type(value) is not int or not 0 <= value < 2**63:
                raise ValueError("Operation limits must be nonnegative SQLite integers")
        if self.wall_time_seconds is not None and (
            not math.isfinite(self.wall_time_seconds) or self.wall_time_seconds <= 0
        ):
            raise ValueError("Wall time must be finite and positive")


@dataclass(frozen=True)
class PendingOperation:
    id: str
    stage: str
    candidate: Candidate | None


class RunStore(Protocol):
    """One exclusively owned durable run; implementations own atomic publication."""

    def read(self) -> State: ...
    def outcome(self) -> str | None: ...
    def latest_observation(self) -> str | None: ...
    def pending(self) -> PendingOperation | None: ...
    @property
    def seconds_remaining(self) -> float | None: ...
    def check_ready(self) -> None: ...
    def start(self, operation_id: str, request: InferenceRequest) -> None: ...
    def proposed(self, operation_id: str, call: ToolCall) -> None: ...
    def dispatch(self, operation_id: str, *, observation: bool, external_action: bool) -> None: ...
    def returned(self, operation_id: str, output: str) -> Candidate: ...
    def complete(self, evaluation: Evaluation) -> StepResult: ...
    def failed(self, operation_id: str, error: str) -> None: ...
    def abandon_undispatched(self, operation_id: str) -> None: ...
