# Runtime and integration guide

This describes the unreleased, breaking 0.2 API. `Budget`, `InMemoryStore`, and
`SQLiteJournal` are removed. Schema-1 databases are refused; preserve them as historical
evidence and start fresh. No automatic conversion or compatibility adapter exists.

## One durable run

Create `SQLiteRun.create(path, run_id=..., initial_state=..., limits=RunLimits(...))`
and pass `run=run` to `Runtime`. The application owns its context-manager lifetime.
Creation refuses an existing path. `SQLiteRun.open(path)` acquires exclusive local
ownership and restores recorded state, observation, reservations and terminal outcome.
A live owner refuses a second writer, including another instance in the same process.
Forked children cannot mutate an inherited store. Read-only SQLite inspection is allowed.

The runtime persists the prepared request and inference reservation before inference;
it persists validated dispatch intent and tool/action reservations before execution.
Returned output is durable before evaluation. Evaluation and an optional accepted state
revision publish in one transaction. `Evaluation.state_update=None` records an assessment
without a commit. A satisfied evaluation with an explicit string publishes that string;
tool output is never implicitly state. Failed/unavailable evaluations retain the proposal
and observation without publishing it. Domain completion remains application-owned.

Mark environment tools `observation=True`; other tools cannot replace the latest environment
observation. `prepare_request` chooses the feedback and may narrow grants and schemas. The
runtime preserves that choice; it does not accumulate history into the next request.
Validators still enforce argument legality. Tools and evaluators are trusted application code.

## Interruption and budgets

`remaining()` derives inference/tool/external capacities from durable reservations. Failed
attempts consume reservations; reopening cannot reset them. Wall time includes downtime;
a backward clock refuses further work. Deadlines cancel cooperative async work, not blocking
code or external processes. Token/USD accounting and provider-neutral usage settlement are
not implemented by this store.

`pending()` distinguishes interrupted inference, proposal, dispatch and returned output.
Explicit `await runtime.recover()` abandons undispatched attempts without refund or re-evaluates
a recorded result without calling inference or a tool. A dispatched operation without a
result raises `UnresolvedEffect`. Recovery never repeats an uncertain operation. There is
no generic external-effect reconciler or environment restore. Applications must not use
this method to claim safe VFX session resume.

`finish(outcome)` records application-owned terminal text. A terminal run refuses steps
before preparation or spending, and refuses commits. Recorded late tool results remain
available as evidence. A terminal outcome does not clear an unresolved dispatch.
`records()` is a derived inspection export, never an import or second state authority.

SQLite uses local rollback journaling and `synchronous=FULL`, with short transactions;
no transaction spans inference or tool execution. Large artifacts remain external. Hashes
identify evaluations; they are not signatures or protection against a malicious database
writer. Filesystem/hardware durability assumptions are those of SQLite's
[atomic commit protocol](https://www.sqlite.org/atomiccommit.html).

## Bounded context

`ContextCompiler` selects whole items within a character budget. `ContextItem(required=True)`
is selected before optional priority items; if required content cannot fit, compilation fails.
The packet reports included, omitted and evidence IDs. The harness chooses relevance and
which inputs are required. This does not account for provider tokens or images.

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
