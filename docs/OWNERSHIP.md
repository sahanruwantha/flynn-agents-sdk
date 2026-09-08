# SDK and harness change ownership

The SDK owns reusable execution mechanisms. The harness owns what an ARC agent learns,
what it tries next, and what counts as progress. A disappointing ARC score is evidence
to investigate, not by itself evidence that the SDK needs a new feature.

## Decide before implementation

1. State the observed failure and the invariant or behavior that should change.
2. Does the fix need pixels, game actions, object identities, goal hypotheses, or ARC
   scoring? It belongs in the harness.
3. Does it enforce a domain-independent execution contract, transport model requests,
   account for operations, or preserve evidence? It belongs in the SDK.
4. Does it contain both? Split the generic mechanism from the application policy, with
   an explicit interface between them. "Both" is not permission to duplicate ownership.
5. If it is only hypothetically reusable, keep it in the harness until another concrete
   consumer or a clear execution invariant justifies an SDK abstraction.

An SDK feature must be explainable and testable with a non-ARC fixture.
Dependencies point from the harness to the SDK. SDK production modules must not import
arc_harness, arc_agi, or arcengine. The architecture test enforces that import boundary;
it does not replace semantic review.

## Responsibility map

| Concern | SDK mechanism | Harness policy or semantics |
|---|---|---|
| Model access | DeepSeek transport, tool-call envelope, safe diagnostics, usage traces | Model selection, task prompts, image preparation |
| Tools | Registration, grants, calling validators before dispatch | Legal ARC actions, coordinates, prediction schema, hypothesis/plan tools |
| Validation repair | Distinct pre-dispatch ProposalRejected error; inference/time accounting | Whether to request correction, repair limit, feedback wording, rejection artifacts |
| Budgets | Reserve inference/tool/external-action capacity; cooperative deadline | Episode limits; interpreting a visual meter as a possible resource |
| Evidence | Intent/result/evaluation journal, identities, unresolved-effect stop | Frames, spatial features, observed transitions, domain memory revisions |
| Evaluation | Bind an evaluation to its candidate; enforce commit preconditions | Pixel prediction checks, world-model tests, official completion and score |
| Context | Whole-item character budget, priorities supplied by caller, omission records | What to recall, priorities, maps, prose truncation, provenance presentation |
| Planning | Execute only the submitted authorized call | Route search, plan cursor, expected positions, invalidation conditions |
| Learning | Generic records/contracts only where needed | Conditional rules, perception, goal inference, counterexamples, model revision |
| Recovery | Preserve uncertainty; never silently repeat an unknown effect | Environment-specific reconciliation, if authoritative evidence supports it |

The broker invokes application validators; it does not currently implement generic
JSON Schema validation. The SDK context compiler is not a domain retrieval engine.
SQLiteRun restores recorded accepted state and reservations; it does not restore an environment.

## Classification of changes already made

| Change | Owner | Why |
|---|---|---|
| DeepSeek rejection reason and call counts | SDK | Provider contract, independent of ARC |
| Preserve BudgetExhausted through tool validation | SDK | Execution accounting must retain its error type |
| Typed ProviderResponseRejected with structural diagnostics | SDK | A received response violates the provider contract before a call is returned |
| Introduce ProposalRejected | SDK | Distinguishes validation refusal from execution failure |
| Three correction turns with unchanged observation | Harness | Application chooses recovery policy using SDK evidence and budgets |
| Long summary/claim handling and bounded recall | Harness | Domain tool payload and prompt policy |
| Destination composition, floor fit, spatial map | Harness | Interpret pixels and game transitions |
| Plan cursor and expected-position checks | Harness | Depend on the inferred motion model |
| Shrinking-bar resource hypothesis | Harness | Interprets environment observations |
| Exact versus projected state identity | Harness | Depends on task-relevant visual features |
| Generic immutable evidence identity | SDK | Must hold for every consumer |

## Change record for every substantive improvement

Include this short record in the issue or PR; the PR template prompts for it:

- **Failure/evidence:** artifact, test, or reproducible trigger.
- **Owner:** SDK, harness, or split.
- **Boundary rationale:** one sentence naming the mechanism or domain semantics.
- **Changes by repository:** for split work, identify the interface and avoid duplicate logic.
- **Validation:** SDK invariant tests, harness behavior tests, and integration evidence as needed.
- **Success criterion:** measurable behavior; distinguish reliability from score improvement.

For example: "A malformed prediction terminates the episode. Split: SDK exposes a
pre-dispatch refusal; harness requests at most three corrected proposals. Tests prove
no rejected action executes, corrections consume inference capacity, and an uncertain
external effect is never retried."

## Candidate improvements after the latest spatial run

| Improvement | Owner | Required evidence |
|---|---|---|
| Revise floor-only rules after a successful mixed-tile probe | Harness | Retained observations plus a revised rule predicting a new transition |
| Avoid repeated probes that cannot distinguish current hypotheses | Harness | Recorded action choices and fewer redundant probes at equal budget |
| Infer and test goal or interaction hypotheses | Harness | Explicit experiment and environment feedback; not movement accuracy alone |
| Retrieve provisional knowledge across eligible episodes | Harness first | Isolated evaluation protocol and measured transfer without leakage |
| Durable recovery of generic runtime state/budgets | SDK | Crash/restart invariants independent of ARC, plus consumer reconciliation |
| Confine generated model programs | Split | SDK confinement mechanism; harness model language and semantic tests |

