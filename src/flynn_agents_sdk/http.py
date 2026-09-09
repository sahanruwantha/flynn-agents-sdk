"""Bounded HTTPS reads under a caller-supplied origin policy (optional http extra).

This transport supplies no documentation policy, model context, domain evaluation,
retry, or accepted state. Register it inside an external-action tool; the runtime
then owns reservations and the caller chooses which response becomes observation.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

import httpx


class FetchRefused(ValueError):
    """The request or response exceeded the caller's declared fetch policy."""


def _url(value: str) -> httpx.URL:
    if (
        not isinstance(value, str)
        or not value
        or any(c.isspace() or ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
    ):
        raise FetchRefused("HTTPS URL must be nonempty and contain no whitespace or controls")
    if "\\" in value:
        raise FetchRefused("HTTPS URL must not contain backslashes")
    try:
        parsed = httpx.URL(value)
    except httpx.InvalidURL as exc:
        raise FetchRefused("Malformed HTTPS URL") from exc
    if parsed.scheme != "https" or not parsed.host or parsed.userinfo or parsed.fragment:
        raise FetchRefused("Fetch requires an absolute HTTPS URL without credentials or fragment")
    return parsed


def _origin(url: httpx.URL) -> tuple[str, int]:
    return url.raw_host.decode("ascii"), url.port or 443


@dataclass(frozen=True)
class FetchPolicy:
    allowed_origins: tuple[str, ...]
    max_response_bytes: int
    timeout_seconds: float
    max_redirects: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_origins, tuple) or not self.allowed_origins:
            raise ValueError("Fetch policy requires an explicit nonempty tuple of HTTPS origins")
        identities = []
        for value in self.allowed_origins:
            parsed = _url(value)
            if parsed.path != "/" or parsed.query:
                raise ValueError("Fetch policy origins cannot include a path or query")
            identities.append(_origin(parsed))
        if len(identities) != len(set(identities)):
            raise ValueError("Fetch policy origins must be distinct")
        if type(self.max_response_bytes) is not int or self.max_response_bytes <= 0:
            raise ValueError("Fetch response byte cap must be a positive integer")
        if type(self.max_redirects) is not int or self.max_redirects < 0:
            raise ValueError("Fetch redirect cap must be a nonnegative integer")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds < float("inf")
        ):
            raise ValueError("Fetch timeout must be positive and finite")

    def validate_url(self, value: str) -> httpx.URL:
        parsed = _url(value)
        if _origin(parsed) not in {_origin(_url(origin)) for origin in self.allowed_origins}:
            raise FetchRefused("HTTPS request origin is outside the caller's fetch policy")
        return parsed


@dataclass(frozen=True)
class FetchResponse:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    redirect_urls: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


async def fetch_https(
    url: str,
    *,
    policy: FetchPolicy,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResponse:
    """Read one bounded response, checking every redirect before dispatch.

    The total deadline includes redirects and streaming. Redirect bodies are not
    consumed. Compressed responses refuse before decoding, so the byte cap cannot
    be bypassed by decompression. No environment proxies, credentials, automatic
    redirects or retries are enabled. Cancellation propagates after closing the
    response and client. Optional transport injection supports offline tests.
    """
    selected = policy.validate_url(url)
    requested = str(selected)
    redirects: list[str] = []
    async with asyncio.timeout(policy.timeout_seconds):
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=policy.timeout_seconds,
            headers={"Accept-Encoding": "identity"},
        ) as client:
            while True:
                async with client.stream("GET", selected) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if len(redirects) >= policy.max_redirects:
                            raise FetchRefused("HTTPS response exceeded the redirect cap")
                        location = response.headers.get("location")
                        if not location:
                            raise FetchRefused("HTTPS redirect response has no Location")
                        selected = policy.validate_url(str(selected.join(location)))
                        redirects.append(str(selected))
                        continue
                    encoding = response.headers.get("content-encoding", "identity").lower()
                    if encoding != "identity":
                        raise FetchRefused(
                            "HTTPS response compression is outside the byte-bound contract"
                        )
                    declared = response.headers.get("content-length")
                    if declared is not None:
                        if not declared.isascii() or not declared.isdecimal():
                            raise FetchRefused(
                                "HTTPS response Content-Length must be an unsigned integer"
                            )
                        digits = declared.lstrip("0") or "0"
                        if (
                            len(digits) > len(str(policy.max_response_bytes))
                            or int(digits) > policy.max_response_bytes
                        ):
                            raise FetchRefused("HTTPS response exceeds the declared byte cap")
                    body = bytearray()
                    async for chunk in response.aiter_raw(chunk_size=16384):
                        if len(body) + len(chunk) > policy.max_response_bytes:
                            raise FetchRefused("HTTPS response exceeds the streamed byte cap")
                        body.extend(chunk)
                    if declared is not None and len(body) != int(declared.lstrip("0") or "0"):
                        raise FetchRefused("HTTPS response length differs from Content-Length")
                    return FetchResponse(
                        requested,
                        str(selected),
                        response.status_code,
                        response.headers.get("content-type", ""),
                        bytes(body),
                        tuple(redirects),
                    )
