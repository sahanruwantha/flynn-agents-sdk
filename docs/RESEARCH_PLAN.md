# Research Plan

**Version:** `0.1.0` · 2026-09-04 · status: planning, nothing registered, nothing run.

## 1. The question

Does a harness in which nothing self-certifies reduce **unsupported success** in
coding agents, at preserved completion and acceptable cost, compared with the harnesses
practitioners use today?

Unsupported success is the outcome Evidence Debt defines and has never been able to
measure causally (`../evidence-debt/docs/REAL_WORLD_IMPACT_PLAN.md`, "Outcomes and
estimands"):

```text
USR = 1 if the system emits run success while
      procedural warrant is independently invalid
      or mandatory-obligation completeness is independently known incomplete;
      0 otherwise.

Impact = Pr(USR=1 | control) - Pr(USR=1 | treatment)
```

The first domain (a Blender production harness) had no ground-truth oracle, so truth and
warrant could not be separated on real runs, and the causal core of that study has never
begun. Coding tasks change that: hidden tests are an oracle for **truth** `T(o,g)` that is
independent of any **warrant** rule `W(B,o,g,p,t)`. Every run can therefore be scored on
both axes without a human coder, which removes the one-coder constraint that blocks the
first domain (`RESEARCH_PLAN.md` there, "Three binding constraints").

## 2. Thesis and the mechanism under test

The agent's "done" is never authority. Acceptance is a typed receipt derived from
independent verifiers bound by content digest to the task, the repository snapshot, and
the change. The mechanism is the conjunction the VFX harness converged on over 190
improvement records, transplanted to a domain that did not motivate it:

| element | in kusum |
|---|---|
| nothing self-certifies | receipts come only from verifiers; agent verdicts are recorded and ignored |
| content-addressed authority | task, judging tests, repo state, and change as digested capsules; computed invalidation closure |
| bounded units | a change set declares files, symbols, and judging tests; context compiled per unit |
| typed rejection | every refusal: contract, expected vs found, legal next actions, at the earliest boundary |
| typed abstention | `cannot_satisfy_in_scope` with contradiction evidence opens a replan, never another guess |
| earned judgment | rubric review only where executable evidence cannot decide, blocking only once qualified |
| improvement lifecycle | every failure becomes a mechanism with a test that fails without it |

## 3. Research questions

- **RQ1 (safety).** At preserved completion, does kusum emit fewer unsupported successes
  than Claude Code and OpenHands on the same tasks, model, and budgets?
- **RQ2 (utility).** What does the safety gain cost: completion, turns, tokens, dollars,
  wall time, abstention, valid-work rejection?
- **RQ3 (abstention).** When a specification is unsatisfiable by construction, does kusum
  abstain with the right contradiction, and how often do the baselines "succeed" instead?
- **RQ4 (reuse).** Does obligation-relative invalidation (re-verify only what a change
  touched) preserve safety while cutting re-verification cost, relative to whole-state
  digests and declared-dependency slices? (Evidence Debt ED-C005, first live test.)
- **RQ5 (training signal).** Do typed rejection traces plus receipts form a reward
  machine that is denser and less gameable than pass/fail, measured by whether an agent
  trained or prompted on them improves RQ1 without degrading RQ2? (exploratory; not in
  the registered study)

## 4. Hypotheses

Each is falsifiable and carries a claim id in `CLAIMS.md`. Numeric thresholds are **not**
set here; they are set from disjoint pilot data before registration (Evidence Debt
"Required guardrails": do not invent the values in the plan).

- **KS-H1.** `Pr(USR | kusum) < Pr(USR | baseline)` by more than the frozen practical
  minimum, with completion non-inferior within the frozen margin.
  *Falsifier:* interval includes effects below the minimum, or completion fails
  non-inferiority, or the gain vanishes when baselines are given the same verifier
  outputs as plain tool results (the "verifier access" control).
- **KS-H2.** Self-certification ratio (agent claims done ∧ hidden tests fail) is lower
  under kusum than under baselines *at equal true completion*.
  *Falsifier:* the ratio is not lower, or is lower only because completion dropped.
- **KS-H3.** On injected unsatisfiable specifications, kusum's abstention precision and
  recall both exceed the frozen thresholds and the baselines' "success" rate on the same
  items is non-zero.
  *Falsifier:* kusum abstains on satisfiable items at a rate above the cap, or fails to
  abstain on unsatisfiable ones, or baselines also abstain.
- **KS-H4.** Guess-loop length (consecutive edits with no new verifier evidence between
  them) is shorter under typed rejections than under free-form error text, at equal
  completion.
  *Falsifier:* no difference, or difference explained by turn budget alone.
- **KS-H5.** Obligation-relative invalidation matches whole-state binding on unsafe reuse
  (non-inferiority) with lower re-verification cost.
  *Falsifier:* any under-invalidation that whole-state binding catches, or no cost
  reduction.

## 5. Design

### Tasks

- **Primary corpus:** SWE-bench Verified, a frozen, seeded subset (pilot 10, registered
  study 50, replication 50 disjoint). Instance ids, image digests, and `FAIL_TO_PASS` /
  `PASS_TO_PASS` sets are sealed before any arm runs.
- **Injected unsatisfiable specifications:** for a frozen fraction of instances, the
  task statement is edited so that the hidden tests and the statement contradict
  (a required behaviour the tests forbid). The correct outcome is typed abstention naming
  the contradiction. Edits are authored before arm assignment and sealed.
- **Truth-preserving evidence substitutions (ED-C007):** paired candidates with identical
  patches but altered presented evidence (stale test log, cherry-picked subset, forged
  summary). The correct decision is unchanged truth with changed admissibility.
- **Contamination guard:** SWE-bench Verified is public; report per-instance repository
  creation dates against the model's training cutoff and analyse the pre/post split
  separately. A second, private task set (tasks authored from this repository's own
  history after the model cutoff) is the replication corpus.

### Arms

| arm | role | pinned |
|---|---|---|
| kusum | treatment | this repository at a tagged commit |
| Claude Code | baseline B1 (practitioner default) | CLI version, settings, tool set |
| OpenHands | baseline B2 (open harness) | release tag, image digest |
| kusum with verifiers exposed as plain tools, no receipts | control C1 | isolates "instruments" from "acceptance authority" |

Same model, same generation options, same turn/token/dollar budgets, same sandbox
(non-root, no ambient network, copy-on-write workspace) for every arm. Arms never share a
process, and no arm sees hidden tests.

### Outcomes

- **Confirmatory:** `USR` per assigned run, scored by the sealed hidden tests (truth) and
  the frozen warrant rule (warrant). Report false success, unsupported true acceptance,
  invalid-warrant acceptance, and known-incomplete acceptance separately; never collapse
  axes.
- **Co-primary:** independently verified true completion, non-inferiority.
- **Guardrails:** valid-work rejection, abstention rate and precision, repair success and
  time to repair, turns, tokens, spend, wall time, evaluator calls, retries, crashes,
  malformed calls, irreversible side effects, provider drift.
- **Mechanism diagnostics:** `FPA`, self-certification ratio, guess-loop length,
  turns-to-acceptance, cost per accepted change, over- and under-invalidation counts,
  mutation score of judging tests (`Discriminative_Q` gate on the verifiers themselves).

### Analysis (inherits Evidence Debt's statistical plan)

Intention to treat; blocked randomization over instances; randomization inference for
the primary contrast; paired absolute risk differences; resampling over repositories
(lineages), never over runs; provider-specific estimates before pooling; multiplicity
frozen for confirmatory endpoints; every other analysis labelled exploratory.

## 6. Milestones

| id | deliverable | done when |
|---|---|---|
| M0 | this plan, decisions D-001..D-006, protocol skeleton | committed; nothing runs |
| M1 | core: capsules and digests, unit contract, verifier registry (one implementation per metric), receipt ledger, typed rejection and abstention envelopes | exhaustive conformance tests over the closed decision space; no model calls; architecture tests for "no verdict flows from agent to receipt" |
| M2 | agent loop: Claude Agent SDK session with compiled unit context, stage/finalize transaction that runs the full validator at the stage call, sandboxed tool broker, hash-chained event journal | one real task closes end to end with a receipt; injected failure (forged test log) is refused with a typed rejection |
| M3 | baselines: pinned Claude Code and OpenHands adapters emitting the common `RawAgentEvent` stream; SWE-bench image pipeline | the same instance runs under all arms with identical budgets and sealed outputs |
| M4 | pilot: 10 sealed instances × 4 arms × 3 seeds on disjoint data; thresholds and margins set from it and frozen | `PROTOCOL.md` frozen with digests, commands, and analysis plan |
| M5 | registered study: 50 instances × 4 arms; injected specifications; substitution pairs | results reported with exact numerators and denominators; negatives preserved |
| M6 | replication on the private post-cutoff corpus; write-up; hand results to Evidence Debt Track G | claim ledger updated with DEMONSTRATED or RETRACTED, never edited in place |

Order is fixed by dependency, not interest. M4 exists so that no threshold in M5 is
chosen after seeing M5 data.

## 7. Threats to validity and how each is bounded

- **Author bias.** kusum's author also designs the tasks and the warrant rule. Truth is
  scored by SWE-bench's own hidden tests, not by the author; the warrant rule is frozen
  before any arm runs; injected specifications are sealed before assignment.
- **Harness confounds.** Baselines have different tool sets and prompts. Control C1
  isolates the acceptance mechanism from instrument availability; the verifier-access
  control gives baselines the same verifier outputs as ordinary tool results.
- **Contamination.** Public benchmark; handled by the cutoff split and the private
  replication corpus.
- **Model and provider drift.** Pin model ids, SDK, CLI, and images; a returned-model or
  fingerprint change starts a new experiment id (Evidence Debt provider matrix).
- **Rejection winning by refusing everything.** Completion non-inferiority is co-primary;
  valid-work rejection is a guardrail with a cap.
- **One implementer.** Conformance tests are exhaustive over the closed decision space,
  and the mechanism's own predictions are pre-registered; independent reimplementation
  is a replication milestone, not a claim of this repository.

## 8. Relationship to Evidence Debt

kusum consumes Evidence Debt's formal definitions (`T`, `W_Q`, `R_Q`, `D`, `C`) and its
outcome definitions unchanged, and supplies what that project's Track G lists as missing:
a treatment arm that runs a closed loop, on a domain with an oracle. Results flow back as
`ED-C004..ED-C009` evidence with this repository's claim ids cited. kusum does not modify
Evidence Debt during a registered study; it imports a content-addressed build of its core.

## 9. What is not claimed

No claim of priority or novelty for any single ingredient. No claim that agents become
truthful. No claim beyond the frozen corpus, model, and budgets until replication holds.
Until M5 reports, the honest description is: *the intervention has never been deployed in
this domain.*
