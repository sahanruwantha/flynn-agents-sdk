# Runtime and integration guide

## Recorded environment episodes

Pass `journal=SQLiteJournal(path, initial_observation=...)` to `Runtime`. Register environment
operations with `Tool(..., external_action=True, observation=True)`. All tool results are
recorded before evaluation; only observation tools update `InferenceRequest.observation`.
A failed prediction cannot erase a returned observation. `request.base` still refers to
accepted application state, so consumers must not mistake it for current environment state.

`Budget(..., external_actions=100, wall_time_seconds=60)` separately bounds external
attempts and total elapsed episode time, starting at budget construction. Failed attempts
consume capacity. Deadlines cancel cooperative async work; they cannot preempt blocking
Python or replace a confined worker. Token accounting is not implemented.

Use one journal and one action writer per episode. The application calls `journal.finish`
with its terminal outcome; the SDK does not certify completion. Reopen with `SQLiteJournal`
to inspect `entries()`, `latest_observation()`, `outcome()`, and `unresolved()`. A durable
intent without a result prevents further dispatch. There is no automatic action replay,
accepted-state restoration, budget restoration, or reconciliation API. A recorded evaluation
is not evidence that an in-memory commit happened. Choose a fresh path for each new episode.

The adjacent `arc-harness` checkout provides a three-action toy episode, including a failed
prediction that remains in recorded history. See its README for the runnable command.

## Bounded context selection

`ContextCompiler(max_characters=...)` selects whole `ContextItem` records by application
priority and returns a `ContextPacket` with included IDs, omitted IDs, and evidence IDs.
It never silently truncates an item. Character budgets are not token or image budgets.
ARC's episode memory uses this utility while owning all spatial representations, beliefs,
and retrieval relevance. The SDK does not assign domain meanings to remembered evidence.

DeepSeek traces include `rejection_reason`, `choice_count`, and `tool_call_count`
for response-contract failures. Invalid response bodies and argument strings are omitted;
reported usage is retained. These optional fields are additive to the trace format.
The adapter still performs one request per inference and requires exactly one permitted
JSON object tool call. Multiple calls are rejected together before dispatch.

DeepSeek documents `tool_choice="required"` as one or more calls:
https://api-docs.deepseek.com/api/create-chat-completion/.
The system instruction explicitly asks for one call and a wait for its result.
This is a prompt-level constraint, not a provider guarantee; no undocumented
`parallel_tool_calls` behavior is relied upon.

Tool validators now raise the distinct `ProposalRejected` contract error for malformed
arguments. Applications may request a bounded correction only after confirming no tool
intent was recorded. Budget exhaustion retains its own exception; execution and provider
errors are not classified as validation refusals. The ARC consumer records correction
requests and charges them to explicit inference and time limits.

DeepSeek `ProviderResponseRejected` (available from `flynn_agents_sdk.deepseek`)
distinguishes a received but malformed response from HTTP, transport, timeout,
cancellation, or request-configuration failures. It exposes `reason`, `choice_count`,
and `tool_call_count`; it remains a subclass of `ProviderError` for existing callers.
The adapter still performs one request and never executes or partially accepts calls.
Applications can choose a bounded correction policy; the exception does not authorize
replaying an external effect.

`Runtime.step(objective, grants=...)` can now narrow construction-time grants for one
step. Expansion is rejected before inference. `prepare_request` may narrow them further
but cannot restore removed grants; the broker enforces the same effective permissions
shown to inference. Overrides do not change later steps' construction-time authority.
