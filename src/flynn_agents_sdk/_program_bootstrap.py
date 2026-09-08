"""Trusted bootstrap, executed only inside ProgramWorker's isolated runtime."""

import ctypes
import errno
import json
import resource
import sys


def confine() -> None:
    cpu, memory = int(sys.argv[1]), int(sys.argv[2])
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    library.seccomp_release.restype = None
    # Default-deny: no network, process creation/exec, namespace changes, ptrace or mounts.
    context = library.seccomp_init(0x00050000 | errno.EPERM)
    if not context:
        raise RuntimeError("seccomp initialization failed")
    try:
        allowed = (
            "read write close fstat newfstatat statx lseek mmap mprotect munmap brk mremap "
            "madvise rt_sigaction rt_sigprocmask rt_sigreturn sigaltstack getpid gettid getppid "
            "exit exit_group futex clock_gettime clock_nanosleep nanosleep getrandom getcwd "
            "getdents64 openat readlink readlinkat access faccessat faccessat2 fcntl "
            "pread64 readv writev sched_yield uname getuid geteuid getgid getegid getrusage "
            "sysinfo times restart_syscall"
        )
        for name in allowed.split():
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number < 0 or library.seccomp_rule_add(context, 0x7FFF0000, number, 0) != 0:
                raise RuntimeError("seccomp rule installation failed")
        if library.seccomp_load(context) != 0:
            raise RuntimeError("seccomp load failed")
    finally:
        library.seccomp_release(context)


def main() -> None:
    # Setup failure exits before reading or compiling any untrusted program.
    try:
        confine()
    except BaseException:
        sys.stderr.write("Program confinement setup failed\n")
        raise SystemExit(78) from None
    try:
        request = json.load(sys.stdin)
        namespace: dict[str, object] = {"__name__": "generated_model"}
        exec(compile(request["source"], "<generated-model>", "exec"), namespace)
        if not all(
            callable(namespace.get(name)) for name in ("init", "transition", "render", "outcome")
        ):
            raise ValueError("Missing model interface")
        function = namespace[request["operation"]]
        assert callable(function)
        value = function(*request["arguments"])
        result = json.dumps({"ok": True, "value": value}, allow_nan=False)
    except BaseException as exc:
        result = json.dumps({"ok": False, "error": type(exc).__name__})
    sys.stdout.write(result)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
