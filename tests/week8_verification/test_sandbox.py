#!/usr/bin/env python3
"""
tests/week8_verification/test_sandbox.py

Week 8 Part 1 Verification Suite:
1. Normal compilation sanity test through sandbox
2. Timeout enforcement test (infinite loop process killed cleanly without hanging)
3. Filesystem isolation test (blocked from writing outside temp directory)
4. Resource limit error reporting test
"""

import os
import shutil
import sys
import tempfile
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from sandbox import compile_sandboxed, execute_sandboxed, get_platform_limitations
from compiler_runner import run_cpp_compiler


def test_normal_compile_and_execute_sanity():
    """Verify normal valid C++ programs compile and execute cleanly through sandbox."""
    code = """
#include <iostream>
int main() {
    std::cout << "sandbox_sanity_ok" << std::endl;
    return 0;
}
"""
    comp_res = compile_sandboxed(code, keep_temp=True)
    try:
        assert comp_res.success, f"Compilation failed: {comp_res.stderr}"
        assert comp_res.executable_path is not None
        assert os.path.exists(comp_res.executable_path)

        exec_res = execute_sandboxed(comp_res.executable_path, timeout=3.0)
        assert exec_res.success, f"Execution failed: {exec_res.stderr}"
        assert exec_res.returncode == 0
        assert "sandbox_sanity_ok" in exec_res.stdout
        assert not exec_res.timed_out
    finally:
        if comp_res.sandbox_dir and os.path.exists(comp_res.sandbox_dir):
            shutil.rmtree(comp_res.sandbox_dir, ignore_errors=True)


def test_compiler_runner_integration_sanity():
    """Verify compiler_runner.run_cpp_compiler works transparently through sandbox."""
    cl01_path = os.path.join(BASE_DIR, "benchmark", "clean", "cl01_hello.cpp")
    errors = run_cpp_compiler(cl01_path)
    assert errors == [], f"Expected 0 errors on clean file, got: {errors}"

    sx01_path = os.path.join(BASE_DIR, "benchmark", "syntax", "sx01_missing_semi_decl.cpp")
    sx_errors = run_cpp_compiler(sx01_path)
    assert len(sx_errors) >= 1
    assert sx_errors[0]["file"] == sx01_path
    assert "expected ';'" in sx_errors[0]["message"]


def test_timeout_kills_runaway_process_cleanly():
    """
    Verification Requirement 1:
    Confirm the sandbox kills a deliberately resource-heavy runaway process (infinite loop)
    via timeout rather than hanging the pipeline, with a clean reported failure.
    """
    code = """
int main() {
    volatile int x = 0;
    while (true) {
        x++;
    }
    return 0;
}
"""
    comp_res = compile_sandboxed(code, keep_temp=True)
    try:
        assert comp_res.success, f"Compile failed: {comp_res.stderr}"
        assert comp_res.executable_path is not None

        # Execute with 1.0 second timeout
        exec_res = execute_sandboxed(comp_res.executable_path, timeout=1.0)
        
        # Must report timeout or resource termination cleanly — not a crash, not a hang
        assert exec_res.timed_out or exec_res.resource_exceeded, "Expected runaway loop to be terminated by timeout/resource limit"
        assert not exec_res.success, "Runaway execution should not report success"
        assert exec_res.error_message is not None
        assert "timed out" in exec_res.error_message.lower() or "resource limit" in exec_res.error_message.lower()
    finally:
        if comp_res.sandbox_dir and os.path.exists(comp_res.sandbox_dir):
            shutil.rmtree(comp_res.sandbox_dir, ignore_errors=True)


