# Claim Ledger

**Ledger date:** 2026-09-04

Every reported result must cite a claim id. Status vocabulary follows Evidence Debt:
**DEMONSTRATED** (inspectable evidence supports the exact bounded statement),
**CONSTRUCTED** (the named artifact exists and passes its declared checks; no empirical
effect implied), **HYPOTHESIS** (falsifiable, prospective evidence missing),
**RETRACTED** (no longer asserted; retained). Rows are amended by appending, never by
rewriting.

## Construction claims (owed by M1 and M2)

| ID | Status | Bounded claim | Required evidence | Falsifier or limit |
|---|---|---|---|---|
| KS-C001 | HYPOTHESIS | A receipt can be built only from `VerifierResult` values, and no code path constructs one from agent output. | AST architecture test over `src/kusum`; a mutant that routes an agent claim into a receipt fails it. | Any construction site outside the verifier package. Says nothing about verifier quality. |
| KS-C002 | HYPOTHESIS | The four-way decision (`PAID`, `OPEN`, `UNKNOWN`, `CONFLICT`) matches a separately written count-based rule on every enumerable one-unit state. | Exhaustive enumeration test with the state count derived, as in ED-C012. | Any enumerated state differs. Excludes multi-unit bundles. |
| KS-C003 | HYPOTHESIS | Invalidation closure re-verifies exactly the receipts whose bound capsules changed. | Property tests over random capsule graphs: no receipt outside the closure is revoked, none inside survives. | Any under- or over-invalidation on the enumerated graphs. Soundness is conditional on complete capture. |
| KS-C004 | HYPOTHESIS | The stage call refuses every finding the complete validator would refuse at finalize, on the same candidate. | Differential test: stage findings ⊇ finalize findings for every fixture. | A finding first seen at finalize. |

## Prospective empirical hypotheses (owed by M5 and M6)

| ID | Status | Hypothesis | Required evidence | Falsifier and current limit |
|---|---|---|---|---|
| KS-H1 | HYPOTHESIS | At preserved completion, kusum emits fewer unsupported successes than Claude Code and OpenHands on the same tasks, model, and budgets. | Registered M5 study; `USR` per assigned run; ITT; randomization inference; lineage-clustered intervals. | Interval includes effects below the frozen minimum; completion fails non-inferiority; gain vanishes under the verifier-access control. Nothing has run. |
| KS-H2 | HYPOTHESIS | Self-certification ratio is lower under kusum at equal true completion. | Same study; ratio and completion reported jointly. | Ratio not lower, or lower only through lower completion. |
| KS-H3 | HYPOTHESIS | On sealed unsatisfiable specifications kusum abstains with the right contradiction above frozen precision and recall; baselines report success on a non-zero share. | Sealed injected set; abstention scored against the sealed contradiction. | Abstention on satisfiable items above the cap; missed abstentions; baselines also abstain. |
| KS-H4 | HYPOTHESIS | Guess-loop length is shorter under typed rejections than under free-form error text at equal completion. | Loop length from the journal; control arm with the same verifiers and free-form output. | No difference, or difference explained by turn budget. |
| KS-H5 | HYPOTHESIS | Obligation-relative invalidation is non-inferior to whole-state binding on unsafe reuse and cheaper to re-verify. | Paired comparison on the same change sequences; unsafe reuse, over-invalidation, and evaluator calls reported separately (ED-C005). | Any unsafe reuse whole-state binding catches; no cost reduction. |

## Retracted claims

None yet.
