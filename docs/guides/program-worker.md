# Confined program worker

`ProgramWorker` is an opt-in execution boundary for generated Python. Ordinary SDK
tools still run as trusted application code. Applications own the model language,
evidence, verification, and decisions; a successful worker result only means execution
and JSON framing succeeded.

The supported backend is Linux x86-64 with a Debian/Ubuntu system Python under
`/usr`, Bubblewrap supporting `--disable-userns` (tested with 0.9.0), and libseccomp.
Missing prerequisites or failed confinement return a failed result. There is no
unconfined fallback. No Python package dependency or provider is added.

## Interface

A source must export four functions: `init(observation)`, `transition(state, action)`,
`render(state)`, and `outcome(state)`. Arguments and return values are finite JSON.
Their domain meaning is entirely application-owned. Every call starts a new process;
thread state explicitly through results, not globals or files.

```python
from flynn_agents_sdk import ProgramLimits, ProgramWorker

source = '''
def init(observation): return observation
def transition(state, action): return state + action
def render(state): return state
def outcome(state): return None
'''
worker = ProgramWorker(ProgramLimits(cpu_seconds=2, wall_seconds=5))
initial = worker.run(source, "init", [2])
if initial.ok:
    next_state = worker.run(source, "transition", [initial.value, 3])
```

The call is synchronous. An async application must arrange its own thread/call boundary
and aggregate budgets. Calls do not automatically create SDK journal operations; the
application must record source/input identities and results through its tool/evaluator
path before using them as evidence. Result values remain untrusted, even when `ok` is
true: a program can deliberately emit a valid JSON envelope with a false prediction.

## Confinement and bounds

Bubblewrap creates user, mount, PID, network, IPC, UTS and cgroup namespaces, removes
capabilities, disables nested user namespaces, and starts a separate session. The root
and isolated proc/dev mounts are read-only. Only the system interpreter, standard
library, architecture libraries, and trusted bootstrap are mounted. Home, workspace,
credentials, evaluator files, and the host environment are absent. Open host file
descriptors are closed; source and arguments arrive through a pipe.

Before compiling source, the bootstrap installs hard address-space and CPU limits and
a default-deny seccomp filter. Network syscalls, process/thread creation, exec, mounts,
ptrace, and namespace changes are not allowed. This is OS confinement, not a restricted
Python builtins list. The parent enforces wall time and combined stdout/stderr size and
kills the process group on exhaustion. The sandbox also dies with its parent.

Defaults per call: 2 CPU seconds, 5 wall seconds including launch, 256 MiB address space,
1 MiB input, 1 MiB combined output. Source is capped at 128 KiB. CPU and memory limits
start in the bootstrap before source execution. Trusted interpreter discovery has its
own 3-second timeout; setup latency can exceed a very small wall limit. There is no
aggregate concurrency, episode, token, or monetary budget in this worker.

This backend shares the host kernel; it is not a VM or protection against kernel bugs.
The explicitly mounted runtime libraries are readable. The tests establish the named
escape-path checks, not a proof against every escape or an independent security audit.
Widening mounts or the syscall allowlist changes this boundary.

## Verification

```bash
FLYNN_REQUIRE_CONFINEMENT=1 .venv/bin/pytest -q tests/integration/test_program_worker.py
```

This required mode fails when confinement is unavailable. Portable test runs may skip
the OS-dependent cases; skipped tests do not establish backend support. The cases cover
private files/environment/inherited descriptors, read-only mounts, a real host listener
and raw network syscall, process/namespace/ptrace attempts, CPU/memory/time/output
exhaustion, malformed output, and setup failure before executing source.

Policy details follow the [Bubblewrap documentation](https://github.com/containers/bubblewrap/blob/main/README.md)
and [Linux seccomp interface](https://man7.org/linux/man-pages/man2/seccomp.2.html).

This prerequisite adds no world-model proposer or paid experiment. The ARC verifier,
holdout protocol, model selection, and useful-action comparison remain harness work.
