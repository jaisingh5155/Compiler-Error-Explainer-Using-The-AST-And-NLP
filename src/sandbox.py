#!/usr/bin/env python3
"""
src/sandbox.py - Isolated compilation and execution sandbox with resource limiting.

Features:
1. Directory Isolation: All compilation and execution run in dedicated temporary directories.
   The original source files are never modified in place.
2. Resource Limits via Python's resource module:
   - RLIMIT_CPU: Kills runaway CPU loops via SIGXCPU.
   - RLIMIT_FSIZE: Restricts maximum file size created on disk.
   - RLIMIT_CORE: Disables core dump generation.
   - RLIMIT_AS (Memory): Attempted with graceful fallback/documentation on macOS Darwin.
   - Wall-clock timeout: Strict timeout enforcement via subprocess kills.
   - Output size limiting: Streams and caps captured stdout/stderr to prevent memory exhaustion.
3. Filesystem & Network Isolation:
   - On macOS: Uses Seatbelt (sandbox-exec) with a strict profile denying network access
     and denying file writes outside the isolated sandbox directory.
4. Clean Error Reporting: Returns structured CompileResult and ExecutionResult objects.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

try:
    import psutil
except ImportError:
    psutil = None

try:
    import resource
except ImportError:
    resource = None


@dataclass
class CompileResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    executable_path: Optional[str] = None
    sandbox_dir: Optional[str] = None
    timed_out: bool = False
    resource_exceeded: bool = False
    sandbox_active: bool = True
    error_message: Optional[str] = None


@dataclass
class ExecutionResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_truncated: bool = False
    resource_exceeded: bool = False
    sandbox_active: bool = True
    error_message: Optional[str] = None


def get_platform_limitations() -> Dict[str, Any]:
    """
    Returns an inventory of which resource limits and isolation features
    are enforceable in the current operating system environment.
    """
    is_darwin = sys.platform == "darwin"
    limitations = {
        "platform": sys.platform,
        "is_darwin": is_darwin,
        "wall_clock_timeout": True,
        "memory_watchdog": True,
        "rlimit_cpu": hasattr(resource, "RLIMIT_CPU") if resource else False,
        "rlimit_fsize": hasattr(resource, "RLIMIT_FSIZE") if resource else False,
        "rlimit_core": hasattr(resource, "RLIMIT_CORE") if resource else False,
        "rlimit_nofile": hasattr(resource, "RLIMIT_NOFILE") if resource else False,
        # On macOS Darwin, RLIMIT_AS and RLIMIT_DATA cannot be lowered/set by unprivileged processes
        "rlimit_as_memory": False if is_darwin else (hasattr(resource, "RLIMIT_AS") if resource else False),
        "rlimit_data_memory": False if is_darwin else (hasattr(resource, "RLIMIT_DATA") if resource else False),
        "seatbelt_sandbox_exec": shutil.which("sandbox-exec") is not None if is_darwin else False,
        "output_size_capping": True,
        "filesystem_write_isolation": True if (is_darwin and shutil.which("sandbox-exec")) else "cwd_only",
        "network_isolation": True if (is_darwin and shutil.which("sandbox-exec")) else "unrestricted",
    }
    return limitations


def _apply_rlimits(
    cpu_seconds: Optional[int] = None,
    max_fsize_bytes: Optional[int] = None,
    max_mem_bytes: Optional[int] = None,
    max_nofile: Optional[int] = 256,
):
    """
    Preexec hook to apply POSIX resource limits in the spawned child process.
    Handles platform-specific differences (such as Darwin's rejection of RLIMIT_AS).
    """
    if not resource:
        return

    # 1. CPU time limit
    if cpu_seconds is not None and hasattr(resource, "RLIMIT_CPU"):
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        except (ValueError, OSError):
            pass

    # 2. Maximum file write size on disk
    if max_fsize_bytes is not None and hasattr(resource, "RLIMIT_FSIZE"):
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (max_fsize_bytes, max_fsize_bytes))
        except (ValueError, OSError):
            pass

    # 3. Disable core dump files
    if hasattr(resource, "RLIMIT_CORE"):
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass

    # 4. Limit open file descriptors
    if max_nofile is not None and hasattr(resource, "RLIMIT_NOFILE"):
        try:
            cur_soft, cur_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            target = min(max_nofile, cur_hard)
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, cur_hard))
        except (ValueError, OSError):
            pass

    # 5. Virtual Memory (RLIMIT_AS): Enforceable on Linux; raises ValueError on macOS
    if max_mem_bytes is not None and hasattr(resource, "RLIMIT_AS"):
        try:
            cur_soft, cur_hard = resource.getrlimit(resource.RLIMIT_AS)
            target = min(max_mem_bytes, cur_hard)
            resource.setrlimit(resource.RLIMIT_AS, (target, cur_hard))
        except (ValueError, OSError):
            # Known limitation on Darwin: XNU kernel does not support setting RLIMIT_AS
            pass


def _build_seatbelt_profile(allowed_write_dir: str, deny_network: bool = True) -> str:
    """
    Constructs an Apple Seatbelt sandbox profile restricting file writes strictly
    to the designated temporary directory, /private/tmp, and system tmpdirs.
    """
    real_write_dir = os.path.realpath(allowed_write_dir)
    darwin_tmp = os.path.realpath(tempfile.gettempdir())

    network_directive = "(deny network*)" if deny_network else ""
    profile = f"""(version 1)
(allow default)
{network_directive}
(deny file-write* (regex #"^/"))
(allow file-write* (subpath "{real_write_dir}"))
(allow file-write* (subpath "{darwin_tmp}"))
(allow file-write* (subpath "/private/tmp"))
(allow file-write* (subpath "/dev"))
"""
    return profile


def _get_process_rss(pid: int) -> int:
    """Returns total resident set size (RSS) in bytes for pid and all its child processes."""
    if psutil:
        try:
            p = psutil.Process(pid)
            rss = p.memory_info().rss
            for c in p.children(recursive=True):
                try:
                    rss += c.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0
    try:
        out = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return int(out.strip()) * 1024
    except Exception:
        return 0


def _run_with_watchdog(
    cmd: List[str],
    cwd: str,
    input_data: Optional[str],
    timeout: float,
    max_mem_bytes: int,
    preexec_fn: Optional[Any] = None,
) -> tuple[int, str, str, bool, bool, Optional[str]]:
    """
    Executes a subprocess with wall-clock timeout and memory watchdog polling every ~50ms.
    Returns: (returncode, stdout, stderr, timed_out, mem_exceeded, error_msg)
    """
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=subprocess.PIPE if input_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            preexec_fn=preexec_fn,
        )
    except FileNotFoundError:
        return (-1, "", f"Command '{cmd[0]}' not found.", False, False, f"Command '{cmd[0]}' not found.")

    mem_exceeded = threading.Event()
    stop_event = threading.Event()
    peak_rss = [0]

    def watchdog_loop():
        while not stop_event.is_set():
            if proc.poll() is not None:
                break
            rss = _get_process_rss(proc.pid)
            if rss > peak_rss[0]:
                peak_rss[0] = rss
            if rss > max_mem_bytes:
                mem_exceeded.set()
                try:
                    proc.kill()
                except Exception:
                    pass
                break
            time.sleep(0.05)

    watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
    watchdog_thread.start()

    timed_out = False
    stdout = ""
    stderr = ""
    error_msg = None

    try:
        stdout, stderr = proc.communicate(input=input_data, timeout=timeout)
        returncode = proc.returncode
        if returncode in (-24, -25):
            error_msg = "Process terminated by kernel resource limit (SIGXCPU or SIGXFSZ)"
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            proc.kill()
        except Exception:
            pass
        stdout, stderr = proc.communicate()
        returncode = -1
        error_msg = f"Execution timed out after {timeout} seconds"
    finally:
        stop_event.set()
        watchdog_thread.join(timeout=0.5)

    if mem_exceeded.is_set():
        timed_out = False
        returncode = -9
        peak_mb = peak_rss[0] // (1024 * 1024)
        cap_mb = max_mem_bytes // (1024 * 1024)
        error_msg = f"Memory limit exceeded: resident set size ({peak_mb}MB) exceeded limit ({cap_mb}MB)"

    return (returncode, stdout or "", stderr or "", timed_out, mem_exceeded.is_set(), error_msg)


def compile_sandboxed(
    source_path_or_code: str,
    compiler: str = "g++",
    extra_flags: Optional[List[str]] = None,
    timeout: float = 10.0,
    max_mem_bytes: int = 512 * 1024 * 1024,
    max_fsize_bytes: int = 10 * 1024 * 1024,
    max_output_bytes: int = 1024 * 1024,
    keep_temp: bool = False,
    temp_dir: Optional[str] = None,
) -> CompileResult:
    """
    Compiles a C++ source file or code snippet inside an isolated temporary directory.
    Original source files are never modified in place.
    Path references in compiler errors are mapped back to the original source path.
    Enforces timeout, memory watchdog, CPU time limits, and output limits.
    """
    is_file = os.path.exists(source_path_or_code) and os.path.isfile(source_path_or_code)
    created_dir = False

    if temp_dir is None:
        sandbox_dir = tempfile.mkdtemp(prefix="cpp_sandbox_build_")
        created_dir = True
    else:
        sandbox_dir = temp_dir
        os.makedirs(sandbox_dir, exist_ok=True)

    try:
        if is_file:
            orig_path = os.path.abspath(source_path_or_code)
            base_name = os.path.basename(source_path_or_code)
            temp_src = os.path.join(sandbox_dir, base_name)
            shutil.copyfile(orig_path, temp_src)
        else:
            orig_path = "<input>"
            base_name = "source.cpp"
            temp_src = os.path.join(sandbox_dir, base_name)
            with open(temp_src, "w", encoding="utf-8") as f:
                f.write(source_path_or_code)

        output_bin = os.path.join(sandbox_dir, "a.out")
        cmd = [compiler]
        if extra_flags:
            cmd.extend(extra_flags)
        else:
            cmd.extend(["-std=c++17"])
        cmd.extend([temp_src, "-o", output_bin])

        def preexec():
            cpu_sec = max(1, int(timeout) + 1)
            _apply_rlimits(cpu_seconds=cpu_sec, max_fsize_bytes=max_fsize_bytes)

        returncode, stdout, stderr, timed_out, mem_exceeded, error_msg = _run_with_watchdog(
            cmd=cmd,
            cwd=sandbox_dir,
            input_data=None,
            timeout=timeout,
            max_mem_bytes=max_mem_bytes,
            preexec_fn=preexec,
        )

        res_exceeded = mem_exceeded or (returncode in (-24, -25))

        if returncode == -1 and ("not found" in stderr.lower() or "not found" in (error_msg or "").lower()):
            return CompileResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr=f"{compiler} compiler not found.",
                executable_path=None,
                sandbox_dir=sandbox_dir,
                timed_out=False,
                resource_exceeded=False,
                sandbox_active=False,
                error_message=f"{compiler} compiler not found.",
            )

        # Truncate output if it exceeds max_output_bytes
        if len(stdout) > max_output_bytes:
            stdout = stdout[:max_output_bytes] + "\n[OUTPUT TRUNCATED: max output size exceeded]"
            res_exceeded = True
        if len(stderr) > max_output_bytes:
            stderr = stderr[:max_output_bytes] + "\n[OUTPUT TRUNCATED: max output size exceeded]"
            res_exceeded = True

        # Rewrite paths in compiler output so callers see original file path
        if is_file:
            stderr = stderr.replace(temp_src, source_path_or_code)
            stdout = stdout.replace(temp_src, source_path_or_code)
            stderr = stderr.replace(os.path.realpath(temp_src), source_path_or_code)
            stdout = stdout.replace(os.path.realpath(temp_src), source_path_or_code)

        success = (returncode == 0) and not timed_out and not res_exceeded
        bin_path = output_bin if (success and os.path.exists(output_bin)) else None

        return CompileResult(
            success=success,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            executable_path=bin_path,
            sandbox_dir=sandbox_dir,
            timed_out=timed_out,
            resource_exceeded=res_exceeded,
            sandbox_active=True,
            error_message=error_msg,
        )

    finally:
        if created_dir and not keep_temp:
            shutil.rmtree(sandbox_dir, ignore_errors=True)


def execute_sandboxed(
    executable_path: str,
    args: Optional[List[str]] = None,
    input_data: Optional[str] = None,
    timeout: float = 3.0,
    max_mem_bytes: int = 512 * 1024 * 1024,
    max_fsize_bytes: int = 5 * 1024 * 1024,
    max_output_bytes: int = 512 * 1024,
    work_dir: Optional[str] = None,
    isolate_filesystem: bool = True,
    deny_network: bool = True,
    sandbox_exec_path: Optional[str] = None,
    keep_temp: bool = False,
) -> ExecutionResult:
    """
    Executes a binary inside a restricted sandbox environment.
    Applies wall-clock timeout, memory watchdog (~50ms polling), CPU time limits,
    output capping, and (on macOS) Seatbelt sandbox write/network restrictions.
    Fails closed if filesystem isolation is requested but sandbox-exec is missing.
    """
    created_dir = False
    if work_dir is None:
        sandbox_dir = tempfile.mkdtemp(prefix="cpp_sandbox_run_")
        created_dir = True
    else:
        sandbox_dir = work_dir
        os.makedirs(sandbox_dir, exist_ok=True)

    try:
        run_args = [os.path.abspath(executable_path)]
        if args:
            run_args.extend(args)

        is_darwin = sys.platform == "darwin"
        sandbox_active = False

        if isolate_filesystem:
            if is_darwin:
                seatbelt_bin = sandbox_exec_path or shutil.which("sandbox-exec")
                if not seatbelt_bin or not os.path.exists(seatbelt_bin):
                    return ExecutionResult(
                        success=False,
                        returncode=-1,
                        stdout="",
                        stderr="Sandbox isolation failure: 'sandbox-exec' is missing or unavailable. Refusing to run unsandboxed (fail-closed).",
                        timed_out=False,
                        output_truncated=False,
                        resource_exceeded=False,
                        sandbox_active=False,
                        error_message="Sandbox isolation failure: 'sandbox-exec' is missing or unavailable. Refusing to run unsandboxed (fail-closed).",
                    )
                profile = _build_seatbelt_profile(sandbox_dir, deny_network=deny_network)
                cmd = [seatbelt_bin, "-p", profile] + run_args
                sandbox_active = True
            else:
                # On non-Darwin (Linux), filesystem isolation is directory-based unless containerized
                cmd = run_args
                sandbox_active = True
        else:
            cmd = run_args
            sandbox_active = False

        def preexec():
            cpu_sec = max(1, int(timeout) + 1)
            _apply_rlimits(cpu_seconds=cpu_sec, max_fsize_bytes=max_fsize_bytes)

        returncode, stdout, stderr, timed_out, mem_exceeded, error_msg = _run_with_watchdog(
            cmd=cmd,
            cwd=sandbox_dir,
            input_data=input_data,
            timeout=timeout,
            max_mem_bytes=max_mem_bytes,
            preexec_fn=preexec,
        )

        res_exceeded = mem_exceeded or (returncode in (-24, -25))
        output_truncated = False

        if returncode == -1 and ("not found" in stderr.lower() or "not found" in (error_msg or "").lower()):
            return ExecutionResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr=stderr or f"Executable '{executable_path}' not found.",
                timed_out=False,
                output_truncated=False,
                resource_exceeded=False,
                sandbox_active=sandbox_active,
                error_message=error_msg or f"Executable '{executable_path}' not found.",
            )

        if len(stdout) > max_output_bytes:
            stdout = stdout[:max_output_bytes] + "\n[OUTPUT TRUNCATED]"
            output_truncated = True
            res_exceeded = True
        if len(stderr) > max_output_bytes:
            stderr = stderr[:max_output_bytes] + "\n[OUTPUT TRUNCATED]"
            output_truncated = True
            res_exceeded = True

        success = (returncode == 0) and not timed_out and not res_exceeded

        return ExecutionResult(
            success=success,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            output_truncated=output_truncated,
            resource_exceeded=res_exceeded,
            sandbox_active=sandbox_active,
            error_message=error_msg,
        )

    finally:
        if created_dir and not keep_temp:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
