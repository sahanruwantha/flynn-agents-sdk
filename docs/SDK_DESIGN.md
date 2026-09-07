# SDK interface design

Historical design checkpoint: implementation descriptions below refer to 0.1. The breaking
0.2 SQLite contracts and current limitations are in [the runtime guide](guides/runtime.md).

Status: experimental first slice plus proposed broader contracts; not a stable API.

## Implemented slice

`Runtime.step(objective)` performs one sequential async operation. `InferenceAdapter`
returns a `ToolCall`; a `ToolBroker` checks explicit grants, registration, and an
application-supplied argument validator before execution. Payloads are immutable strings;
the application defines their format. There is no generic JSON Schema implementation.
`Evaluator` returns an `Evaluation` binding the complete frozen candidate, including
base state, tool call, and output. `InMemoryStore.commit` checks that binding, a satisfied
verdict, and the unchanged base before publishing the next revision without await points.

`Budget` bounds inference/tool attempts. Reservations consume one unit permanently,
including on failed or cancelled dispatch. External action attempts can have a separate limit. An optional monotonic wall-time
budget cancels cooperative async steps. Token settlement and monetary accounting remain deferred. `Runtime.events` is a process-local diagnostic
snapshot, not durable evidence. `StepResult` retains the candidate and evaluation.
Failures propagate after recording a diagnostic; tool exceptions and cancellation during
dispatch mark the effect unknown and never trigger an automatic retry. The optional `Journal` independently records intent/result/evaluation and supplies the
latest explicit observation to inference. `SQLiteJournal` blocks unresolved actions after
reopening, but does not recover accepted state or replay actions. Failed/unavailable evaluations return an uncommitted result.

Interfaces are async for waiting and cancellation, but execution is sequential. A runtime
serializes its steps; stores reject stale commits across runtimes sharing the same event
loop. No thread/process concurrency guarantee is made. The SQLite journal uses schema version 1 and serializes exact evaluation inputs as JSON.
It is not the complete portable record format below; canonical hashing and migrations
remain design requirements.


## Minimum interfaces

| Interface | Input and output | Contract |
|---|---|---|
| InferenceAdapter.generate | Explicit request → response with usage and stop reason | No tools, hidden retries, or session memory inside adapter |
| ToolBroker.execute | Validated call + grants → result/effect record | Reject unknown tools and invalid arguments before dispatch |
| ContextCompiler.compile | Task + selected revision + retrieval budget → packet | Include provenance; disclose omitted or truncated material |
| Evaluator.evaluate | Frozen candidate + exact evidence → scoped evaluation | Model verdict alone cannot establish a mechanical pass |
| StateStore.commit | Expected revision + output + evaluations → revision | Atomic compare-and-publish; refuse stale base |
| Budget.reserve/settle | Operation estimate → reservation → observed usage | Include failed operations; report unknown usage explicitly |

Requests name model/weights, generation settings, input messages, response schema,
allowed tools, and limits. Responses preserve available raw payload, normalized content,
finish reason, usage, and provider identity. Lack of a provider fingerprint is recorded
as unavailable, not synthesized. Never require disclosure of private chain of thought;
record available outputs and explicit decision summaries.

## Records

Every durable record has a schema version and explicit identity. Proposed families:
TaskSpec, ModelRequest, ModelResponse, ToolCall, ToolResult, ObservationRef,
CandidateRevision, EvaluationRecord, CommitRecord, StopRecord, RunManifest.
The application supplies domain payload schemas. JSON canonicalization and digest rules
must be pinned with golden fixtures, including previous-generation read behavior.
A changed required contract requires explicit migration or refusal.

Evaluation decisions should distinguish satisfied, failed, and unavailable checks.
Run endings distinguish completion established by the application, exhausted budget,
cancellation, invalid proposal, execution failure, and unresolved external effect.
Do not promote a schema-valid proposal into an accepted result.

## Budget and recovery

The run configuration separately bounds model tokens, wall time, tool executions,
worker CPU/memory, and application-defined external actions. Dollar accounting is
optional for local inference; unavailable costs are not zero costs. Reserve capacity
before dispatch and settle actual usage afterward. Exhaustion is a recorded outcome.

Read-only transport retries are bounded and explicit. Mutating calls need adapter-proven
idempotency or reconciliation. Journal intent before dispatch and result after return;
a death between them remains unresolved until evidence closes the gap.

## First executable example

Build a deterministic toy environment and scripted inference adapter. Observe a state,
propose a typed action, execute it, capture the result, and evaluate the proposed output.
Inject a stale revision, forged success string, malformed call, exhausted budget, and
interruption around dispatch. This example must run without a paid model or ARC download.
Next, wire a local model and use exactly the same kernel interfaces.

## Extension discipline

ARC registers observations, game actions, model-checking tools, and completion reading.
No game-specific record is added to SDK core for convenience. A second tiny non-ARC
consumer must work before calling the API reusable. Prefer one tested extension point
over speculative adapters for every model provider.

## Direct provider implementation

DeepSeekAdapter implements the existing one-call InferenceAdapter protocol using optional
HTTPX transport. InferenceRequest now includes immutable tool specifications and explicit
image inputs. Runtime can call a trusted prepare_request function to attach application
context. Token usage and finish metadata are available through an explicit on_trace sink;
they are not yet part of budget settlement or the SQLite journal. The ARC consumer saves
these traces separately. Hosted inference is a development path; local inference remains
pending. No provider session, hidden tools, or automatic retries are introduced.
