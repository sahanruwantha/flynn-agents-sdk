# Claim ledger

Updated 2026-09-06. This ledger distinguishes repository facts from proposed benefits.

| ID | Status | Claim | Evidence needed / current limit |
|---|---|---|---|
| F-C001 | Present | Planning docs and a version-only Python scaffold exist | Repository files; no functional runtime implied |
| F-H001 | Hypothesis | Invalid or stale evaluations cannot commit output | Negative tests plus crash and substitution fixtures |
| F-H002 | Hypothesis | A consumer controls every model request and tool dispatch | Adapter/kernel conformance and captured request trace |
| F-H003 | Hypothesis | Bounded context reduces cost without lowering completion | Same-model ablation with completion and latency reported |
| F-H004 | Hypothesis | Counterexample-driven repair improves ARC action efficiency | Frozen held-out evaluation in arc-harness |
| F-H005 | Hypothesis | Runtime is reusable beyond ARC | Independent non-ARC consumer through the same public API |

No ARC score, performance improvement, world-first architecture, training benefit, or
competition eligibility is established. Historical KS-* claims are retained in
[the archived ledger](history/kusum/CLAIMS.md), not promoted or silently relabelled.
