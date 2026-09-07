# Coordinated roadmap

Status: SDK runtime and ARC toy integration implemented; a partial phase-2 journal is
implemented. Hosted DeepSeek vision is implemented for development smoke tests; local inference and
official ARC integration remain planned.
Milestones are dependency gates, not promised dates.

| Phase | SDK deliverable | ARC consumer deliverable | Exit evidence |
|---|---|---|---|
| 0 | Current design and package scaffold | Scope, architecture, evaluation plan | Docs agree on ownership and implementation status; package installs |
| 1 | Contracts, scripted adapter, minimal kernel | Toy environment through public SDK interfaces | Install/import test; malformed call and budget refusals; one complete recorded episode |
| 2 | Durable events, evaluation records, revision checks, cancellation | Recorded observation/action history | Restart/crash fixtures; no duplicate unknown external action; stale evaluation refusal |
| 3 | Local inference adapter and tested program worker | Generic ARC adapter plus simple baseline | No-network end-to-end smoke run within explicit limits |
| 4 | Context/retrieval and frozen-input evaluation tools | Competing executable world models, counterexamples, experiment policy | Wrong model is rejected; revised model predicts withheld transitions |
| 5 | Stable extension surface and pinned SDK commit | Ablations and frozen held-out game evaluation | Same-model/same-budget comparison; failures and overhead included |
| 6 | Reproducible build and release notes | Competition packaging and eligible model | Official entrypoint rehearsal; rules and artifact audit; no unsupported score claim |

Do not wait for a large SDK to finish before using it: phases 1–4 each end in a consumer
that runs. ARC pins an exact SDK commit until a reproducible versioned release exists.
A cross-repository change lands SDK capability first, then the ARC pin and consumer.

## First implementation task

Implemented in the SDK: pure records and protocols, a scripted adapter, a sequential
async step, trusted tool grants/validation, attempt budgets, scoped evaluation, and
in-memory revision checks. `examples/scripted_task.py` is the runnable toy consumer.
Fault tests cover malformed/unauthorized calls, exhausted budgets, forged success text,
stale and mismatched evidence, and cancellation. Strict type checking accompanies the API.

ARC now includes a runnable three-action toy episode, failed-prediction preservation,
invalid-action and budget-stop cases. SQLite records can be reopened; a real subprocess
crash fixture checks that an unresolved action cannot be repeated. External action limits
and cooperative episode deadlines are implemented. Inference receives the latest explicitly
recorded observation independently of accepted state.

Phase 2 remains partial: accepted-state/commit recovery, durable budgets, full lifecycle
records, and environment-specific reconciliation are not implemented. The consumer uses
an editable sibling SDK dependency until these working-tree changes have a committed
revision to pin. Next: commit and pin the integration, then local inference and an official
environment baseline. Do not run generated model code before adding tested confinement.

## Deferred

RL training, multi-agent role networks, fine-grained invalidation, durable distributed
jobs, broad provider support, and coding-benchmark studies all require
separate evidence of need. Documentation is not evidence that any mechanism works.
