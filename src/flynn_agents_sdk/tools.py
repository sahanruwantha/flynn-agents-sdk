"""Explicit registration and dispatch of trusted application tools."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from flynn_agents_sdk.contracts import (
    BudgetExhausted,
    ContractError,
    ProposalRejected,
    ToolCall,
    ToolSpec,
)


@dataclass(frozen=True)
class Tool:
    name: str
    validate: Callable[[str], None]
    execute: Callable[[str], Awaitable[str]]
    external_action: bool = False
    observation: bool = False
    description: str = ""
    parameters_json: str = '{"type":"object","properties":{},"additionalProperties":false}'


class ToolBroker:
    """The registry contains trusted code, never model-supplied Python.

    Validators must be pure and raise ValueError for malformed arguments.
    Permission checks precede validation; validation precedes dispatch.
    """

    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if not tool.name or tool.name in self._tools:
                raise ContractError(f"Empty or duplicate tool name: {tool.name!r}")
            self._tools[tool.name] = tool

    def specifications(self, grants: tuple[str, ...]) -> tuple[ToolSpec, ...]:
        return tuple(
            ToolSpec(tool.name, tool.description, tool.parameters_json)
            for tool in self._tools.values()
            if tool.name in grants
        )

    def prepare(self, call: ToolCall, grants: tuple[str, ...]) -> Tool:
        if not isinstance(call, ToolCall):
            raise ContractError("Inference must return a ToolCall")
        if not isinstance(call.name, str) or not isinstance(call.arguments, str):
            raise ContractError("Tool name and arguments must be strings")
        if call.name not in grants:
            raise ContractError(f"Tool {call.name!r} is not granted")
        if call.name not in self._tools:
            raise ContractError(f"Tool {call.name!r} is not registered")
        tool = self._tools[call.name]
        try:
            tool.validate(call.arguments)
        except BudgetExhausted:
            raise
        except ValueError as error:
            raise ProposalRejected(f"Invalid arguments for {call.name!r}: {error}") from error
        return tool
