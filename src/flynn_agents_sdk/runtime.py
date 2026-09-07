"""One explicit inference/tool/evaluation transaction per step."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from flynn_agents_sdk.budget import Budget
from flynn_agents_sdk.contracts import (
    Candidate,
    ContractError,
    Evaluator,
    Event,
    InferenceAdapter,
    InferenceRequest,
    Journal,
    StateStore,
    StepResult,
    UnresolvedEffect,
    Verdict,
    check_evaluation,
)
from flynn_agents_sdk.tools import ToolBroker


class Runtime:
    """Sequential async execution with in-memory diagnostics and no automatic retry.

    Tools and evaluators are trusted application code. A failed/cancelled tool
    dispatch may already have affected the outside world; its effect is unknown.
    Committing an output does not declare the application's overall task complete.
    """

    def __init__(
        self,
        *,
        inference: InferenceAdapter,
        tools: ToolBroker,
        evaluator: Evaluator,
        store: StateStore,
        budget: Budget,
        grants: tuple[str, ...],
        journal: Journal | None = None,
        prepare_request: Callable[[InferenceRequest], InferenceRequest] | None = None,
    ) -> None:
        self._prepare_request = prepare_request
        self._journal = journal
        self._inference = inference
        self._tools = tools
        self._evaluator = evaluator
        self._store = store
        self._budget = budget
        self._grants = tuple(grants)
        self._lock = asyncio.Lock()
        self._events: list[Event] = []

    @property
    def events(self) -> tuple[Event, ...]:
        """Process-local diagnostic snapshot; not a durable replay journal."""
        return tuple(self._events)

    async def step(self, objective: str, *, grants: tuple[str, ...] | None = None) -> StepResult:
        async with self._lock:
            async with asyncio.timeout(self._budget.seconds_remaining):
                return await self._step(objective, grants)

    async def _step(self, objective: str, grants: tuple[str, ...] | None) -> StepResult:
        step_id = uuid4().hex
        stage = "inference"
        self._events.append(Event(step_id, "started", ""))
        try:
            if self._journal is not None and self._journal.unresolved():
                raise UnresolvedEffect("Prior action has no recorded result; stop and reconcile")
            effective = self._grants if grants is None else tuple(grants)
            if not set(effective) <= set(self._grants):
                raise ContractError("Per-step grants cannot expand runtime authority")
            base = self._store.read()
            observation = self._journal.latest_observation() if self._journal is not None else None
            request = InferenceRequest(
                objective, base, effective, observation, self._tools.specifications(effective)
            )
            if self._prepare_request is not None:
                request = self._prepare_request(request)
            if not set(request.allowed_tools) <= set(effective):
                raise ContractError("Prepared request cannot expand per-step authority")
            effective = tuple(request.allowed_tools)
            request = replace(request, tools=tuple(t for t in request.tools if t.name in effective))
            self._budget.reserve_inference()
            call = await self._inference.generate(request)
            stage = "validation"
            tool = self._tools.prepare(call, effective)
            self._budget.reserve_tool(external_action=tool.external_action)
            if self._journal is not None:
                self._journal.begin(step_id, base, call, observation=tool.observation)
            stage = "tool"
            self._events.append(Event(step_id, "tool_dispatched", call.name))
            output = await tool.execute(call.arguments)
            stage = "result"
            self._events.append(Event(step_id, "tool_returned", call.name))
            if not isinstance(output, str):
                raise ContractError("Tool output must be a string")
            if self._journal is not None:
                self._journal.returned(step_id, output)
            candidate = Candidate(step_id, base, call, output)
            stage = "evaluation"
            evaluation = await self._evaluator.evaluate(candidate)
            check_evaluation(candidate, evaluation)
            if self._journal is not None:
                self._journal.evaluated(step_id, evaluation)
            if evaluation.verdict is not Verdict.SATISFIED:
                self._events.append(Event(step_id, "not_accepted", evaluation.verdict.value))
                return StepResult(candidate, evaluation, self._store.read(), False)
            stage = "commit"
            state = self._store.commit(candidate, evaluation)
            self._events.append(Event(step_id, "committed", str(state.revision)))
            return StepResult(candidate, evaluation, state, True)
        except asyncio.CancelledError:
            outcome = "effect_unknown" if stage == "tool" else "cancelled"
            self._events.append(Event(step_id, outcome, stage))
            raise
        except Exception as error:
            # Root execution boundary records failure, then preserves the exception.
            outcome = "effect_unknown" if stage == "tool" else "failed"
            self._events.append(Event(step_id, outcome, f"{stage}: {type(error).__name__}"))
            raise
