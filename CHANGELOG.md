# Changelog

Changes are grouped by release. Dates use YYYY-MM-DD. Version policy is in
[RELEASING.md](docs/RELEASING.md).

## [Unreleased]

### Changed

- Repository made private by owner request; installation guidance uses authenticated SSH.
- SDK changes require refreshing the ARC Harness Git pin, reinstalling, and testing.

## [0.1.0] - 2026-09-07

First public runtime release. The API remains experimental.

### Added

- Sequential async runtime with typed inference, tool, evaluation, and state interfaces.
- Tool argument validation, construction grants, and enforced narrowing per step.
- Inference/tool/action budgets and cooperative wall-time deadlines.
- SQLite intent/result/evaluation journaling and unresolved-effect dispatch protection.
- Whole-item context selection with evidence and omission reporting.
- Optional DeepSeek text/vision adapter with structured traces and typed provider failures.
- Scripted offline example, unit/integration/architecture tests, and typed package marker.
- Public contributor and security guidance, version policy, CI, and GitHub release assets.

### Limitations

- Trusted tools execute in-process; no sandbox or blocking-code preemption.
- No automatic external-effect reconciliation, accepted-state recovery, or budget recovery.
- Application evaluators define success; a satisfied step does not prove task completion.

## [0.0.1] - 2026-09-06

### Added

- Internal package scaffold, Apache-2.0 license, and initial design documents.
- Distribution name `flynn-agents-sdk` and import name `flynn_agents_sdk`.

This version was not a public package release.

[Unreleased]: https://github.com/sahanruwantha/flynn-agents-sdk/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sahanruwantha/flynn-agents-sdk/releases/tag/v0.1.0
[0.0.1]: https://github.com/sahanruwantha/flynn-agents-sdk/commit/e48d996bced22ba2b8a8df61a675903885cdf207