def test_filesystem_isolation_blocks_escape_write():
    """
    Verification Requirement 2:
    Confirm the sandbox cannot write outside its designated temp directory.
    Attempt a path escape / absolute-path write from within a sandboxed process
    and confirm it is blocked or contained, without creating the external file.
    """
    escape_target = os.path.expanduser("~/sandbox_escape_test_blocked.txt")
    if os.path.exists(escape_target):
        os.remove(escape_target)

    code = f"""
#include <fstream>
#include <iostream>

int main() {{
    std::ofstream out("{escape_target}");
    if (!out.is_open()) {{
        std::cerr << "ESCAPE_WRITE_BLOCKED" << std::endl;
        return 13;
    }}
    out << "compromised" << std::endl;
    out.close();
    return 0;
}}
"""
    comp_res = compile_sandboxed(code, keep_temp=True)
    try:
        assert comp_res.success, f"Compile failed: {comp_res.stderr}"
        
        exec_res = execute_sandboxed(comp_res.executable_path, timeout=3.0)
        
        # Verify the escape target file was NOT created on disk
        assert not os.path.exists(escape_target), "CRITICAL: Sandbox failed to prevent write outside temp directory!"
        # Verify the process failed to open/write the file
        assert exec_res.returncode != 0, f"Expected non-zero returncode on blocked write, got: {exec_res.returncode}"
    finally:
        if os.path.exists(escape_target):
            os.remove(escape_target)
        if comp_res.sandbox_dir and os.path.exists(comp_res.sandbox_dir):
            shutil.rmtree(comp_res.sandbox_dir, ignore_errors=True)


def test_relative_path_escape_blocked():
    """Verify relative traversal (../..) cannot escape the sandbox boundary."""
    code = """
#include <fstream>
#include <iostream>

int main() {
    std::ofstream out("../../relative_escape_attempt.txt");
    if (!out.is_open()) {
        std::cerr << "RELATIVE_ESCAPE_BLOCKED" << std::endl;
        return 17;
    }
    out << "should_not_exist" << std::endl;
    out.close();
    return 0;
}
"""
    comp_res = compile_sandboxed(code, keep_temp=True)
    try:
        assert comp_res.success, f"Compile failed: {comp_res.stderr}"
        exec_res = execute_sandboxed(comp_res.executable_path, timeout=3.0)
        
        # Check parent directories for leaked file
        parent_dir = os.path.dirname(comp_res.sandbox_dir)
        grandparent_dir = os.path.dirname(parent_dir)
        leaked1 = os.path.join(parent_dir, "relative_escape_attempt.txt")
        leaked2 = os.path.join(grandparent_dir, "relative_escape_attempt.txt")
        
        assert not os.path.exists(leaked1)
        assert not os.path.exists(leaked2)
        assert exec_res.returncode != 0
    finally:
        if comp_res.sandbox_dir and os.path.exists(comp_res.sandbox_dir):
            shutil.rmtree(comp_res.sandbox_dir, ignore_errors=True)


def test_platform_limitations_structure():
    """Verify get_platform_limitations returns all required fields."""
    lims = get_platform_limitations()
    assert "platform" in lims
    assert "wall_clock_timeout" in lims
    assert "rlimit_cpu" in lims
    assert "rlimit_fsize" in lims
    assert "rlimit_as_memory" in lims
    assert "filesystem_write_isolation" in lims
    assert "network_isolation" in lims
    if sys.platform == "darwin":
        assert lims["is_darwin"] is True
        # Documented macOS limitation: RLIMIT_AS cannot be lowered/enforced via setrlimit
        assert lims["rlimit_as_memory"] is False
    assert lims.get("memory_watchdog") is True


def test_memory_watchdog_kills_memory_hog():
    """
    Verification Requirement 1:
    Confirm the memory watchdog polls resident memory (~50ms) and SIGKILLs
    a memory-hog program exceeding the cap before wall-clock timeout fires.
    Program is capped at 100MB so machine is never endangered even if watchdog fails.
    """
    code = """
#include <vector>
#include <chrono>
#include <thread>
#include <iostream>

int main() {
    std::vector<std::vector<char>> chunks;
    // Bounded allocation: 20 chunks of 5MB = 100MB max
    for (int i = 0; i < 20; ++i) {
        chunks.emplace_back(5 * 1024 * 1024, (char)i);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    std::cout << "finished_all_chunks" << std::endl;
    return 0;
}
"""
    comp_res = compile_sandboxed(code, keep_temp=True)
    try:
        assert comp_res.success, f"Compile failed: {comp_res.stderr}"
        # Set max_mem_bytes to 25MB with 5.0s timeout
        exec_res = execute_sandboxed(
            comp_res.executable_path,
            timeout=5.0,
            max_mem_bytes=25 * 1024 * 1024,
        )

        assert not exec_res.success, "Memory hog should not report success"
        assert exec_res.resource_exceeded is True, "Expected resource_exceeded to be True"
        assert exec_res.timed_out is False, "Must be killed by memory watchdog, NOT timeout"
        assert exec_res.error_message is not None
        assert "memory limit exceeded" in exec_res.error_message.lower()
        assert exec_res.returncode == -9
    finally:
        if comp_res.sandbox_dir and os.path.exists(comp_res.sandbox_dir):
            shutil.rmtree(comp_res.sandbox_dir, ignore_errors=True)


