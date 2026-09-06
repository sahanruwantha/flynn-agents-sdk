# SDK interface design

Status: proposed contract sketch. These names are not a released API.

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
