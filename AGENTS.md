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
