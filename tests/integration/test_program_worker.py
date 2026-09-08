import os
import socket

import pytest

from flynn_agents_sdk.program_worker import ProgramLimits, ProgramWorker

BASE = """
def init(x): return x
def transition(state, action): return state + action
def render(state): return [[state, None]]
def outcome(state): return None
"""


@pytest.fixture(scope="module")
def worker():
    worker = ProgramWorker()
    result = worker.run(BASE, "init", [0])
    if not result.ok:
        if os.environ.get("FLYNN_REQUIRE_CONFINEMENT") == "1":
            pytest.fail(f"Required confinement unavailable: {result}")
        pytest.skip(f"Confinement backend unavailable: {result.error}: {result.stderr}")
    return worker


def program(body):
    return BASE + "\ndef init(x):\n" + "\n".join("    " + line for line in body.splitlines())


def test_fixed_interface_and_fresh_state(worker):
    assert worker.run(BASE, "init", [2]).value == 2
    assert worker.run(BASE, "transition", [2, 3]).value == 5
    assert worker.run(BASE, "render", [5]).value == [[5, None]]
    assert worker.run(BASE, "outcome", [5]).value is None
    stateful = BASE + "\ncount=0\ndef init(x):\n global count\n count+=1\n return count\n"
    assert worker.run(stateful, "init", [0]).value == 1
    assert worker.run(stateful, "init", [0]).value == 1


def test_private_files_env_proc_and_inherited_fds_are_not_exposed(worker, tmp_path, monkeypatch):
    secret = tmp_path / "evaluator-private.txt"
    secret.write_text("test-only-secret")
    monkeypatch.setenv("SDK_PRIVATE_TEST", "not-for-model")
    descriptor = os.open(secret, os.O_RDONLY)
    os.set_inheritable(descriptor, True)
    try:
        source = program("""import os
paths = [x, '/proc/1/root' + x, '/home', '/etc/passwd']
reads = []
for path in paths:
    try:
        reads.append(open(path).read())
    except OSError:
        reads.append(None)
leak = False
for fd in range(3, 128):
    try:
        leak = leak or b'test-only-secret' in os.read(fd, 128)
    except OSError:
        pass
return {'reads': reads, 'environment': os.environ.get('SDK_PRIVATE_TEST'), 'fd_leak': leak}""")
        result = worker.run(source, "init", [str(secret)])
        assert result.ok, result
        assert result.value == {"reads": [None] * 4, "environment": None, "fd_leak": False}
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("path", ["/written", "/dev/written", "/proc/written", "/worker.py"])
def test_filesystem_is_read_only(worker, path):
    result = worker.run(program("open(x, 'w').write('escape')\nreturn True"), "init", [path])
    assert not result.ok
    assert result.error and result.error.startswith("program_error:")


def test_host_network_and_raw_socket_syscall_are_blocked(worker):
    # Real host listener; a separate namespace plus seccomp must prevent contact.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = worker.run(
            program(
                "import socket\nsocket.create_connection(('127.0.0.1', x), timeout=1)\nreturn True"
            ),
            "init",
            [port],
        )
        assert not result.ok
    source = program(
        "import ctypes\nc=ctypes.CDLL(None, use_errno=True)\n"
        "r=c.syscall(41, 2, 1, 0)\nreturn [r,ctypes.get_errno()]"
    )
    assert worker.run(source, "init", [None]).value == [-1, 1]


@pytest.mark.parametrize(
    "code",
    [
        "import os\nos.fork()",
        "import os, sys\nos.execv(sys.executable, [sys.executable,'-c','pass'])",
        "import ctypes\nc=ctypes.CDLL(None, use_errno=True)\nassert c.unshare(0x10000000) == 0",
        "import ctypes\nc=ctypes.CDLL(None, use_errno=True)\nassert c.ptrace(0, 0, 0, 0) == 0",
    ],
)
def test_process_and_namespace_escape_paths_are_denied(worker, code):
    result = worker.run(program(code + "\nreturn True"), "init", [None])
    assert not result.ok, result


def test_memory_cpu_wall_and_output_limits(worker):
    memory = ProgramWorker(ProgramLimits(memory_bytes=64 * 1024**2))
    result = memory.run(program("a = bytearray(512 * 1024**2)\nreturn len(a)"), "init", [None])
    assert not result.ok and result.elapsed_seconds < 5
    cpu = ProgramWorker(ProgramLimits(cpu_seconds=1, wall_seconds=6))
    result = cpu.run(program("while True: pass"), "init", [None])
    assert not result.ok and result.error != "timeout" and result.elapsed_seconds < 5
    wall = ProgramWorker(ProgramLimits(wall_seconds=0.5))
    result = wall.run(program("import time\ntime.sleep(30)"), "init", [None])
    assert result.error == "timeout" and result.elapsed_seconds < 3
    output = ProgramWorker(ProgramLimits(output_bytes=2048))
    for stream in ("1", "2"):
        result = output.run(
            program(f"import os\nwhile True: os.write({stream}, b'x'*65536)"), "init", [None]
        )
        assert result.error == "output_limit"
        assert len(result.stderr.encode()) <= 2048


def test_malformed_output_and_missing_interface_are_rejected(worker):
    assert not worker.run("def init(x): return x", "init", [None]).ok
    forged = BASE + '\nimport os\nos.write(1,b\'{"ok":true,"value":1,"value":2}\')\nos._exit(0)\n'
    assert worker.run(forged, "init", [None]).error == "invalid_output"


def test_backend_unavailable_never_executes_source(monkeypatch, tmp_path):
    marker = tmp_path / "must-not-exist"
    monkeypatch.setattr("flynn_agents_sdk.program_worker.shutil.which", lambda _: None)
    result = ProgramWorker().run(f"open({str(marker)!r}, 'w').write('bad')", "init", [None])
    assert result.error == "unavailable"
    assert not marker.exists()


def test_bootstrap_confinement_failure_never_executes_source(worker, monkeypatch):
    command = worker._command()
    # Break trusted limit setup inside the real namespace; the model is never compiled.
    command[-1] = "invalid-memory-limit"
    monkeypatch.setattr(worker, "_command", lambda: command)
    source = "import os\nos.write(2, b'MODEL_EXECUTED')\n" + BASE
    result = worker.run(source, "init", [None])
    assert result.returncode == 78 and result.error == "execution_failed"
    assert result.value is None and result.stderr == "Program confinement setup failed\n"


def test_limits_and_input_checked_before_execution():
    with pytest.raises(ValueError):
        ProgramLimits(cpu_seconds=True)
    with pytest.raises(ValueError):
        ProgramWorker().run("x" * (128 * 1024 + 1), "init", [])
    with pytest.raises(ValueError):
        ProgramWorker().run(BASE, "init", [float("nan")])
    for wall in (True, "5", float("inf"), float("nan"), 0):
        with pytest.raises(ValueError):
            ProgramLimits(wall_seconds=wall)
    for operation, arguments in (("init", []), ("transition", [1]), ("render", {"x": 1})):
        with pytest.raises(ValueError):
            ProgramWorker().run(BASE, operation, arguments)
