# SDK readiness for the VFX runtime cutover

This is the scoped SDK acceptance checklist for replacing the Claude Agent SDK in VFX.
It is not a claim that VFX has migrated, that every possible SDK feature exists, or that
live-model visual quality is proven. Flynn provides generic execution; the harness owns
its tools, observations, prompts, authority and success criteria.

| SDK capability | Implemented contract | Verification |
|---|---|---|
| Native tool registration | ToolBroker, Tool.structured, explicit validators | Invalid arguments and ungranted calls cannot dispatch |
| Structured multimodal results | ToolResult, text/image references, immutable JSON data | Strict serialization and SQLite reopen round-trips |
| Dynamic permissions | Per-step grants and recorded DispatchGuard decisions | Missing/denied/error/cancelled guards refuse before tool reservation |
| Bounded sessions | Explicit SessionStep / SessionStop policy | No implicit retry, history accumulation or domain completion |
| Lifecycle and termination | Durable event notifications and SessionTermination | Callback failure, deadlines, cancellation, terminal re-entry refusal |
| Model access | InferenceAdapter plus native DeepSeek text/vision transport | Mock HTTP covers tool schema, selected images, usage and rejection |
| Usage and budgets | Neutral usage; call, tool, external-action, time and output-token limits | Rejected/unknown usage, reservation settlement and reopen tests |
| Bounded context | Required items, provenance, omission records; explicit preparation | Overflow refuses before inference; selected feedback is preserved |
| State and recovery | SQLite ownership, evaluated revisions and explicit recovery | Crash/uncertain-effect tests; no automatic external replay |
| Packaging | Private SSH main installation, base SDK without third-party dependencies | Wheel/source build and clean installed-package tests |

The combined readiness test exercises a native multimodal Session with mocked DeepSeek
HTTP, real SQLite accounting, narrowed grants, durable guards and structured observations.
It spends the exact output allowance, stops explicitly and leaves domain state unaccepted.
Only the provider HTTP boundary is mocked in that test; no Claude package or API is involved.

## Deliberate boundaries

- File/Blender tools, role loops, prompts, context relevance, asset access, sandboxing,
  validation rules and acceptance receipts are harness integrations, not missing SDK tools.
- Pricing and USD policy belong to the harness. Unknown costs must not be reported as zero.
- Input-token usage is measured but not capped: no verified pre-request bound exists for
  the current provider. Output caps depend on the trusted adapter/provider honoring them.
- Local POSIX ownership and cooperative async cancellation are the supported execution
  model. This is not distributed scheduling or a sandbox for untrusted Python.
- Image references are not fetched automatically. The harness selects and verifies images
  before constructing ImageInput. Broad provider support, token streaming, distributed jobs
  and automatic session resume are not prerequisites for the defined VFX cutover.
- Native tools take explicit schemas and pure application validators; the broker does not
  silently reinterpret JSON Schema or infer domain constraints from descriptions.

SDK scope is ready when the tests and both installed-consumer gates pass on the same pushed
revision. VFX migration remains separate work; it must exercise every role and independently
verify its receipts before removing the old runtime. Discovery of a concrete shared gap must
still produce an SDK test and mechanism rather than a prompt workaround.

## SDK verification checkpoint

The schema-5 implementation passes 151 tests in the checkout and the same 151 tests
against the built wheel in an isolated environment without Claude installed. Ruff,
formatting, mypy, wheel/source builds and the scripted durable-reopen example pass.
Consumer SSH refreshes are the final compatibility gate for this revision. No paid
inference or live-model quality claim is part of SDK completion.
