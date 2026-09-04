# Decision Log

Append-only. A later decision may supersede an earlier one but must not delete it. No
entry reports an experimental result.

## D-001 — Name and scope

- Date: 2026-09-04
- Status: accepted
- Decision: the project is named **kusum** (chosen by the author). It is a coding-agent
  harness built from scratch; it does not reuse the VFX harness code, only the mechanism
  that harness converged on.
- Alternatives considered: extend the VFX harness to coding tasks.
- Rationale: the VFX harness is specialized for Blender (workers, image metrics, judge
  panels). A direct comparison with Claude Code and OpenHands needs the same tasks and
  universal verifiers, and the transplant to an unmotivating domain is itself the test.
- Consequence: no import of `vfx_harness`; the improvement records there are reference
  material, cited by id.

## D-002 — Stack

- Date: 2026-09-04
- Status: accepted
- Decision: Python 3.11; Claude Agent SDK pinned at `0.2.149` for the treatment arm's
  model transport; Docker for task environments using SWE-bench images (`swebench 5.0.2`
  tooling); `uv` for environments; `pytest` and `ruff`.
- Alternatives considered: a direct-API loop without the SDK; a TypeScript harness.
- Rationale: the SDK gives typed messages, hooks, tool policy, and usage reporting the
  harness depends on; Evidence Debt's provider matrix already names the SDK arm and a
  direct-API transport-sensitivity arm, which this stack can add later.
- Consequence: upgrades to the SDK, CLI baseline, or images create a new experiment id;
  nothing is pooled across pins.

## D-003 — Truth comes from hidden tests, warrant from the frozen rule

- Date: 2026-09-04
- Status: accepted
- Decision: candidate truth `T(o,g)` is scored only by the sealed SWE-bench
  `FAIL_TO_PASS` and `PASS_TO_PASS` sets (or the private corpus's sealed tests).
  Procedural warrant `W` is scored only by the frozen warrant rule over the presented
  evidence. Neither axis is ever derived from the other or from agent output.
- Alternatives considered: human adjudication of truth; agent self-report.
- Rationale: this is the property the first domain lacked. It removes the single-coder
  constraint for truth and makes `USR` measurable per run.
- Consequence: no arm may see hidden tests; a leak invalidates the run and is recorded.

## D-004 — Baselines and control

- Date: 2026-09-04
- Status: accepted
- Decision: baselines are Claude Code (pinned CLI) and OpenHands (pinned release). The
  control arm is kusum with its verifiers exposed as plain tools and no receipts, so
  instrument availability is separated from acceptance authority.
- Alternatives considered: a single baseline; a prompt-only "be careful" control.
- Rationale: RQ1 asks about the mechanism, not about having more tools.
- Consequence: baseline adapters emit the common event stream and never share a process
  with kusum; each is pinned per experiment.

## D-005 — No threshold is chosen in the plan

- Date: 2026-09-04
- Status: accepted
- Decision: practical-minimum effect, non-inferiority margin, abstention caps, and
  budget caps are set from the M4 pilot on disjoint instances and frozen in
  `PROTOCOL.md` before M5 runs.
- Rationale: Evidence Debt's guardrail rule; a threshold chosen after seeing confirmatory
  data is not a threshold.
- Consequence: M5 cannot start before the protocol digest is committed.

## D-006 — Licence

- Date: 2026-09-04
- Status: accepted
- Decision: Apache-2.0, matching Evidence Debt's choice for its explicit patent grant.
- Consequence: third-party material redistributed in derived form must be attributed in
  a `NOTICE` file before release; the repository is private until then.
