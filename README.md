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

An SSH key authorized for this private repository is required. Development and consumers
use `main`; the experimental 0.2 API is not tagged or published to PyPI:

```bash
python -m pip install "flynn-agents-sdk @ git+ssh://git@github.com/sahanruwantha/flynn-agents-sdk.git@main"
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
connect a model. Applications may supply the loop around `await runtime.step(objective)` or use
[Session](docs/guides/sessions.md) with explicit step/stop policy.

## Included

See the [SDK cutover readiness checklist](docs/SDK_READINESS.md) for scope and limitations.

- **Native structured tools:** immutable text/image observations and structured data.
- **Dispatch guards:** required decisions are durable and enforced before tool dispatch.
- **Session lifecycle:** explicit continuation/stop policy and durable event notifications.

- **Enforced tool grants:** per-step overrides can narrow permissions; the broker
  enforces the same permitted tools shown to inference.
- **Bounded execution:** inference, tool, external-action, cooperative time limits, and
  optional output-token reservations. Unknown output usage blocks further model calls;
  scripted work needs no output tokens. Input usage is accounted for, not capped.
- **Evaluated state:** explicit optional state updates, atomically persisted with evaluations.
- **SQLite evidence:** durable requests, reservations, intents, results, evaluations and state; unresolved
  dispatches block further execution instead of triggering automatic retries.
- **Context selection:** whole items chosen within a character budget, with explicit
  evidence IDs and omissions; required items must fit.
- **Provider-neutral accounting:** `InferenceResult` carries a proposal and usage; schema 5
  records known, unknown and not-applicable usage, including rejected responses.
  Missing reports remain unreported. `SQLiteRun.inspect` reads schemas 2–4 for audit only;
  execution requires a new schema-5 run.
- **Optional DeepSeek adapter:** direct HTTP requests, text/image inputs, structured
  traces, and typed response errors. No hidden agent loop or automatic retries.

Ordinary Flynn tools run trusted application code in the same process; their deadlines
cannot preempt blocking Python. After a tool returns, Flynn preserves its evidence
but refuses to begin evaluation after the deadline. It checks again before publishing
an evaluation or state update, including recovery and direct SQLite completion.
Callers still need bounded, cancellable I/O for timely interruption. Generated Python can use the separate opt-in
[confined program worker](docs/guides/program-worker.md), with a tested Linux backend
and no unconfined fallback. SQLiteRun restores recorded state and remaining operation budgets. It cannot
restore a Blender scene, reconcile external effects, or certify task completion. See the
[runtime guide](docs/guides/runtime.md) for these boundaries.

## Keep ARC Harness on the current SDK

After every pushed SDK change, run the harness's update command:

```bash
bash ../arc-harness/scripts/sync_sdk.sh
```

It resolves the SDK revision selected in ARC's `pyproject.toml` over SSH, records the
exact commit in `uv.lock`, installs the package
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

### Optional bounded HTTPS reads

The `http` extra adds caller-policy-bound HTTPS response transport. Exact permitted
origins, redirect limits, response byte caps and a total deadline remain explicit;
source selection, extracted text and domain acceptance belong to the harness.
See [bounded HTTPS reads](docs/http.md) for the transport and tool-registration contract.
