"""Bounded session driving over Runtime; the application supplies every next decision."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from flynn_agents_sdk.contracts import (
    BudgetExhausted,
    ContractError,
    DispatchGuard,
    Evaluator,
    Event,
    InferenceAdapter,
    InferenceRejected,
    InferenceRequest,
    ProposalRejected,
    RunStore,
    State,
    StepResult,
    UnresolvedEffect,
)
from flynn_agents_sdk.results import parse_json
from flynn_agents_sdk.runtime import Runtime
from flynn_agents_sdk.tools import ToolBroker


@dataclass(frozen=True)
class SessionStep:
    objective: str
    grants: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ContractError("Session step requires a nonempty objective")
        if (
            type(self.grants) is not tuple
            or any(not isinstance(grant, str) or not grant for grant in self.grants)
            or len(set(self.grants)) != len(self.grants)
        ):
            raise ContractError("Session grants require a tuple of unique nonempty tool names")


@dataclass(frozen=True)
class SessionStop:
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ContractError("Session stop requires an explicit application reason")


@dataclass(frozen=True)
class SessionView:
    """Current evidence only. The application selects any further context it needs."""

    state: State
    observation: str | None
    last_step: StepResult | None
    completed_steps: int


@dataclass(frozen=True)
class SessionTermination:
    kind: Literal["stopped", "budget_exhausted", "timed_out", "cancelled", "failed"]
    reason: str
    completed_steps: int

    def __post_init__(self) -> None:
        if self.kind not in ("stopped", "budget_exhausted", "timed_out", "cancelled", "failed"):
            raise ContractError("Unsupported session termination kind")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ContractError("Session termination requires a reason")
        if type(self.completed_steps) is not int or self.completed_steps < 0:
            raise ContractError("Completed session steps must be a nonnegative integer")

    def to_json(self) -> str:
        return json.dumps(
            {"schema": "flynn.session-termination/v1", **asdict(self)},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, value: str) -> "SessionTermination":
        record = parse_json(value)
        if (
            not isinstance(record, dict)
            or set(record) != {"schema", "kind", "reason", "completed_steps"}
            or record["schema"] != "flynn.session-termination/v1"
        ):
            raise ContractError("Session termination requires the exact v1 record")
        return cls(record["kind"], record["reason"], record["completed_steps"])


class Session:
    """One terminal invocation, with no automatic retry, recovery, or domain acceptance.

    RunLimits remain the single execution budget. Policy and on_step are trusted,
    synchronous application callbacks; they must not block or perform external actions.
    prepare_request selects the context transported by Runtime. The SDK adds no history.
    Exceptions propagate after terminal recording. The caller owns the store/provider
    lifetimes and must keep them open until execute returns or raises.
    """

    def __init__(
        self,
        *,
        inference: InferenceAdapter,
        tools: ToolBroker,
        evaluator: Evaluator,
        run: RunStore,
        grants: tuple[str, ...],
        policy: Callable[[SessionView], SessionStep | SessionStop],
        prepare_request: Callable[[InferenceRequest], InferenceRequest] | None = None,
        on_step: Callable[[StepResult], None] | None = None,
        on_rejection: Callable[
            [ProposalRejected | InferenceRejected, SessionView], SessionStep | SessionStop
        ]
        | None = None,
        guards: tuple[DispatchGuard, ...] = (),
        on_event: Callable[[Event], None] | None = None,
    ) -> None:
        self._run = run
        self._runtime = Runtime(
            inference=inference,
            tools=tools,
            evaluator=evaluator,
            run=run,
            grants=grants,
            prepare_request=prepare_request,
            guards=guards,
            on_event=on_event,
        )
        self._policy = policy
        self._on_step = on_step
        self._on_rejection = on_rejection
        self._lock = asyncio.Lock()

    def _check_ready(self) -> None:
        self._run.check_ready()
        if self._run.seconds_remaining == 0:
            raise BudgetExhausted("Session wall-time budget exhausted")

    async def execute(self) -> SessionTermination:
        async with self._lock:
            # Refuse terminal or unresolved journals before calling application code.
            if self._run.outcome() is not None:
                raise ContractError("Run already ended; create a fresh session")
            if self._run.pending() is not None:
                raise UnresolvedEffect("Session cannot recover a pending operation")
            baseline = self._run.completed_operations()
            count = 0
            last: StepResult | None = None
            correction: SessionStep | SessionStop | None = None
            try:
                self._check_ready()
                async with asyncio.timeout(self._run.seconds_remaining):
                    while True:
                        decision = (
                            correction
                            if correction is not None
                            else self._policy(
                                SessionView(
                                    self._run.read(),
                                    self._run.latest_observation(),
                                    last,
                                    count,
                                )
                            )
                        )
                        correction = None
                        self._check_ready()
                        if isinstance(decision, SessionStop):
                            termination = SessionTermination("stopped", decision.reason, count)
                            self._run.finish(termination.to_json())
                            return termination
                        if not isinstance(decision, SessionStep):
                            raise ContractError(
                                "Session policy must return SessionStep or SessionStop"
                            )
                        try:
                            last = await self._runtime.step(
                                decision.objective, grants=decision.grants
                            )
                        except (ProposalRejected, InferenceRejected) as exc:
                            if (
                                self._on_rejection is None
                                or self._runtime.rejected_proposal is not exc
                            ):
                                raise
                            self._check_ready()
                            correction = self._on_rejection(
                                exc,
                                SessionView(
                                    self._run.read(), self._run.latest_observation(), last, count
                                ),
                            )
                            if not isinstance(correction, (SessionStep, SessionStop)):
                                raise ContractError(
                                    "Rejection policy must return SessionStep or SessionStop"
                                ) from exc
                            continue
                        count += 1
                        if self._on_step is not None:
                            self._on_step(last)
            except BaseException as exc:
                kind: Literal["budget_exhausted", "timed_out", "cancelled", "failed"]
                if isinstance(exc, asyncio.CancelledError):
                    kind = "cancelled"
                elif isinstance(exc, TimeoutError):
                    kind = "timed_out"
                elif isinstance(exc, BudgetExhausted):
                    kind = "budget_exhausted"
                else:
                    kind = "failed"
                # Exception text can contain credentials or payloads; persist only its type.
                count = self._run.completed_operations() - baseline
                termination = SessionTermination(kind, type(exc).__name__, count)
                self._run.finish(termination.to_json())
                raise
