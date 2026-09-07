"""Deterministic adapter for offline examples and runtime tests."""

from collections.abc import Iterable

from flynn_agents_sdk.contracts import (
    InferenceFailure,
    InferenceRequest,
    InferenceResult,
    InferenceUsage,
    ToolCall,
)


class ScriptedAdapter:
    def __init__(self, calls: Iterable[ToolCall]) -> None:
        self._calls = iter(calls)

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        try:
            return InferenceResult.scripted(next(self._calls))
        except StopIteration as error:
            raise InferenceFailure(
                "Script exhausted; supply another scripted proposal",
                usage=InferenceUsage.scripted(),
            ) from error
