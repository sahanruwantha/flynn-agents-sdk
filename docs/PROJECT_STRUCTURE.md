# Python project structure

Status: first executable slice, experimental API.

```text
src/flynn_agents_sdk/
    __init__.py       # Explicit public exports and distribution version
    contracts.py      # Immutable records, protocols, evaluation binding checks
    context.py        # Bounded whole-item selection and omission/evidence reporting
    runtime.py        # Sequential async step orchestration
    budget.py         # Attempt/action counters and cooperative episode deadline
    journal.py        # SQLite intent/result/evaluation evidence and stop records
    tools.py          # Trusted registry, grants, application argument validators
    state.py          # In-memory compare-and-publish store
    inference.py      # Scripted inference adapter
    deepseek.py       # Optional direct async DeepSeek vision provider
    py.typed          # Checked public annotations
examples/
    scripted_task.py  # Offline consumer with an independent integer evaluator
tests/
    unit/
    integration/
    architecture/
```

Keep cohesive flat modules until actual responsibilities justify subpackages. The
previous expanded tree is not an implementation requirement. Further durable state, model
providers, retrieval, and isolation get modules only when implemented and tested.

Contracts use the standard library only. The runtime consumes inference and state
protocols rather than importing concrete adapters. Applications compose dependencies;
there is no global registry or import-time setup. Runtime code must never import
examples, tests, or ARC-specific code. Architecture tests enforce current boundaries.

The src layout separates installed code from tooling; tests use importlib mode.
`uv.lock` pins development dependencies. Do not commit environments or build outputs.
