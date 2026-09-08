# Security policy

Only the latest 0.x release receives security fixes. There is no guaranteed response SLA.

Report suspected vulnerabilities privately through
[GitHub's vulnerability reporting form](https://github.com/sahanruwantha/flynn-agents-sdk/security/advisories/new).
Include affected versions, a minimal reproduction, and the expected boundary. Do not
include API keys, private datasets, or another person's credentials in reports.

If private reporting is temporarily unavailable, contact the maintainer through their
[GitHub profile](https://github.com/sahanruwantha) to arrange a private channel before
sharing exploit details. Do not post an exploit in a public issue.

Registered tools, evaluators, request hooks, and trace callbacks remain trusted code.
Keep secrets out of model inputs and trace sinks. Generated Python can use the opt-in
[confined program worker](docs/guides/program-worker.md). Its tested Linux boundary does
not protect in-process tools or replace a VM against kernel vulnerabilities.
