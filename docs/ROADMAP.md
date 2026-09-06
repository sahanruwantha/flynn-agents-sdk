# Coordinated roadmap

Status: planned, 2026-09-06. Milestones are dependency gates, not promised dates.

| Phase | SDK deliverable | ARC consumer deliverable | Exit evidence |
|---|---|---|---|
| 0 | Current design and supersession record | Scope, architecture, evaluation plan | Docs agree on ownership and implementation status |
| 1 | Rename distribution to flynn-agents-sdk and import to flynn_agents; contracts, scripted adapter, minimal kernel | Toy environment through public SDK interfaces | Install/import test; malformed call and budget refusals; one complete recorded episode |
| 2 | Durable events, evaluation records, revision checks, cancellation | Recorded observation/action history | Restart/crash fixtures; no duplicate unknown external action; stale evaluation refusal |
| 3 | Local inference adapter and tested program worker | Generic ARC adapter plus simple baseline | No-network end-to-end smoke run within explicit limits |
| 4 | Context/retrieval and frozen-input evaluation tools | Competing executable world models, counterexamples, experiment policy | Wrong model is rejected; revised model predicts withheld transitions |
| 5 | Stable extension surface and pinned SDK commit | Ablations and frozen held-out game evaluation | Same-model/same-budget comparison; failures and overhead included |
| 6 | Reproducible build and release notes | Competition packaging and eligible model | Official entrypoint rehearsal; rules and artifact audit; no unsupported score claim |

Do not wait for a large SDK to finish before using it: phases 1–4 each end in a consumer
that runs. ARC pins an exact SDK commit until a reproducible versioned release exists.
A cross-repository change lands SDK capability first, then the ARC pin and consumer.

## First implementation task

Migrate the version-only kusum scaffold and its test together, without preserving an
unneeded compatibility alias. Add pure call/result/budget contracts, a scripted model
adapter, and a kernel that performs one authorized tool call. Exercise it with a toy
consumer. No new model dependency is necessary for this task.

## Deferred

RL training, multi-agent role networks, fine-grained invalidation, durable distributed
jobs, broad provider support, and revival of the old SWE-bench causal study all require
separate evidence of need. Documentation is not evidence that any mechanism works.
