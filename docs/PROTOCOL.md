# Evaluation protocol template

Status: UNFROZEN; no registered trial or benchmark result exists.

Before scored evaluation, commit the SDK and consumer SHAs, model/weight and tokenizer
identities, inference backend/configuration, prompt and tool schema digests, game split,
seed policy, action/compute/wall limits, scorer version, retry rules, and analysis script.
A changed component starts a new experiment identity. Never relabel development runs
as confirmatory evidence after seeing their outcomes.

Record every assigned episode, including crash, timeout, malformed response, and refusal.
Report environment completion separately from procedural validity and predictor accuracy.
Internal diagnostics cannot replace official game scoring. Publish per-game results,
aggregate methodology, repeated-run variation, and complete budgets for each arm.

Freeze development versus held-out games before tuning. Group variants from the same
underlying mechanics where known. Keep run workspaces isolated and carry learned state
only across boundaries explicitly allowed by the evaluation protocol. Public-set holdout
is not proof of training-data cleanliness or private competition performance.

Numeric stopping thresholds and repetitions remain unset until a budgeted pilot. No
paid model runs or public release are authorized by this document. ARC owns its more
specific [evaluation protocol](https://github.com/sahanruwantha/arc-harness/blob/main/docs/EVALUATION.md).
