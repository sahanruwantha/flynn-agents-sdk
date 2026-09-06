# Research plan

Status: prospective. The previous coding-agent study is preserved in
[the archive](history/kusum/RESEARCH_PLAN.md); it is not the current implementation queue.

Question: can explicit observations, testable world models, selective context, and
counterexample-driven repair improve adaptation efficiency at a fixed model and budget?
ARC-specific score experiments belong to [ARC Harness](https://github.com/sahanruwantha/arc-harness).
SDK research measures overhead, valid and invalid transitions, replay fidelity, and the
ability to support those experiments without changing hidden runtime policy.

Separate two claims: the kernel correctly enforces a contract, and the contract improves
agent performance. Offline conformance tests address the first. Controlled game trials
address the second. A receipt is no guarantee that an inferred world model is correct.

Compare a simple agent with the full instrumented policy under the same inference model,
observations, action interface, and explicit limits. Ablate model verification, hypothesis
memory, targeted repair, and context selection individually. Distinguish a benefit from
extra tools from a benefit from how the loop uses them. Publish negative results and
latency/compute costs. Do not claim novelty without a separate prior-work comparison.

The architecture inherits principles from VFX Harness and Re-enactment Engine. Successful
production control does not establish general game reasoning. Local-model compatibility
and benchmark generalization both require fresh tests, not extrapolation from those repos.
