"""Opt-in Linux program worker; no fallback to unconfined subprocess execution."""

import json
import math
import os
import platform
import selectors
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Operation = Literal["init", "transition", "render", "outcome"]


@dataclass(frozen=True)
class ProgramLimits:
    cpu_seconds: int = 2
    memory_bytes: int = 256 * 1024 * 1024
    wall_seconds: float = 5.0
    output_bytes: int = 1024 * 1024
    input_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for value, low, high in (
            (self.cpu_seconds, 1, 60),
            (self.memory_bytes, 64 * 1024 * 1024, 2 * 1024**3),
            (self.output_bytes, 1024, 2 * 1024**2),
            (self.input_bytes, 1024, 2 * 1024**2),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Invalid program limit")
        if (
            type(self.wall_seconds) not in (int, float)
            or not math.isfinite(self.wall_seconds)
            or not 0 < self.wall_seconds <= 120
        ):
            raise ValueError("Invalid wall limit")


@dataclass(frozen=True)
class ProgramResult:
    ok: bool
    value: Any = None
    error: str | None = None
    returncode: int | None = None
    elapsed_seconds: float = 0.0
    stderr: str = ""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate output key")
        result[key] = value
    return result


def _nonfinite(value: str) -> Any:
    raise ValueError("Non-finite program output")


class ProgramWorker:
    """One process per call, with JSON state explicitly threaded by the application.

    Supported backend: Debian/Ubuntu-style Linux x86-64, system Python under /usr,
    Bubblewrap with user namespaces, and libseccomp. No host workspace/env is granted.
    Model output is untrusted evidence, never an SDK semantic acceptance verdict.
    """

    def __init__(self, limits: ProgramLimits | None = None) -> None:
        self.limits = limits or ProgramLimits()

    def _command(self) -> list[str]:
        binary = shutil.which("bwrap")
        python = Path("/usr/bin/python3").resolve()
        if platform.system() != "Linux" or platform.machine() != "x86_64" or not binary:
            raise RuntimeError("Required Linux confinement backend unavailable")
        if not python.is_file() or python.parent != Path("/usr/bin"):
            raise RuntimeError("Supported system Python unavailable")
        metadata = (
            subprocess.run(
                [
                    str(python),
                    "-I",
                    "-S",
                    "-c",
                    "import sysconfig; print(sysconfig.get_path('stdlib'))",
                ],
                capture_output=True,
                check=True,
                timeout=3,
                env={},
            )
            .stdout.decode()
            .strip()
        )
        stdlib = Path(metadata).resolve()
        if stdlib.parent != Path("/usr/lib") or not stdlib.name.startswith("python3."):
            raise RuntimeError("Unsupported runtime layout")
        libraries = Path("/usr/lib/x86_64-linux-gnu")
        if not (libraries / "libseccomp.so.2").exists():
            raise RuntimeError("libseccomp unavailable")
        return [
            binary,
            "--unshare-all",
            "--unshare-user",
            "--disable-userns",
            "--assert-userns-disabled",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--ro-bind",
            str(python),
            str(python),
            "--ro-bind",
            str(stdlib),
            str(stdlib),
            "--ro-bind",
            str(libraries),
            str(libraries),
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib/x86_64-linux-gnu",
            "/lib64",
            "--ro-bind",
            str(Path(__file__).with_name("_program_bootstrap.py")),
            "/worker.py",
            "--proc",
            "/proc",
            "--remount-ro",
            "/proc",
            "--dev",
            "/dev",
            "--remount-ro",
            "/dev",
            "--remount-ro",
            "/",
            "--chdir",
            "/",
            "--",
            str(python),
            "-I",
            "-S",
            "-B",
            "/worker.py",
            str(self.limits.cpu_seconds),
            str(self.limits.memory_bytes),
        ]

    def run(self, source: str, operation: Operation, arguments: list[Any]) -> ProgramResult:
        if operation not in ("init", "transition", "render", "outcome"):
            raise ValueError("Unsupported operation")
        if not isinstance(source, str) or len(source.encode()) > 128 * 1024:
            raise ValueError("Program source exceeds limit")
        arity = 2 if operation == "transition" else 1
        if not isinstance(arguments, list) or len(arguments) != arity:
            raise ValueError(f"{operation} requires an argument array of length {arity}")
        payload = json.dumps(
            {"source": source, "operation": operation, "arguments": arguments}, allow_nan=False
        ).encode()
        if len(payload) > self.limits.input_bytes:
            raise ValueError("Program input exceeds limit")
        start = time.monotonic()
        try:
            command = self._command()
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return ProgramResult(
                False,
                error="unavailable",
                stderr=str(exc),
                elapsed_seconds=time.monotonic() - start,
            )
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={},
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            return ProgramResult(
                False,
                error="unavailable",
                stderr=str(exc),
                elapsed_seconds=time.monotonic() - start,
            )
        assert (
            process.stdin is not None and process.stdout is not None and process.stderr is not None
        )

        input_pipe = process.stdin

        def send() -> None:
            try:
                with input_pipe:
                    input_pipe.write(payload)
            except (BrokenPipeError, OSError):
                pass

        writer = threading.Thread(target=send, daemon=True)
        writer.start()
        output, errors = bytearray(), bytearray()
        failure = None
        try:
            with selectors.DefaultSelector() as selector:
                for pipe, target in ((process.stdout, output), (process.stderr, errors)):
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, target)
                while selector.get_map():
                    remaining = self.limits.wall_seconds - (time.monotonic() - start)
                    if remaining <= 0:
                        failure = "timeout"
                        break
                    for key, _ in selector.select(min(remaining, 0.05)):
                        data = os.read(key.fd, 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        room = self.limits.output_bytes - len(output) - len(errors)
                        key.data.extend(data[:room])
                        if len(data) > room:
                            failure = "output_limit"
                            break
                    if failure:
                        break
                if not failure:
                    remaining = self.limits.wall_seconds - (time.monotonic() - start)
                    try:
                        process.wait(timeout=max(remaining, 0.001))
                    except subprocess.TimeoutExpired:
                        failure = "timeout"
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            writer.join(timeout=1)
            process.stdout.close()
            process.stderr.close()
        elapsed = time.monotonic() - start
        stderr = errors.decode(errors="replace")
        if failure or process.returncode:
            return ProgramResult(
                False,
                error=failure or "execution_failed",
                returncode=process.returncode,
                elapsed_seconds=elapsed,
                stderr=stderr,
            )
        try:
            result = json.loads(output, object_pairs_hook=_strict_object, parse_constant=_nonfinite)
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise ValueError("Malformed result")
            if result["ok"] and set(result) == {"ok", "value"}:
                return ProgramResult(
                    True, result["value"], returncode=0, elapsed_seconds=elapsed, stderr=stderr
                )
            if (
                not result["ok"]
                and set(result) == {"ok", "error"}
                and isinstance(result["error"], str)
            ):
                return ProgramResult(
                    False,
                    error="program_error:" + result["error"],
                    returncode=0,
                    elapsed_seconds=elapsed,
                    stderr=stderr,
                )
        except (ValueError, UnicodeError, RecursionError):
            pass
        return ProgramResult(
            False, error="invalid_output", returncode=0, elapsed_seconds=elapsed, stderr=stderr
        )
