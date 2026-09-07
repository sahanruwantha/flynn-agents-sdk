"""Run with: uv run python examples/scripted_task.py."""

import asyncio

from flynn_agents_sdk import (
    Budget,
    Candidate,
    Evaluation,
    InMemoryStore,
    Runtime,
    ScriptedAdapter,
    Tool,
    ToolBroker,
    ToolCall,
    Verdict,
)


def validate_integer(arguments: str) -> None:
    int(arguments)


async def increment(arguments: str) -> str:
    return str(int(arguments) + 1)


class IncrementEvaluator:
    async def evaluate(self, candidate: Candidate) -> Evaluation:
        expected = int(candidate.base.value) + 1
        passed = candidate.call.arguments == candidate.base.value and candidate.output == str(
            expected
        )
        return Evaluation(
            candidate,
            "increment/v1",
            "one integer successor",
            Verdict.SATISFIED if passed else Verdict.FAILED,
            f"Expected {expected}; observed {candidate.output}",
        )


async def main() -> None:
    runtime = Runtime(
        inference=ScriptedAdapter([ToolCall("increment", "4")]),
        tools=ToolBroker([Tool("increment", validate_integer, increment)]),
        evaluator=IncrementEvaluator(),
        store=InMemoryStore("4"),
        budget=Budget(inference_calls=1, tool_calls=1),
        grants=("increment",),
    )
    result = await runtime.step("Increment the current integer once")
    print(f"Accepted: {result.committed}; revision: {result.state.revision}")
    print(f"State: {result.state.value}")
    for event in runtime.events:
        print(f"{event.stage}: {event.detail}")


if __name__ == "__main__":
    asyncio.run(main())
