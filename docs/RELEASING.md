# Versioning and releases

`pyproject.toml` is the single version source. `flynn_agents_sdk.__version__` reads the
installed distribution metadata. Never hand-edit that Python value.

## Compatibility policy

Use MAJOR.MINOR.PATCH versions. Before 1.0, breaking public API changes require a minor
version bump and migration notes; patches preserve the public API. Backward-compatible
features may also use a minor bump. After 1.0, breaking changes require a major bump.
Consumers should pin an exact release or a compatible minor range while the API is experimental.

Keep user-visible changes under `Unreleased` in CHANGELOG.md. Every release must have a
matching dated heading. Tags use `v` plus the exact project version and must not be moved.

## Release checklist

1. Update the project version and changelog; add migration notes for breaking changes.
2. Run `uv lock`, `uv sync --locked --extra dev`, and the checks in CONTRIBUTING.md.
3. Open and merge a reviewed PR; wait for main CI to pass.
4. Tag the tested commit: `git tag -a vX.Y.Z -m "Release X.Y.Z"` and
   `git push origin vX.Y.Z`.
5. The release workflow re-runs CI, validates the tag against metadata and changelog,
   builds a wheel and source archive, and uploads both with SHA256SUMS to GitHub Releases.
   All 0.x releases are marked prerelease on GitHub to reflect API instability.
6. Check the release assets and install the wheel in a fresh environment.

A failed release workflow must be investigated, not bypassed. Correct a broken release
with a new version rather than replacing an existing tag or artifact. The workflow uses
GitHub's scoped token, not a personal token or package-index credential.

## Consumer update requirement

The repository is private. After pushing an SDK change, run
`bash ../arc-harness/scripts/sync_sdk.sh` and record the installed commit and test result.
This requirement applies to unreleased changes too; the harness tracks `main` over SSH
and locks its resolved commit. Do not use an editable local-path dependency.

The script runs on demand as part of the SDK change workflow; it is not a background
watcher. It never uploads an SSH key, publishes to PyPI, or invokes paid inference.

## PyPI

Private SSH Git installs and private GitHub release assets are the distribution channels.
PyPI publication is not enabled.
A maintainer must first establish project ownership on PyPI, configure a trusted publisher
bound to a reviewed workflow and protected environment, and add the publishing job.
Do not add PyPI credentials to the repository or claim a PyPI release before it exists.
