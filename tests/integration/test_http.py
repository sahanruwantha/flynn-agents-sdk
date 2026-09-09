import asyncio
import hashlib
import subprocess
import sys
from dataclasses import replace

import httpx
import pytest

from flynn_agents_sdk.http import FetchPolicy, FetchRefused, fetch_https

POLICY = FetchPolicy(("https://docs.example.test",), 32, 1)


class Body(httpx.AsyncByteStream):
    def __init__(self, chunks, *, wait=None):
        self.chunks = chunks
        self.wait = wait
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.wait:
            await self.wait()

    async def aclose(self):
        self.closed = True


def execute(handler, url="https://docs.example.test/api", policy=POLICY):
    return asyncio.run(fetch_https(url, policy=policy, transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example.test/api",
        "https://other.test/",
        "https://docs.example.test.other/",
        "https://docs.example.test@other.test/",
        "https://x:secret@docs.example.test/",
        "https://docs.example.test:8443/",
        "https://docs.example.test/a#fragment",
        " https://docs.example.test/",
        "https://docs.example.test/\n",
        "//docs.example.test/",
        "https://docs.example.test/\x7f",
        "https://docs.example.test/\u0081",
        "https://docs.example.test/\u00a0",
        "https://docs.example.test\\@other.test/",
    ],
)
def test_disallowed_urls_refuse_before_network(url):
    with pytest.raises(FetchRefused):
        execute(lambda _: pytest.fail("disallowed URL dispatched"), url)


def test_success_keeps_exact_bytes_status_and_identity(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://unused.example.test")
    body = Body([b"hello ", b"world"])
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["accept-encoding"] == "identity"
        assert "authorization" not in request.headers
        return httpx.Response(
            404, headers={"content-type": "text/plain", "content-length": "11"}, stream=body
        )

    result = execute(handle)
    assert result.body == b"hello world" and result.status_code == 404
    assert result.sha256 == hashlib.sha256(result.body).hexdigest()
    assert result.requested_url == result.final_url == "https://docs.example.test/api"
    assert result.content_type == "text/plain" and result.redirect_urls == ()
    assert len(requests) == 1 and body.closed


def test_relative_redirect_is_bounded_and_recorded():
    bodies = []
    requests = []

    def handle(request):
        requests.append(str(request.url))
        body = Body([b"ignored redirect" if len(requests) == 1 else b"final"])
        bodies.append(body)
        return (
            httpx.Response(302, headers={"location": "/manual"}, stream=body)
            if len(requests) == 1
            else httpx.Response(200, stream=body)
        )

    result = execute(handle)
    assert requests == ["https://docs.example.test/api", "https://docs.example.test/manual"]
    assert result.redirect_urls == (requests[1],) and result.final_url == requests[1]
    assert result.body == b"final" and all(body.closed for body in bodies)


@pytest.mark.parametrize("location", ["https://other.test/", "http://docs.example.test/", "/again"])
def test_redirect_cannot_escape_policy_or_cap(location):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": location}, stream=Body([]))

    with pytest.raises(FetchRefused):
        execute(handle, policy=replace(POLICY, max_redirects=0 if location == "/again" else 3))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "headers,chunks,match",
    [
        ({"content-length": "100"}, [], "declared byte cap"),
        ({"content-length": "9" * 5000}, [], "declared byte cap"),
        ({}, [b"x" * 16, b"y" * 17], "streamed byte cap"),
        ({"content-length": "-1"}, [], "unsigned integer"),
        ({"content-length": "3"}, [b"xx"], "differs"),
        ({"content-encoding": "gzip"}, [b"compressed"], "compression"),
    ],
)
def test_response_refusal_closes_stream_without_partial_success(headers, chunks, match):
    body = Body(chunks)
    with pytest.raises(FetchRefused, match=match):
        execute(lambda _: httpx.Response(200, headers=headers, stream=body))
    assert body.closed


def test_total_deadline_covers_streaming():
    async def delay():
        await asyncio.sleep(10)

    body = Body([b"x"], wait=delay)
    with pytest.raises(TimeoutError):
        execute(
            lambda _: httpx.Response(200, stream=body), policy=replace(POLICY, timeout_seconds=0.01)
        )
    assert body.closed


def test_cancellation_closes_stream_and_propagates():
    async def run():
        started = asyncio.Event()

        async def wait():
            started.set()
            await asyncio.Event().wait()

        body = Body([], wait=wait)
        task = asyncio.create_task(
            fetch_https(
                "https://docs.example.test/api",
                policy=POLICY,
                transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=body)),
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert body.closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_origins": ()},
        {"allowed_origins": ("https://docs.example.test/path",)},
        {"allowed_origins": ("https://docs.example.test", "https://docs.example.test:443")},
        {"max_response_bytes": True},
        {"max_response_bytes": 0},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 0},
        {"max_redirects": -1},
    ],
)
def test_policy_has_explicit_finite_bounds(change):
    with pytest.raises(ValueError):
        replace(POLICY, **change)


def test_base_sdk_does_not_require_optional_http_dependency():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.modules['httpx'] = None; import flynn_agents_sdk"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
