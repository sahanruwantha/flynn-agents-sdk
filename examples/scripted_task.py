"""A complete durable operation without a provider key."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from flynn_agents_sdk import (
    Candidate,
    Evaluation,
    RunLimits,
    Runtime,
    ScriptedAdapter,
    SQLiteRun,
    Tool,
    ToolBroker,
    ToolCall,
    Verdict,
)


def validate(arguments: str) -> None:
    if arguments != "4":
        raise ValueError("Expected 4")


async def increment(arguments: str) -> str:
    return str(int(arguments) + 1)


class Check:
    async def evaluate(self, candidate: Candidate) -> Evaluation:
        return Evaluation(
            candidate,
            "successor/v1",
            "integer successor",
            Verdict.SATISFIED if candidate.output == "5" else Verdict.FAILED,
            "Expected output 5",
            state_update=candidate.output,
        )


async def main() -> None:
    with TemporaryDirectory() as folder:
        path = Path(folder) / "run.sqlite"
        with SQLiteRun.create(
            path, run_id="example", initial_state="4", limits=RunLimits(1, 1, 0)
        ) as run:
            runtime = Runtime(
                inference=ScriptedAdapter([ToolCall("increment", "4")]),
                tools=ToolBroker([Tool("increment", validate, increment)]),
                evaluator=Check(),
                run=run,
                grants=("increment",),
            )
            result = await runtime.step("Increment 4")
            print(f"Accepted update: {result.committed}; revision: {result.state.revision}")
        with SQLiteRun.open(path) as recovered:
            print(f"Reopened state: {recovered.read().value}; budget: {recovered.remaining()}")


if __name__ == "__main__":
    asyncio.run(main())
