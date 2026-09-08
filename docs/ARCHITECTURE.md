# Runtime architecture

Status: the unreleased 0.2 kernel uses a single SQLite run for state, requests,
reservations, effects and evaluations. See the [runtime guide](guides/runtime.md) for
implemented behavior and limitations. External environment restoration and usage settlement
remain application responsibilities. Generated Python has a separate opt-in
[confined worker](guides/program-worker.md); it does not change ordinary tool execution.

The current threat model treats inference proposals as untrusted data and the kernel,
registered tools, evaluators, and storage implementation as trusted code in one event
loop. The store is not thread-safe or a security boundary against in-process Python.
Generated programs must use the tested confinement backend, never an ordinary in-process tool.

See [change ownership](OWNERSHIP.md) for the implementation decision checklist,
responsibility map, and classification of recent improvements.

## Boundary

The SDK schedules explicit inference and tool operations over versioned task state.
Applications own domain semantics, objectives, admissible evidence, and evaluators.
Dependencies point from applications to the SDK, never back into application code.

| SDK owns | Application owns |
|---|---|
| Inference request/response contract | Choice of model and task-specific prompts |
| Validator invocation and scoped dispatch | Domain tools and legal action meanings |
| Durable events and output identity | Observations, hypotheses, and goal semantics |
| Evaluation transport and commit preconditions | What a particular evaluator can establish |
| Context limits, retrieval transport, budgets | Relevance policy and experiment selection |
| Cancellation and external-effect accounting | Whether an environment supports reconciliation |

## Small kernel, explicit policy

One orchestrator serializes authoritative state updates. It compiles context, reserves
budget, calls an inference adapter, validates proposals, dispatches permitted tools,
and records results. Independent read-only evaluations may eventually run concurrently
against the same frozen inputs. Parallel model roles are not required for the first slice.

A policy chooses the next operation; the kernel enforces its legality. Swapping policy
must not swap evidence readers, accounting, or evaluator implementations implicitly.
Model adapters cannot run tools or declare a task successful.

```text
Task + policy + selected state
  → compile context → reserve budget → inference → validate proposal
  → authorized tool execution → capture result → application evaluation
  → publish explicit state update / retain observation / stop
```

## Authority and uncertainty

Store raw tool/environment observations separately from inferred interpretations.
Applications may maintain competing hypotheses. A hypothesis consistent with the observed
history is useful for planning but has no authority over unseen transitions. Unknowns
can authorize budgeted probes; they cannot justify calling an unevaluated output passed.

Use scoped evaluation records: input identities, evaluator/version/configuration,
observations, decision, and limitations. Hashes bind bytes; they do not prove semantic
truth or prevent forgery by a writer who can replace both content and hashes. Trusted
publication requires an actual process/filesystem boundary, not a private constructor.

## Durability and replay

`SQLiteRun` is required by the default composition. An exclusive local owner spans awaits;
short transactions reserve work before execution and atomically publish the bound evaluation
with an optional accepted state revision. Reopening restores recorded state and operation
budgets. Explicit recovery can re-evaluate returned evidence, never replay an unknown effect.
Schema 1 is rejected. This is not VFX authority, scene reconstruction or domain acceptance.

A satisfied observation does not imply a state change. The application evaluator supplies an
explicit state update or none. The application alone declares domain completion. The SDK
cannot make filesystem artifact publication atomic with its own database transaction.

## Isolation

The opt-in `ProgramWorker` runs generated Python in an isolated subprocess with a fixed
read-only runtime and per-call limits. Network is always denied. Applications expose it
through their broker and own recording and verification; there is no automatic integration
with `Runtime`. The model receives no evaluator-private files or credentials. See the
worker guide for supported platforms, negative tests, and the shared-kernel boundary.

## Proposed package layout

The package root is `src/flynn_agents_sdk/`. Start with cohesive modules
for contracts, runtime, inference, tools, context, events, evaluation, and isolation;
introduce subpackages only when responsibilities justify them. Pure contracts cannot
import filesystem adapters, model providers, or ARC code. There is no need for a graph
database, distributed scheduler, plugin marketplace, or general multi-agent framework
before the first measured consumer works.

See [Project structure](PROJECT_STRUCTURE.md) for the proposed tree and import boundaries.
