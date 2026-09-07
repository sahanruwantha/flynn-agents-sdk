import json

import pytest

from flynn_agents_sdk import (
    ContractError,
    Evaluation,
    ImageContent,
    ProposalRejected,
    RunLimits,
    Runtime,
    ScriptedAdapter,
    SQLiteRun,
    TextContent,
    Tool,
    ToolBroker,
    ToolCall,
    ToolResult,
    UnresolvedEffect,
    Verdict,
)


class Observe:
    async def evaluate(self, candidate):
        return Evaluation(candidate, "fixture", "observation", Verdict.SATISFIED, "recorded")


def test_result_rejects_ambiguous_payloads():
    for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
        with pytest.raises(ContractError):
            ToolResult(data_json=data)
    for value in ([], ("text",)):
        with pytest.raises(ContractError):
            ToolResult(content=value)
    result = ToolResult(
        (TextContent("measured"), ImageContent("artifact:render-sha256")), '{"x":2}'
    )
    assert ToolResult.from_json(result.to_json()) == result
    document = json.loads(result.to_json())
    for mutation in ({"schema": "unknown"}, {"unexpected": True}, {"content": [{"type": "audio"}]}):
        with pytest.raises(ContractError):
            ToolResult.from_json(json.dumps({**document, **mutation}))


@pytest.mark.parametrize("status", ["ok", "refused"])
def test_multimodal_observation_survives_reopen_without_state_commit(tmp_path, status):
    import asyncio

    expected = ToolResult(
        (TextContent("current measurement"), ImageContent("artifact:exact-render", "high")),
        '{"count":3}',
        status,
    )

    def validate(args):
        if set(args) != {"frame"} or type(args["frame"]) is not int:
            raise ValueError("one integer frame required")

    async def execute(args):
        assert args == {"frame": 4}
        return expected

    tool = Tool.structured(
        "measure",
        description="Read current frame",
        parameters_json=(
            '{"type":"object","properties":{"frame":{"type":"integer"}},"required":["frame"]}'
        ),
        validate=validate,
        execute=execute,
    )
    path = tmp_path / "run.sqlite"
    with SQLiteRun.create(
        path, run_id="structured", initial_state="unchanged", limits=RunLimits(1, 1, 0)
    ) as run:
        runtime = Runtime(
            inference=ScriptedAdapter([ToolCall("measure", '{"frame":4}')]),
            tools=ToolBroker([tool]),
            evaluator=Observe(),
            run=run,
            grants=("measure",),
        )
        result = asyncio.run(runtime.step("observe"))
        assert ToolResult.from_json(result.candidate.output) == expected
        assert not result.committed
        assert run.read().value == "unchanged"
        run.finish("observation collected")
    with SQLiteRun.open(path) as run:
        assert ToolResult.from_json(run.latest_observation()) == expected
        assert run.read().revision == 0


def test_invalid_arguments_and_ungranted_call_do_not_reach_handler():
    calls = []

    def validate(args):
        if args != {"frame": 4}:
            raise ValueError("incorrect frame")

    async def execute(args):
        calls.append(args)
        return ToolResult()

    broker = ToolBroker(
        [
            Tool.structured(
                "measure",
                description="read",
                parameters_json='{"type":"object"}',
                validate=validate,
                execute=execute,
            )
        ]
    )
    for arguments in ("[]", '{"frame":3}', '{"frame":3,"frame":4}'):
        with pytest.raises(ProposalRejected):
            broker.prepare(ToolCall("measure", arguments), ("measure",))
    with pytest.raises(ContractError, match="not granted"):
        broker.prepare(ToolCall("measure", '{"frame":4}'), ())
    assert calls == []


@pytest.mark.parametrize("bad_result", [True, False])
def test_handler_failures_remain_unresolved_dispatches(tmp_path, bad_result):
    import asyncio

    async def execute(args):
        if bad_result:
            return {"text": "wrong result contract"}
        raise RuntimeError("handler defect")

    tool = Tool.structured(
        "act",
        description="action",
        parameters_json='{"type":"object"}',
        validate=lambda args: None,
        execute=execute,
        external_action=True,
    )
    with SQLiteRun.create(
        tmp_path / "run.sqlite",
        run_id="failed",
        initial_state="unchanged",
        limits=RunLimits(1, 1, 1),
    ) as run:
        runtime = Runtime(
            inference=ScriptedAdapter([ToolCall("act", "{}")]),
            tools=ToolBroker([tool]),
            evaluator=Observe(),
            run=run,
            grants=("act",),
        )
        with pytest.raises(ContractError if bad_result else RuntimeError):
            asyncio.run(runtime.step("act"))
        assert run.read().revision == 0
        assert run.latest_observation() is None
        assert run.remaining()["external"] == 0
        assert run.pending() is not None
        with pytest.raises(UnresolvedEffect):
            run.check_ready()
