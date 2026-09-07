"""Deterministic adapter for offline examples and runtime tests."""

from collections.abc import Iterable

from flynn_agents_sdk.contracts import ContractError, InferenceRequest, ToolCall


class ScriptedAdapter:
    def __init__(self, calls: Iterable[ToolCall]) -> None:
        self._calls = iter(calls)

    async def generate(self, request: InferenceRequest) -> ToolCall:
        try:
            return next(self._calls)
        except StopIteration as error:
            raise ContractError("Script exhausted; supply another scripted proposal") from error
