# Design decisions

These decisions describe Flynn Agents SDK on its own terms. Mechanisms remain proposed
unless their implementation and tests exist.

## D-001 — Scope

Accepted direction, 2026-09-06. Build a reusable Python agent runtime that owns inference
requests, tool dispatch, context, budgets, records, and evaluated state transitions.
Applications supply domain policies and evidence semantics. ARC Harness is the first
consumer; its game rules and scoring are excluded from this package.

## D-002 — Own orchestration

Accepted operator constraint. Do not depend on Claude Agent SDK or OpenAI Agents SDK.
Thin inference clients may transport explicit requests, but cannot own hidden loops,
tool execution, session memory, or retries. Local inference must be supportable.

## D-003 — Package and dependency boundaries

Accepted scaffold and proposed runtime layout. Use a src layout, distribution name
`flynn-agents-sdk`, and import name `flynn_agents`. Keep pure records and interfaces
separate from orchestration and I/O implementations. Consumers construct adapters and
inject dependencies. Provider clients and worker backends belong at the outer boundary.
Detailed ownership is documented in [Project structure](PROJECT_STRUCTURE.md).

## D-004 — Evaluation authority

Proposed runtime rule. Model proposals and observed evidence are separate records.
An evaluation establishes only its declared scope. Commit requires matching input
identities and the expected base revision. Type annotations and hashes alone do not
establish a security boundary or prove semantic truth.

## D-005 — Incremental implementation

Build one runnable vertical slice before growing abstractions. Keep planned modules in
the design until behavior and tests justify creating them. No empty subsystem skeletons,
generic utility dumping grounds, or automatic plugin discovery at this stage.

## D-006 — Licensing and distribution

The SDK retains Apache-2.0. Dependencies and model weights retain their own licenses.
The repository remains private. A public package name, trademark clearance, public
release, and competition eligibility are not established by the repository name.
