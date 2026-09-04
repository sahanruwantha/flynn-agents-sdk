# Preregistration Draft

- Protocol version: `0.1.0-draft`
- Date authored: 2026-09-04
- Status: **UNFROZEN DRAFT — NO REGISTERED PHASE HAS RUN**

Freezing requires an immutable commit of this repository, this protocol's digest, the
schema digests, the sealed instance set and hidden-test digests, the sealed injected
specifications, the arm pins (kusum tag, Claude Code version, OpenHands release, images,
SDK, model ids), every budget and generation option, the exact commands, and the analysis
plan. Results produced before that event are development evidence and cannot satisfy this
protocol retroactively.

## Research boundary

The study asks whether a harness in which acceptance is derived only from independent
verifiers reduces unsupported success at preserved completion, on the frozen corpus,
model, and budgets. It does not test whether agents are truthful in general, whether a
receipt implies correctness beyond its verifiers, or whether the effect holds outside the
frozen conditions.

## To be frozen from the M4 pilot (disjoint instances)

| quantity | set by | frozen value |
|---|---|---|
| practical minimum effect on `USR` | pilot risk-and-cost exercise | — |
| completion non-inferiority margin | pilot | — |
| abstention-on-satisfiable cap | pilot | — |
| valid-work rejection cap | pilot | — |
| turn, token, dollar, wall-time budgets per run | pilot | — |
| number of seeds per instance × arm | power analysis on pilot variance | — |
| multiplicity control for confirmatory endpoints | statistician review | — |

## Primary analysis (fixed now)

- Unit of assignment: instance × seed; blocked randomization by repository; arms run in
  randomized order within block.
- Primary contrast: `Pr(USR | kusum) − Pr(USR | Claude Code)` and `− Pr(USR | OpenHands)`,
  each as a paired absolute risk difference with lineage-clustered resampling and
  randomization inference.
- Co-primary: true completion non-inferiority, same pairing.
- Intention to treat: crashes, timeouts, refusals, and malformed runs are outcomes.
- Sensitivity, prespecified: worst-case missing outcomes, execution order, cache state,
  provider drift, pre/post training-cutoff split.
- Everything else is exploratory and labelled so.

## Stop rules

Stop enrolment if any arm's severe-event rate (irreversible side effect, credential
exposure, sandbox escape) exceeds zero; report exact bounds and extend under a registered
rule rather than manufacture precision.

## Reproducibility

Every run publishes its pre- and post-run workspace digests, the hash-chained event
journal, raw provider objects, and the sealed scoring inputs; the analysis is a script
whose inputs are those digests.
