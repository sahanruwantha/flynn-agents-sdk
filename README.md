# Flynn Agents SDK

A custom agent runtime for bounded reasoning, tool execution, and evidence-backed state.
The runtime owns the loop. Models propose work; registered evaluators determine whether
specific output contracts are satisfied.

**Status: design and minimal Python scaffold.** The distribution is `flynn-agents-sdk`
and the import package is `flynn_agents`, version 0.0.1. Only package metadata and a
smoke test exist. The runtime, inference adapters, tools, persistence, and isolation
components are planned; there is no functional agent API yet.

## What we are building

A small Python SDK that lets applications control every model invocation, tool grant,
context packet, budget, and state transition. Claude Agent SDK and OpenAI Agents SDK
are excluded. Thin inference clients are allowed: they transport explicit requests,
not agent loops, hidden tool execution, sessions, or automatic context management.
The competition path must support local inference without hosted API access.

Our first consumer is [ARC Harness](https://github.com/sahanruwantha/arc-harness),
which will learn unfamiliar game rules through observation and experiment. The SDK
itself will know nothing about ARC grids, game IDs, scoring, or solution strategies.

```text
arc-harness: observations → hypotheses → experiments → plans → game actions
                                │
                                ▼
flynn-agents-sdk: context · inference · tools · budgets · events · evaluations
```

## Principles

- Observations and interpretations have separate identities and types.
- Model output cannot certify its own correctness.
- A passed check establishes only its declared scope, never universal truth.
- Uncertainty permits bounded experiments; invalid authority does not permit a commit.
- Context is compiled for the active decision, with explicit retrieval for missing evidence.
- Recorded evidence survives a session; stale conclusions do not silently survive revisions.
- The runtime records failures and ambiguous external effects instead of retrying blindly.

Flynn is an independent SDK. Its design keeps domain behavior in consumer applications
and makes execution policy explicit and inspectable.

## Documentation

- [Architecture](docs/ARCHITECTURE.md): boundaries and control loop.
- [SDK design](docs/SDK_DESIGN.md): proposed interfaces and failure semantics.
- [Roadmap](docs/ROADMAP.md): coordinated implementation and exit criteria.
- [Research plan](docs/RESEARCH_PLAN.md) and [evaluation protocol](docs/PROTOCOL.md).
- [Claim ledger](docs/CLAIMS.md): what is established and what remains a hypothesis.
- [Decisions](docs/DECISIONS.md): scope change and implementation constraints.
- [Project structure](docs/PROJECT_STRUCTURE.md): current tree, proposed modules, and dependency rules.
- [Contributing](CONTRIBUTING.md): Python conventions and verification workflow.

## Working on the current scaffold

Python 3.11+ and `uv` are the development baseline. These commands test only
what exists today; they do not run an agent:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

There is no published install command or implemented `flynn` CLI yet. Future API
examples in design documents are specifications, not working usage examples.

Licensed under [Apache-2.0](LICENSE). Model weights and inference backends retain their
own terms. The repositories remain private until a separate release decision.
