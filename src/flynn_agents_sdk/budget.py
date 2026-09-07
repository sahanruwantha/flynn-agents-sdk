"""Conservative operation accounting; failed dispatches consume capacity."""

import math
import time

from flynn_agents_sdk.contracts import BudgetExhausted


class Budget:
    """Bound inference and tool attempts for one sequential runtime.

    Counts are separate from token or monetary usage. An optional monotonic
    deadline starts at construction and supports cooperative async cancellation.
    Reservations are consumed permanently, including on cancellation or failure.
    """

    def __init__(
        self,
        *,
        inference_calls: int,
        tool_calls: int,
        external_actions: int | None = None,
        wall_time_seconds: float | None = None,
    ) -> None:
        for value in (inference_calls, tool_calls):
            if type(value) is not int or value < 0:
                raise ValueError("Operation limits must be nonnegative integers")
        if external_actions is not None and (
            type(external_actions) is not int or external_actions < 0
        ):
            raise ValueError("External action limit must be a nonnegative integer")
        if wall_time_seconds is not None and (
            not math.isfinite(wall_time_seconds) or wall_time_seconds <= 0
        ):
            raise ValueError("Wall time must be finite and positive")
        self._deadline = None if wall_time_seconds is None else time.monotonic() + wall_time_seconds
        self._external_remaining = external_actions
        self._inference_remaining = inference_calls
        self._tools_remaining = tool_calls

    @property
    def inference_remaining(self) -> int:
        return self._inference_remaining

    @property
    def tools_remaining(self) -> int:
        return self._tools_remaining

    @property
    def seconds_remaining(self) -> float | None:
        return None if self._deadline is None else max(0.0, self._deadline - time.monotonic())

    @property
    def external_actions_remaining(self) -> int | None:
        return self._external_remaining

    def _check_deadline(self) -> None:
        if self.seconds_remaining == 0:
            raise BudgetExhausted("Episode wall-time budget exhausted")

    def reserve_inference(self) -> None:
        self._check_deadline()
        if self._inference_remaining == 0:
            raise BudgetExhausted("Inference budget exhausted; supply a new explicit budget")
        self._inference_remaining -= 1

    def reserve_tool(self, *, external_action: bool = False) -> None:
        self._check_deadline()
        if self._tools_remaining == 0:
            raise BudgetExhausted("Tool budget exhausted; no tool was dispatched")
        if external_action and self._external_remaining == 0:
            raise BudgetExhausted("External action budget exhausted; no action was dispatched")
        self._tools_remaining -= 1
        if external_action and self._external_remaining is not None:
            self._external_remaining -= 1
