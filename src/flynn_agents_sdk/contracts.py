"""Immutable contracts for the experimental single-step runtime.

Payloads are strings so records cannot retain caller-owned mutable objects.
Applications define payload formats and validate tool arguments.
"""

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


class StateStore(Protocol):
    def read(self) -> State: ...

    def commit(self, candidate: Candidate, evaluation: Evaluation) -> State:
        """Atomically check the base and evaluation before publication."""
        ...


def check_evaluation(candidate: Candidate, evaluation: Evaluation) -> None:
    """Check full input binding, including rejected and unavailable evaluations."""
    if not isinstance(evaluation, Evaluation) or evaluation.candidate != candidate:
        raise ContractError("Evaluation does not bind the exact candidate")
    if not isinstance(evaluation.verdict, Verdict):
        raise ContractError("Evaluation verdict must be a Verdict member")
    for field in (evaluation.evaluator, evaluation.scope, evaluation.reason):
        if not isinstance(field, str) or not field.strip():
            raise ContractError("Evaluation requires nonempty evaluator, scope, and reason")


class UnresolvedEffect(ContractError):
    """A prior dispatch has no recorded result; external reconciliation is required."""


class Journal(Protocol):
    """One episode's evidence, independent of accepted application state."""

    def latest_observation(self) -> str | None: ...

    def unresolved(self) -> tuple[str, ...]: ...

    def begin(
        self, step_id: str, base: State, call: ToolCall, *, observation: bool = False
    ) -> None:
        """Durably claim dispatch, refusing any outstanding unresolved dispatch."""
        ...

    def returned(self, step_id: str, output: str) -> None: ...

    def evaluated(self, step_id: str, evaluation: Evaluation) -> None: ...
