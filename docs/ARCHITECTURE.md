# Runtime architecture

Status: mixed implementation and target design. The first slice implements async,
sequential execution, scripted inference, trusted tool validation, operation budgets,
scoped evaluation binding, in-memory revision checks, SQLite action/result/evaluation
records, external action limits, and cooperative deadlines. Full durable event replay,
accepted-state recovery, retrieval, local model transport, and confinement remain proposed.

The current threat model treats inference proposals as untrusted data and the kernel,
registered tools, evaluators, and storage implementation as trusted code in one event
loop. The store is not thread-safe or a security boundary against in-process Python.
Generated programs must not run until an isolation backend is implemented and tested.

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
  → commit matching output / return typed finding / stop
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

Implemented: the optional SQLite journal commits intent before dispatch, result before
assessment, and the exact bound evaluation before state publication. Results survive
rejected predictions and evaluator exceptions. Observation-producing tools explicitly opt
in; internal tool results cannot replace the latest environment observation. Reopening
an unfinished dispatch blocks new actions. An application-recorded terminal outcome closes
the journal to dispatch. Journal schema 1 rejects unsupported versions. SQLite connections
are owned by the composing application; the runtime does not close them.

The journal does not persist accepted-state commits, remaining budgets, inference requests,
or a complete event trace. It supports evidence inspection and conservative stopping, not
resuming an environment or proving exactly-once effects. A single application writer must
own the episode, including interpretation and evaluation. The following broader design
remains a target:

An append-only event stream records attempted operations and their outcomes. Selected
state points to immutable records. A commit requires the expected base revision and
matching evaluation inputs. Reject stale bases; never silently rebase accepted work.
Start with complete relevant-input binding and broad invalidation. Narrow dependency
invalidation only once all actual reads are captured and tested.

Replay means reconstructing decisions from recorded inputs and outputs. It does not
promise identical fresh model sampling or arbitrary rollback of an external environment.
An interrupted environment action may have happened without an observed response.
Mark that effect unknown; reconcile only if the adapter can prove the outcome. Do not
repeat a move automatically because a request timed out.

## Isolation

Generated programs run behind a broker in an isolated worker with explicit resource and
filesystem grants. The model never receives evaluator-private files, credentials, or
unrestricted host execution. Network is disabled in competition mode. A claimed
confinement backend needs negative tests before it is considered supported.

## Proposed package layout

The package root is `src/flynn_agents_sdk/`. Start with cohesive modules
for contracts, runtime, inference, tools, context, events, evaluation, and isolation;
introduce subpackages only when responsibilities justify them. Pure contracts cannot
import filesystem adapters, model providers, or ARC code. There is no need for a graph
database, distributed scheduler, plugin marketplace, or general multi-agent framework
before the first measured consumer works.

See [Project structure](PROJECT_STRUCTURE.md) for the proposed tree and import boundaries.
