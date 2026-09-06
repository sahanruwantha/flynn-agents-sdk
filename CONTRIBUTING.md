# Contributing

## Environment and checks

Use Python 3.11+ in a virtual environment. Package metadata and tool settings live in
`pyproject.toml`; do not duplicate them in setup.py or ad hoc requirements files.

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

Before a release, install the built wheel into a fresh environment and run the tests
against that installation outside the source checkout. Do not use PYTHONPATH or sys.path
patches to hide missing installed files. Test the minimum supported Python and a current
supported release in CI when that workflow is added. No CI matrix is implemented yet.

## Python conventions

- Use PEP 8 naming, module-level imports, and clear docstrings on public APIs. Annotate
  public functions and boundary records. Add a type checker with the first real API;
  annotations alone do not validate untrusted inputs at runtime.
- Prefer immutable dataclasses for pure values, enums for closed vocabularies, and
  Protocol interfaces for injected dependencies. Add validation libraries only when
  boundary validation needs justify the dependency.
- Keep I/O at explicit adapters. Avoid import side effects, mutable module globals,
  wildcard imports, circular dependencies and implicit plugin registration.
- Use context managers for owned resources and narrowly caught exceptions. Preserve
  causes when translating adapter failures. Do not swallow cancellation or confuse
  unknown external effects with a failed, safe-to-repeat operation.
- Use pathlib for paths and explicit UTF-8 for text I/O. Never unpickle untrusted input.
  Log structured facts through library logging without configuring the application's
  root logger. Keep secrets and unavailable private model reasoning out of records.
- Version comes from pyproject.toml via installed distribution metadata. Public exports
  are explicit; do not promise stability for unfinished internals.

## Testing and change scope

Tests live under tests/ and follow production responsibilities. Assert observable
behavior, failure boundaries, and meaningful counterexamples rather than internal call
sequences. Shared adapter tests establish conformance; integration tests exercise real
publication and crash boundaries. Do not make unit tests depend on network or model spend.

Keep current implementation and proposed design visibly separate. Add a module only with
working behavior. Update the README and relevant contracts when behavior changes. Follow
[the structure proposal](docs/PROJECT_STRUCTURE.md) and introduce architecture tests with
new package boundaries. Do not add compatibility aliases for unreleased scaffold names.
