# DeepSeek adapter

Install the `deepseek` extra (`uv sync --extra deepseek`) and import
`DeepSeekAdapter` from `flynn_agents_sdk.deepseek`. Supply an API key explicitly and use
it as an async context manager. The provider does not load environment files or manage
an agent loop. The default model is `deepseek-v4-flash-vision-exp`.

```python
async with DeepSeekAdapter(api_key=key, max_tokens=512, timeout_seconds=45) as inference:
    # Pass inference to Runtime together with application tools and a journal.
    ...
```

`Tool.description` and `Tool.parameters_json` become explicit `ToolSpec` records in each
request. The broker still validates generated arguments before dispatch. A trusted
`Runtime(..., prepare_request=...)` callback can attach `ImageInput` records to the frozen
request; image URLs/data URLs are explicit and the provider never reads local files.
Only granted tool schemas are sent. Exactly one complete permitted JSON tool call is
accepted; truncation, multiple calls, malformed output, and provider errors stop the step.

The adapter sends directly to `https://api.deepseek.com/chat/completions` via HTTPX,
with thinking disabled, no streaming, redirects, or automatic retries. HTTP timeouts and
a total request deadline are enforced. `on_trace` receives response identity, finish reason,
selected call, elapsed time, and available token counts; missing usage stays unknown.
Trace callbacks are trusted synchronous sinks: a sink failure stops execution. Credentials,
raw provider error bodies, and reasoning content are not included in traces.


Model availability is provider-controlled. Configure the model explicitly for your account;
the experimental default is not a guarantee of ongoing availability.
