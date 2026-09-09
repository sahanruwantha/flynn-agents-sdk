import asyncio
import json

import httpx
import pytest

from flynn_agents_sdk import (
    Evaluation,
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
    Verdict,
)
from flynn_agents_sdk.http import FetchPolicy, FetchRefused, fetch_https


class Observe:
    async def evaluate(self, candidate):
        result = ToolResult.from_json(candidate.output)
        verdict = Verdict.SATISFIED if result.status == "ok" else Verdict.FAILED
        return Evaluation(candidate, "transport", "observation", verdict, "HTTP result recorded")


@pytest.mark.parametrize("mode", ["ok", "oversize", "transport_error", "cancel", "invalid"])
def test_http_operation_retains_accounting_and_never_commits_state(tmp_path, mode):
    policy = FetchPolicy(("https://docs.example.test",), 8, 1)
    requests = []
    path = tmp_path / "fetch.sqlite"

    async def run():
        entered = asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                entered.set()
                if mode == "cancel":
                    await asyncio.Event().wait()
                yield b"xxxxxxxxx" if mode == "oversize" else b"page"

        def handle(request):
            requests.append(request)
            if mode == "transport_error":
                raise httpx.ConnectError("offline injected failure", request=request)
            return httpx.Response(200, stream=Stream())

        def validate(arguments):
            if set(arguments) != {"url"} or not isinstance(arguments["url"], str):
                raise ValueError("one URL string required")
            policy.validate_url(arguments["url"])

        async def execute(arguments):
            try:
                fetched = await fetch_https(
                    arguments["url"], policy=policy, transport=httpx.MockTransport(handle)
                )
            except FetchRefused as exc:
                return ToolResult((TextContent(str(exc)),), "{}", "refused")
            return ToolResult(
                (TextContent(fetched.body.decode()),),
                json.dumps(
                    {
                        "final_url": fetched.final_url,
                        "sha256": fetched.sha256,
                        "status_code": fetched.status_code,
                    }
                ),
            )

        tool = Tool.structured(
            "fetch",
            description="Read a bounded permitted response",
            parameters_json='{"type":"object"}',
            validate=validate,
            execute=execute,
            external_action=True,
        )
        url = "https://outside.example.test/" if mode == "invalid" else "https://docs.example.test/"
        with SQLiteRun.create(
            path, run_id="http", initial_state="unaccepted", limits=RunLimits(1, 1, 1)
        ) as journal:
            runtime = Runtime(
                inference=ScriptedAdapter([ToolCall("fetch", json.dumps({"url": url}))]),
                tools=ToolBroker([tool]),
                evaluator=Observe(),
                run=journal,
                grants=("fetch",),
            )
            if mode == "cancel":
                task = asyncio.create_task(runtime.step("read"))
                await entered.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif mode == "transport_error":
                with pytest.raises(httpx.ConnectError):
                    await runtime.step("read")
            elif mode == "invalid":
                with pytest.raises(ProposalRejected):
                    await runtime.step("read")
            else:
                outcome = await runtime.step("read")
                assert not outcome.committed
                assert ToolResult.from_json(outcome.candidate.output).status == (
                    "ok" if mode == "ok" else "refused"
                )
                journal.finish("read complete")

    asyncio.run(run())
    with SQLiteRun.open(path) as journal:
        assert journal.read().value == "unaccepted" and journal.read().revision == 0
        assert journal.records()["commits"] == []
        assert journal.remaining() == {
            "inference": 0,
            "tool": int(mode == "invalid"),
            "external": int(mode == "invalid"),
        }
        assert (journal.pending() is not None) == (mode in {"transport_error", "cancel"})
    assert len(requests) == int(mode != "invalid")
