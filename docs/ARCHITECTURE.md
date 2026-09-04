# Architecture

**Status:** target architecture for M1 and M2. Nothing below exists yet.

## Invariants

1. **No verdict flows from the agent to a receipt.** The agent's claims are journaled as
   events and excluded from acceptance inputs by type: the receipt builder accepts only
   `VerifierResult` values, which only registered verifiers can construct.
2. **One implementation per metric.** A verifier registry maps a metric id to exactly
   one implementation; producers and consumers call the same code; unknown ids are
   rejected.
3. **Content addressing everywhere.** Task, judging tests, repository snapshot, unit
   contract, change, verifier configuration, and policy are digested capsules. A receipt
   binds all of them. Changing any capsule invalidates exactly the receipts whose closure
   contains it (computed, never inferred).
4. **Earliest boundary.** Every check runs at the first point where its inputs exist:
   the stage call validates the whole candidate, not finalize.
5. **Fail closed.** Missing, stale, ambiguous, or schema-incompatible authority is a
   typed refusal, never a warning.
6. **Rejections teach.** Every refusal is a `TypedRejection`: contract id, expected,
   found, legal next actions.
7. **Abstention is legal.** `cannot_satisfy_in_scope(contradiction_evidence)` ends the
   unit with a typed finding that opens a replan; the harness never forces another guess.

## Components (M1, no model calls)

```text
src/kusum/
  domain/
    capsules.py        Task, JudgingTests, RepoSnapshot, UnitContract, Change: frozen,
                       digested, no I/O
    receipts.py        Receipt = verifier results × capsule digests; PAID / OPEN /
                       UNKNOWN / CONFLICT decision, derived only from VerifierResult
    rejections.py      TypedRejection, Abstention envelopes; closed vocabularies
    invalidation.py    closure computation: which receipts a capsule change touches
  verifiers/
    registry.py        metric id → one implementation; VerifierResult constructor is
                       private to this package
    build.py types.py lint.py tests.py mutation.py coverage.py
  ledger/
    journal.py         append-only, hash-chained event journal; one writer per run
    store.py           immutable receipts and findings, content-addressed
```

Conformance is exhaustive over the closed decision space (every verifier-result
combination × every capsule-freshness state), the way Evidence Debt enumerates its
17,496 one-assessment states. Architecture tests assert invariants 1 and 2 by AST.

## Components (M2, model calls)

```text
src/kusum/
  agent/
    session.py         Claude Agent SDK session with compiled unit context only
    tools.py           bounded tools: read within unit, patch within unit, run declared
                       verifiers, stage, finalize, abstain; every tool answer is typed
    policy.py          hooks: deny writes outside the unit, deny unregistered commands,
                       journal every call
  transaction/
    stage.py           validates the full candidate at the stage call; refuses any new
                       finding it introduces; records what finalize will still refuse
    finalize.py        runs the complete verifier set, builds the receipt, seals the
                       change; a max-turns or budget exhaustion publishes nothing
  sandbox/
    broker.py          narrow typed operations over an isolated workspace
    container.py       non-root, read-only root, no ambient network, fixed limits
```

## Experiment layer (M3+)

```text
experiments/
  common/              TrialSpec, RawAgentEvent, seals, label firewall (from Evidence
                       Debt's live-study contract; imported as a content-addressed build)
  arms/
    kusum.py           treatment
    kusum_tools_only.py control C1
    claude_code.py     baseline B1 (pinned CLI, subprocess, common event stream)
    openhands.py       baseline B2 (pinned release, common event stream)
  tasks/
    swebench.py        sealed instance sets, images, hidden tests kept outside arms
    unsatisfiable.py   injected contradictions, sealed before assignment
    substitutions.py   truth-preserving evidence substitution pairs
  scoring/
    truth.py           hidden tests only
    warrant.py         frozen rule only
    outcomes.py        USR, FPA, completion, guardrails, diagnostics
```

## What is deliberately absent

No memory across runs, no repository-wide context, no self-repair without a receipt, no
retry from prose, no "helpful" tolerance. Each of these is a place the first domain found
unsupported success hiding.
