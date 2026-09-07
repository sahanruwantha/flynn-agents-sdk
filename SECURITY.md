# Security policy

Only the latest 0.x release receives security fixes. There is no guaranteed response SLA.

Report suspected vulnerabilities privately through
[GitHub's vulnerability reporting form](https://github.com/sahanruwantha/flynn-agents-sdk/security/advisories/new).
Include affected versions, a minimal reproduction, and the expected boundary. Do not
include API keys, private datasets, or another person's credentials in reports.

If private reporting is temporarily unavailable, contact the maintainer through their
[GitHub profile](https://github.com/sahanruwantha) to arrange a private channel before
sharing exploit details. Do not post an exploit in a public issue.

Flynn is not a sandbox: registered tools, evaluators, request hooks, and trace callbacks
are trusted code. Keep secrets out of model inputs and trace sinks. Use separate workers
and application-level isolation for untrusted code or files.
