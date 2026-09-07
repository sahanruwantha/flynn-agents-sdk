"""A complete native guarded session, with HTTP mocked only at the provider boundary."""

import asyncio
import json
from dataclasses import replace

import httpx

from flynn_agents_sdk import (
    DispatchGuard,
    Evaluation,
    GuardDecision,
    ImageContent,
    ImageInput,
    RunLimits,
    Session,
    SessionStep,
    SessionStop,
    SessionTermination,
    SQLiteRun,
    TextContent,
    Tool,
    ToolBroker,
    ToolResult,
    Verdict,
)
from flynn_agents_sdk.deepseek import DeepSeekAdapter


def test_native_multimodal_session_uses_one_durable_budget(tmp_path):
    requests = []
    image = "data:image/png;base64,aGVsbG8="

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        name = "measure" if len(requests) == 1 else "submit"
        assert payload["max_tokens"] == (4 if len(requests) == 1 else 2)
        if name == "submit":
            assert payload["messages"][1]["content"][1]["image_url"]["url"] == image
        return httpx.Response(
            200,
            json={
                "id": f"response-{len(requests)}",
                "model": payload["model"],
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {"name": name, "arguments": "{}"},
                                }
                            ]
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    async def measure(args):
        return ToolResult(
            (TextContent("three objects measured"), ImageContent(image)), '{"count":3}'
        )

    async def submit(args):
        return ToolResult(data_json='{"submitted":true}')

    def validate(args):
        if args:
            raise ValueError("No arguments accepted")

    async def guard(context):
        return GuardDecision(
            context.call.name in context.request.allowed_tools, "harness scope checked"
        )

    def prepare(request):
        # The harness explicitly selects this image; SDK never injects result images itself.
        if request.observation:
            observation = ToolResult.from_json(request.observation)
            selected = tuple(
                ImageInput(item.url, item.detail)
                for item in observation.content
                if isinstance(item, ImageContent)
            )
            return replace(request, images=selected)
        return request

    def policy(view):
        if view.completed_steps == 2:
            return SessionStop("submitted for independent acceptance")
        return SessionStep(
            "Observe then submit", ("measure",) if view.completed_steps == 0 else ("submit",)
        )

    class Observe:
        async def evaluate(self, candidate):
            return Evaluation(
                candidate, "observation", "transport", Verdict.SATISFIED, "recorded only"
            )

    tools = ToolBroker(
        [
            Tool.structured(
                name,
                description=name,
                parameters_json='{"type":"object"}',
                validate=validate,
                execute=handler,
            )
            for name, handler in (("measure", measure), ("submit", submit))
        ]
    )
    path = tmp_path / "session.sqlite"

    async def execute():
        async with DeepSeekAdapter(
            api_key="offline-key", max_tokens=4, transport=httpx.MockTransport(respond)
        ) as adapter:
            with SQLiteRun.create(
                path,
                run_id="readiness",
                initial_state="unaccepted",
                limits=RunLimits(2, 2, 0, 10, output_tokens=4),
            ) as run:
                result = await Session(
                    inference=adapter,
                    tools=tools,
                    evaluator=Observe(),
                    run=run,
                    grants=("measure", "submit"),
                    policy=policy,
                    prepare_request=prepare,
                    guards=(DispatchGuard("scope", guard),),
                ).execute()
                assert result.completed_steps == 2
                assert run.output_budget().spent == 4
                assert run.output_budget().available == 0
                assert run.usage_summary()["known_input_tokens"] == 20
                assert run.read().revision == 0

    asyncio.run(execute())
    assert len(requests) == 2
    with SQLiteRun.open(path) as run:
        assert SessionTermination.from_json(run.outcome()).kind == "stopped"
        assert len(run.records()["guard_decisions"]) == 2
        assert len(run.records()["lifecycle_events"]) == 12
        assert run.read().value == "unaccepted"
