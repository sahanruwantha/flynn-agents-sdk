# Flynn Agents SDK

[![Checks](https://github.com/sahanruwantha/flynn-agents-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/sahanruwantha/flynn-agents-sdk/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

A small Python runtime for agents whose tool permissions, budgets, observations, and
state changes need to be explicit and inspectable.

**Experimental 0.2 API (unreleased) · local POSIX · Python 3.11+ · Apache-2.0**

Models propose tool calls. Your application validates arguments, supplies tools and an
independent evaluator, and decides what success means. Flynn coordinates one bounded
step at a time. It has no required third-party runtime dependencies; DeepSeek is optional.

## Install (private repository)

An SSH key authorized for this repository is required. The 0.2 branch is not released;
install this checkout for development (`uv sync --extra dev`). The previous release uses
the incompatible 0.1 API:

```bash
python -m pip install "flynn-agents-sdk @ git+ssh://git@github.com/sahanruwantha/flynn-agents-sdk.git@v0.1.0"
```

For DeepSeek, use `flynn-agents-sdk[deepseek]` in the same requirement. Wheels and source
archives are available in [GitHub Releases](https://github.com/sahanruwantha/flynn-agents-sdk/releases).
The project is not yet published to PyPI; `pip install flynn-agents-sdk` is not the
installation path documented for this release.

## Try it without an API key

```bash
git clone git@github.com:sahanruwantha/flynn-agents-sdk.git
cd flynn-agents-sdk
uv sync --locked --extra dev
uv run python examples/scripted_task.py
```

The [complete example](examples/scripted_task.py) uses scripted inference to propose
incrementing `4`, executes the registered tool, independently checks `5`, and commits
revision 1. Replace `ScriptedAdapter` with an implementation of `InferenceAdapter` to
connect a model. Applications supply the loop around `await runtime.step(objective)`.

## Included

- **Enforced tool grants:** per-step overrides can narrow permissions; the broker
  enforces the same permitted tools shown to inference.
- **Bounded execution:** inference, tool, external-action, and cooperative time limits.
- **Evaluated state:** explicit optional state updates, atomically persisted with evaluations.
- **SQLite evidence:** durable requests, reservations, intents, results, evaluations and state; unresolved
  dispatches block further execution instead of triggering automatic retries.
- **Context selection:** whole items chosen within a character budget, with explicit
  evidence IDs and omissions; required items must fit.
- **Optional DeepSeek adapter:** direct HTTP requests, text/image inputs, structured
  traces, and typed response errors. No hidden agent loop or automatic retries.

Flynn runs trusted application code in the same process. It is not a sandbox. Deadlines
cannot preempt blocking Python. SQLiteRun restores recorded state and remaining operation budgets. It cannot
restore a Blender scene, reconcile external effects, or certify task completion. See the
[runtime guide](docs/guides/runtime.md) for these boundaries.

## Keep ARC Harness on the current SDK

After every pushed SDK change, run the harness's update command:

```bash
bash ../arc-harness/scripts/sync_sdk.sh
```

It fetches `main` over SSH, records the exact commit in `uv.lock`, installs the package
into the harness `.venv`, verifies Git provenance, and runs the offline harness tests.
Normal runs use `uv sync --locked --extra dev` for that exact tested commit. The harness
does not import an editable sibling checkout. Unpushed code is not available over SSH.

## Documentation

- [Documentation index](docs/README.md) — current guides and clearly marked design work.
- [DeepSeek integration](docs/guides/deepseek.md).
- [SDK versus harness ownership](docs/OWNERSHIP.md).
- [Changelog](CHANGELOG.md) and [versioning and releases](docs/RELEASING.md).
- [Contributing](CONTRIBUTING.md), [security reports](SECURITY.md), and
  [community expectations](CODE_OF_CONDUCT.md).

Domain rules, spatial memory, experiment choice, and scoring belong in applications.
Flynn's ARC consumer demonstrated a completed level in a bounded development run;
that is consumer evidence, not a general SDK task-success guarantee.

Licensed under [Apache-2.0](LICENSE). Provider services and model weights have their own terms.
