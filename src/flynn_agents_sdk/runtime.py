"""Explicit inference, dispatch and evaluated publication over a durable run."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from flynn_agents_sdk.contracts import (
    ContractError,
    Evaluator,
    Event,
    InferenceAdapter,
    InferenceCancelled,
    InferenceFailure,
    InferenceRequest,
    InferenceResult,
    OutputBoundedInference,
    OutputReservation,
    RunStore,
    StepResult,
    UnresolvedEffect,
)
from flynn_agents_sdk.tools import ToolBroker


class Runtime:
    """One operation per step; no hidden retry or domain-success declaration.

    The store owns run-wide serialization and durable budgets. Tools and evaluators
    remain trusted application code; cooperative cancellation cannot stop blocking code.
    """

    def __init__(
        self,
        *,
        inference: InferenceAdapter,
        tools: ToolBroker,
        evaluator: Evaluator,
        run: RunStore,
        grants: tuple[str, ...],
        prepare_request: Callable[[InferenceRequest], InferenceRequest] | None = None,
    ) -> None:
        self._prepare_request = prepare_request
        self._inference = inference
        self._tools = tools
        self._evaluator = evaluator
        self._run = run
        self._grants = tuple(grants)
        self._lock = asyncio.Lock()
        self._events: list[Event] = []

    @property
    def events(self) -> tuple[Event, ...]:
        """Process-local presentation events. Durable operation records live in the store."""
        return tuple(self._events)

    async def step(self, objective: str, *, grants: tuple[str, ...] | None = None) -> StepResult:
        async with self._lock:
            self._run.check_ready()
            async with asyncio.timeout(self._run.seconds_remaining):
                return await self._step(objective, grants)

    async def _step(self, objective: str, grants: tuple[str, ...] | None) -> StepResult:
        effective = self._grants if grants is None else tuple(grants)
        if not set(effective) <= set(self._grants):
            raise ContractError("Per-step grants cannot expand runtime authority")
        base = self._run.read()
        request = InferenceRequest(
            objective,
            base,
            effective,
            self._run.latest_observation(),
            self._tools.specifications(effective),
        )
        if self._prepare_request is not None:
            request = self._prepare_request(request)
        if request.base != base:
            raise ContractError("Prepared request cannot substitute accepted state")
        if not set(request.allowed_tools) <= set(effective):
            raise ContractError("Prepared request cannot expand per-step authority")
        effective = tuple(request.allowed_tools)
        request = replace(
            request, tools=tuple(tool for tool in request.tools if tool.name in effective)
        )
        reservation: OutputReservation | None = None
        available = self._run.output_budget().available
        if available is not None:
            if not isinstance(self._inference, OutputBoundedInference):
                raise ContractError("Output-limited runs require an adapter with plan_output")
            reservation = self._inference.plan_output(request, available)
            if not isinstance(reservation, OutputReservation):
                raise ContractError("plan_output must return an OutputReservation")
            if (
                reservation.kind == "model"
                and request.max_output_tokens is not None
                and reservation.tokens > request.max_output_tokens
            ):
                raise ContractError("Output plan cannot expand the prepared request ceiling")
            request = replace(request, max_output_tokens=reservation.tokens)
        operation_id = uuid4().hex
        self._run.start(operation_id, request, reservation)
        self._events.append(Event(operation_id, "started", ""))
        stage = "inference"
        try:
            try:
                response = await self._inference.generate(request)
            except (InferenceFailure, InferenceCancelled) as error:
                if error.usage is not None:
                    self._run.record_usage(operation_id, error.usage)
                raise
            if not isinstance(response, InferenceResult):
                raise ContractError("Inference must return an InferenceResult")
            self._run.record_usage(operation_id, response.usage)
            call = response.call
            self._run.proposed(operation_id, call)
            stage = "validation"
            tool = self._tools.prepare(call, effective)
            self._run.dispatch(
                operation_id, observation=tool.observation, external_action=tool.external_action
            )
            stage = "tool"
            self._events.append(Event(operation_id, "tool_dispatched", call.name))
            output = await tool.execute(call.arguments)
            candidate = self._run.returned(operation_id, output)
            self._events.append(Event(operation_id, "tool_returned", call.name))
            stage = "evaluation"
            result = self._run.complete(await self._evaluator.evaluate(candidate))
            self._events.append(
                Event(operation_id, "committed" if result.committed else "observed", "")
            )
            return result
        except BaseException as error:
            # Root boundary records diagnostics, preserving cancellation and programming errors.
            self._run.failed(operation_id, f"{stage}: {type(error).__name__}")
            outcome = "effect_unknown" if stage == "tool" else "failed"
            self._events.append(Event(operation_id, outcome, stage))
            raise

    async def recover(self) -> StepResult | None:
        """Explicitly close an undispatched attempt or re-evaluate a returned result.

        Never re-run inference or a tool. Ownership must already have been acquired
        by the store; a dispatched operation with no result remains indeterminate.
        """
        async with self._lock:
            if self._run.outcome() is not None:
                raise ContractError("Run already ended; recovery cannot reopen it")
            pending = self._run.pending()
            if pending is None:
                return None
            if pending.stage == "dispatched":
                raise UnresolvedEffect("External effect is unknown; adapter evidence is required")
            if pending.candidate is None:
                self._run.abandon_undispatched(pending.id)
                return None
            async with asyncio.timeout(self._run.seconds_remaining):
                return self._run.complete(await self._evaluator.evaluate(pending.candidate))