def test_filesystem_isolation_positive_control():
    """
    Verification Requirement 2:
    Positive control for the isolation test: run the same escape-attempt program
    UNSANDBOXED (isolate_filesystem=False), writing to an external path,
    and assert the write succeeds.
    This proves the blocked write in the sandboxed test is caused by Seatbelt
    and not a bad path.
    """
    target_path = os.path.expanduser("~/sandbox_positive_control_probe.txt")
    if os.path.exists(target_path):
        os.remove(target_path)

    code = f"""
#include <fstream>
#include <iostream>

int main() {{
    std::ofstream out("{target_path}");
    if (!out.is_open()) {{
        std::cerr << "WRITE_FAILED" << std::endl;
        return 13;
    }}
    out << "positive_control_data" << std::endl;
    out.close();
    return 0;
}}
"""
    comp_res = compile_sandboxed(code, keep_temp=True)
    try:
        assert comp_res.success, f"Compile failed: {comp_res.stderr}"

        # 1. Sandboxed run: MUST BE BLOCKED
        sandboxed_res = execute_sandboxed(comp_res.executable_path, isolate_filesystem=True, timeout=3.0)
        assert sandboxed_res.returncode != 0, "Sandboxed execution should have blocked write"
        assert not os.path.exists(target_path), "File should NOT exist after sandboxed execution"

        # 2. Positive control (unsandboxed run): MUST SUCCEED
        unsandboxed_res = execute_sandboxed(comp_res.executable_path, isolate_filesystem=False, timeout=3.0)
        assert unsandboxed_res.returncode == 0, f"Unsandboxed run failed: {unsandboxed_res.stderr}"
        assert os.path.exists(target_path), "File MUST exist after unsandboxed positive control run"
        with open(target_path) as f:
            content = f.read().strip()
        assert content == "positive_control_data"
    finally:
        if os.path.exists(target_path):
            os.remove(target_path)
        if comp_res.sandbox_dir and os.path.exists(comp_res.sandbox_dir):
            shutil.rmtree(comp_res.sandbox_dir, ignore_errors=True)


def test_fail_closed_when_sandbox_exec_missing():
    """
    Verification Requirement 3:
    When sandbox-exec is missing or unavailable, execute_sandboxed() must fail closed:
    refuse to run the compiled program unsandboxed, report a clear error,
    and report sandbox_active=False.
    """
    code = """
#include <iostream>
int main() {
    std::cout << "should_not_run_unsandboxed" << std::endl;
    return 0;
}
"""
    comp_res = compile_sandboxed(code, keep_temp=True)
    try:
        assert comp_res.success, f"Compile failed: {comp_res.stderr}"

        # Simulate missing sandbox-exec by providing nonexistent path
        fake_sandbox_exec = "/nonexistent/usr/bin/sandbox-exec"
        exec_res = execute_sandboxed(
            comp_res.executable_path,
            sandbox_exec_path=fake_sandbox_exec,
            isolate_filesystem=True,
        )

        assert exec_res.success is False
        assert exec_res.sandbox_active is False
        assert exec_res.returncode == -1
        assert exec_res.error_message is not None
        assert "refusing to run unsandboxed" in exec_res.error_message.lower() or "missing" in exec_res.error_message.lower()
        # Verify the program was NEVER actually executed
        assert "should_not_run_unsandboxed" not in exec_res.stdout
    finally:
        if comp_res.sandbox_dir and os.path.exists(comp_res.sandbox_dir):
            shutil.rmtree(comp_res.sandbox_dir, ignore_errors=True)
