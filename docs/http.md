# Bounded HTTPS reads

The optional `http` extra provides `flynn_agents_sdk.http`. The base SDK remains
standard-library-only; DeepSeek users already have the same HTTP dependency.

```python
from flynn_agents_sdk.http import FetchPolicy, fetch_https

policy = FetchPolicy(
    allowed_origins=("https://docs.example.org",),
    max_response_bytes=131072,
    timeout_seconds=10,
    max_redirects=2,
)
response = await fetch_https("https://docs.example.org/api", policy=policy)
```

The caller selects exact permitted HTTPS origins and finite response, deadline and
redirect limits. Every redirect is checked before dispatch. Origin matching includes
the effective port; substrings, credential-bearing URLs, fragments, whitespace and
control characters do not extend the policy. The total deadline covers all redirects
and streaming. No environment proxies, automatic redirects or retries are enabled.

Responses request identity encoding and refuse compressed bodies before decoding.
The transport checks declared and streamed size, returns no partial body after a
refusal, and preserves exact returned bytes with a SHA-256 digest. `FetchResponse`
also carries requested/final URL, status code, content type and redirect destinations.
A non-redirect HTTP error status is returned for the caller to interpret. Network
errors, total deadline expiry and cancellation propagate; resources close on unwind.
`FetchRefused` identifies a request or response outside the supplied policy.

Register the fetch inside an ordinary `Tool.structured(..., external_action=True)`.
Call `policy.validate_url` from that tool's pure argument validator, as well as using
the transport's own validation. Reuse caller-supplied dispatch guards. Flynn then
reserves the operation and retains observations or uncertain failures in SQLite.
Do not retry an unresolved operation or equate a fetched page with accepted state.

The harness owns source selection, any tighter path/query rules, text extraction,
artifact retention, context selection and domain evaluation. Retrieved content is
reference data, not instructions granting permissions. The transport does not turn
HTML into a model prompt, summarize it, choose which page to fetch, or certify its
claims. The integration tests demonstrate successful and refused observations,
pre-dispatch URL rejection, and interrupted/failed reads without state commits.

`transport=` supports an `httpx.AsyncBaseTransport` for offline tests. The fetch owns
and closes its client and supplied transport for that call; provide a fresh transport
when its implementation cannot be reused after closing.
