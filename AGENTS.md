# SDK change workflow

Owner preference: this repository stays private. Do not make it public or publish to PyPI.
Use SSH Git authentication already configured on the host; never copy keys into a repo.

After every SDK change that is pushed, install it into the adjacent ARC Harness before
reporting completion:

1. Run the SDK checks and push the authorized SDK change.
2. Run `bash ../arc-harness/scripts/sync_sdk.sh`.
3. Verify that the harness installed the pushed SDK commit and all offline tests pass.
4. Report the installed commit and any test failure. Preserve the harness's updated lock.

Do not treat a sibling editable checkout as installation evidence. The harness consumes
the private Git repository over SSH and pins the tested commit in uv.lock. Unpushed
changes cannot be installed over SSH; state that limitation if pushing is not authorized.
Paid inference runs remain separate from these offline compatibility checks.

# Standing learning objective

For learning-related work, read `.cursor/rules/learning-procedure.mdc` and apply it.
The shared learning procedure and its measurable improvement across environments are
our objective; ARC and other games are test settings. Preserve the SDK workflow above.

# Inference configuration identity

Configuration-aware adapters describe effective settings without dispatch and record
the fingerprint derived from the actual request payload. Credentials and changing
request evidence are not configuration. Changing request-to-wire framing requires a
configuration protocol generation change; harnesses separately bind task prompts,
tool contracts, evidence and domain qualification. Never copy a preflight fingerprint
into usage without deriving it from the dispatched payload.
