# Python project structure

Status: the minimal installed package exists; the expanded runtime tree below is a
proposal. Introduce each module with its implementation and tests, not as an empty shell.

## Current tree

```text
flynn-agents-sdk/
├── pyproject.toml             # Package metadata, build backend, pytest and Ruff settings
├── uv.lock                    # Resolved development dependencies
├── README.md                  # Purpose, actual status and development commands
├── CONTRIBUTING.md            # Development conventions and review requirements
├── LICENSE
├── MANIFEST.in                # Include docs and tests in the source distribution
├── src/
│   └── flynn_agents_sdk/
│       └── __init__.py         # Minimal public facade and installed version
├── tests/
│   └── unit/
│       └── test_package.py     # Installed distribution/import identity
└── docs/                      # Architecture, API proposals, roadmap and research
```

`uv.lock` pins the repository's development environment. Consumers resolve the
library's declared dependency ranges.
Do not commit virtual environments, generated build metadata, or benchmark output.

## Target tree as functionality lands

```text
src/flynn_agents_sdk/
├── __init__.py                # Explicit stable exports; no setup or I/O at import
├── contracts/                 # Pure data types and abstract dependency interfaces
│   ├── tasks.py               # Task identity and execution limits
│   ├── inference.py           # Requests, responses, usage and adapter Protocol
│   ├── tools.py               # Calls, results, grants and tool Protocol
│   ├── events.py              # Versioned event vocabulary
│   ├── evaluation.py          # Candidate and scoped evaluation records
│   ├── state.py               # Revisions and store Protocol
│   └── errors.py              # Typed contract errors and stop reasons
├── runtime/                   # Application-independent orchestration
│   ├── runner.py              # Explicit loop and lifecycle
│   ├── dispatch.py            # Grant validation and serialized tool dispatch
│   ├── budget.py              # Reservations, usage and exhaustion
│   ├── commit.py              # Revision/evaluation preconditions
│   └── cancellation.py        # Cancellation and unresolved-effect handling
├── context/                   # Bounded packets and retrieval policy interfaces
│   ├── compiler.py
│   └── retrieval.py
├── evaluation/                # Evaluator registration and frozen-input coordination
│   ├── registry.py
│   └── coordinator.py
├── adapters/                  # Concrete I/O behind contracts
│   ├── inference/             # Scripted first; explicit local/provider adapters later
│   ├── storage/               # File-backed events, immutable records and selected head
│   └── isolation/             # Worker broker and tested confinement backends
└── py.typed                   # Ship when the public typed API is supported and checked

tests/
├── unit/                     # Pure rules and isolated component behavior
├── contract/                 # Shared conformance tests for every adapter
├── integration/              # Kernel + store + worker/adapter interactions
├── architecture/             # Enforced import and public-surface boundaries
└── fixtures/                 # Small deterministic, non-secret test data

examples/                     # Runnable consumers of public SDK APIs
benchmarks/                   # SDK overhead and scaling; ARC scores live elsewhere
docs/
├── tutorials/                # Working step-by-step examples once APIs exist
├── how-to/                   # Focused operational tasks
├── reference/                # Public API and durable schema contracts
└── decisions/                # Individual ADRs when the decision index outgrows one file
.github/workflows/            # CI when packaging and test environments are pinned
```

Each Python package directory gets a deliberate `__init__.py` when created. Domain
semantics stay in consumers: hypothesis policies, visual parsing, environments, and
official benchmark scorers do not become generic SDK modules. The existing planning
documents stay linked at their current paths until their replacements actually exist.

## Allowed imports

- `contracts` uses the standard library and other pure contracts only.
- `runtime`, `context`, and `evaluation` depend on contracts and explicit pure helpers.
  They do not select or import concrete provider, storage, or sandbox adapters.
- `adapters` implements the contracts. Provider SDK imports remain inside the appropriate
  adapter boundary, with optional installation extras when those adapters ship.
- The consumer is the composition root: it constructs adapters and supplies them to the
  runner. No global service locator, hidden singleton client, or import-time registration.
- Internal modules import concrete modules, not the package facade. The facade exports
  only supported API names and must not create circular dependencies.

Enforce these edges with architecture tests before the relevant packages land. Runtime
code cannot import tests, examples, benchmarks, generated artifacts, or ARC Harness.

## Why this structure

A src layout separates installed importable code from repository tooling and helps expose
packaging mistakes. Tests should exercise an installed package, with pytest's importlib
mode avoiding test-directory path mutation. See the [PyPA guidance](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
and [pytest guidance](https://docs.pytest.org/en/stable/explanation/goodpractices.html).

The package uses responsibility-based boundaries without requiring a separate class or
module for every operation. Begin small, split cohesive behavior when it warrants it, and
avoid vague `utils.py`, `helpers.py`, or `manager.py` collections. Keep runtime dependencies
minimal and give expensive provider/tool integrations explicit opt-in extras.
