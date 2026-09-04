# kusum

## A coding-agent harness in which nothing self-certifies

An agent that says "done" has not finished. In kusum, a change is accepted only when a
typed receipt says so, and that receipt is derived from independent verifiers (build,
types, lint, hidden and declared tests, mutation adequacy of the judging tests) bound by
content digest to the task, the repository snapshot, and the change. The agent's own
verdict is never an input to acceptance. Every refusal names the contract it violated,
expected versus found, and the legal next actions. "Cannot satisfy this specification in
scope" is a first-class, typed outcome with evidence, not a failure to keep trying.

kusum is a research artifact, built from scratch, with two purposes:

1. **The second domain for Evidence Debt.** The mechanism in
   `../evidence-debt` was distilled from incidents in a Blender production harness. A
   schema that only fits the incidents it was distilled from measures its own design.
   Software-agent success claims ("tests passed", "build is green") are the planned second
   domain, and here they come with something the first domain lacked: a ground-truth
   oracle (hidden tests) that is independent of the warrant rule, so *truth* and *warrant*
   can finally be measured separately on the same runs.
2. **The treatment arm the causal study never had.** Evidence Debt's Track G (randomized
   closed-loop trials, `USR = Pr(success emitted | warrant invalid or completeness
   incomplete)`) is gated on "the treatment arm exists and a closed loop runs". kusum is
   that arm. The baselines are Claude Code and OpenHands on the same tasks, the same model,
   and the same budgets.

## What carries over unchanged from the VFX harness

- Nothing self-certifies: acceptance is a receipt from independent verifiers.
- Content-addressed authority with computed preservation: task specification, judging
  tests, and repository state are digested capsules; a change to one invalidates exactly
  the receipts whose closure it touched, nothing more.
- Bounded units with compiled context: a change set declares the files, symbols, and
  judging tests it owns; the agent's context scales with the unit, not the repository.
- Typed rejections that teach, applied at the earliest boundary where the inputs exist.
- Typed abstention with contradiction evidence, opening a replan instead of another guess.
- The improvement lifecycle: every failure becomes a mechanism with a test that fails
  without it.

## What changes

The evidence hierarchy becomes deterministic (build, types, lint) → executable (declared
tests, hidden tests, property tests, mutation score, coverage of changed lines) → judged
(rubric review only where executable evidence cannot decide, with earned blocking
authority). The Blender workers, image metrics, and judge panels do not transfer; that is
the point of choosing this domain.

## Status

`0.0.1`, planning. No mechanism exists yet. Nothing in this repository may be cited as
evidence. See [the research plan](docs/RESEARCH_PLAN.md), the
[decision log](docs/DECISIONS.md), the [architecture](docs/ARCHITECTURE.md), the
[claim ledger](docs/CLAIMS.md), and the [protocol draft](docs/PROTOCOL.md).

## Stack

Python 3.11, Claude Agent SDK pinned per `docs/DECISIONS.md` D-002, Docker for task
environments (SWE-bench images), `uv` for environments. Baseline harnesses are pinned per
experiment and never share a process with kusum.

Licensed under the [Apache License 2.0](LICENSE).