These are classifications, not claims that the deferred capabilities are implemented.

Implemented boundary example: Runtime.step's optional grants override and enforcement
of further prepare_request narrowing belong to the SDK. Decisions about when to narrow
tools remain harness policy. The harness currently uses informative reassessment rather
than mandatory deliberation gating.

## Neutral inference accounting (schema 3)

- **Failure/evidence:** ARC calculated usage from DeepSeek callbacks; VFX's Flynn
  path had no usage report. SQLite inference reservations could not distinguish
  scripted canonical replay from a model request, and rejected responses lost usage.
- **Owner:** SDK records accounting; harnesses select models, prices, budgets and
  domain completion. This change adds no token limit or dollar-cost claim.
- **Contract:** adapters return `InferenceResult(call, usage)`. `InferenceUsage`
  separates model/scripted kind from known/unknown/not-applicable usage, includes
  provider/model and response/finish identity, and preserves partial token counts.
  `model` is requested identity; `response_model` is provider-reported identity,
  independently nullable. Missing response identity never falls back to the request.
  Identity matching and judge qualification are harness policy. The optional field
  lives in the existing immutable usage JSON; absent historical fields remain unknown.
  `InferenceFailure` and `InferenceCancelled` carry reports for failed invocations.
  A missing report remains unreported, including process death and historical runs.
  Raw response retention stays in the provider's opt-in diagnostics.
- **Durability:** Runtime appends accounting before validating the proposed tool.
  Schema 3 adds immutable `inference_usage` rows keyed by operation id without
  changing existing tables. `SQLiteRun.inspect` reads schema 2 and 3 without writes;
  `SQLiteRun.open` accepts only schema 3. Historical inspection is not resume authority.
- **Consumers:** ARC episode summaries use journal usage, retaining provider traces
  for diagnostics/replay. Direct experiment callers unwrap `.call`. VFX publishes
  an attempt-scoped usage projection and keeps its receipt writers authoritative.
- **Validation:** generic fixtures cover rejection, timeout, cancellation, partial
  usage, scripted calls, unreported operations and immutable history. A SQL golden
  generated from the released schema-2 implementation proves historical evidence
  remains readable byte-for-byte without authorizing execution. Both consumers must
  pass their offline gates against the pushed SDK before handoff.
- **Success criterion:** accounting survives failed proposals and reopened runs;
  scripted operations never inflate unknown model usage. No ARC-score or VFX-quality
  improvement is inferred from accounting alone.

## Output-token admission (schema 4)

- **Failure/evidence:** usage records alone could not stop a new request or bound its
  output. A successful diagnostic followed by an uncertain model response must not
  reset spending capacity or prevent separately authorized deterministic work.
- **Owner:** SDK reserves and enforces output ceilings; harnesses choose whether to
  enable a cap, its value, and domain continuation. Input usage remains accounting
  only: no verified pre-request input-token bound is available here. Prices and
  dollar settlement remain out of scope.
- **Contract:** `RunLimits.output_tokens` is optional. A capped runtime requires
  `plan_output(request, available)` to produce an `OutputReservation` without I/O.
  DeepSeek reserves at most its configured maximum and the remaining cap, then
  sends the durable request ceiling as `max_tokens`. Scripted inference reserves zero.
- **Durability:** schema 4 adds immutable `output_reservations`, inserted atomically
  with the operation and inference reservation before generate. Known output counts
  settle the hold; unknown/unreported output retains it and blocks new model calls.
  Missing input usage does not erase a known output count. Breaches retain the actual
  report, refuse tool dispatch, and block subsequent model calls. Enforcement relies
  on the trusted adapter/provider honoring its declared bound; a provider violation
  cannot be undone or represented as staying within budget.
- **Consumers:** ARC exposes `--output-tokens` and reports the derived budget. VFX
  accepts the same limit through its existing opt-in engine, publishes a v2 usage
  projection and proves canonical scripted replay after output exhaustion. None of
  these records changes accepted state, receipt authority or domain success.
- **Validation:** offline HTTP, failed response, partial usage, process-death,
  reservation immutability and historical schema-3 golden tests; both SSH consumer
  gates. Schema 2 and 3 are audit-readable; only schema 4 authorizes execution.
- **Success criterion:** refusal before another model request, durable uncertainty,
  and exact consumed/held/available counts after reopen. No input or USD cap claimed.

## Inference configuration admission

`ConfiguredInference.configuration(request)` is an optional read-only capability
returning immutable `InferenceConfiguration(provider, model, protocol, settings_json)`.
Its canonical SHA-256 covers effective model settings, including DeepSeek's system
instruction, thinking/effort, tool-choice mode and output ceiling. Request evidence and
tool definitions remain in the SDK request, outside this settings description; the
harness must bind those separately. Credentials never enter the description.

`InferenceUsage.configuration_sha256` independently retains the fingerprint derived
from the actual dispatched payload, including rejection, timeout and cancellation.
Absent historical/unreported metadata stays unknown; scripted usage cannot claim it.
The field lives in existing immutable usage JSON and changes no tables or historical
bytes. A preflight description is not proof of dispatch, domain qualification or
acceptance. Harness policy compares the selected configuration to actual usage.
