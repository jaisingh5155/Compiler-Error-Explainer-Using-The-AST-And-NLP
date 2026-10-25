"""
tests/test_sanitizer_word_boundary.py
──────────────────────────────────────
Standalone regression test confirming that the pre-execution input sanitizer
(_sanitize_code in compiler_runner.py) correctly allows harmless functions
whose names contain 'system', 'exec', 'popen', 'fork' as substrings (e.g.
filesystem(), subsystem(), ecosystem(), execute(), reopen(), forklift()),
while still strictly blocking actual dangerous system calls (e.g. system(...),
exec(...), popen(...), fork(...)).
"""
import os
import sys
import tempfile
import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from compiler_runner import _sanitize_code, run_cpp_compiler


def test_sanitizer_allows_harmless_substring_function_names():
    """Verify functions containing 'system', 'exec', 'popen', 'fork' as substrings are permitted."""
    harmless_code = """
    #include <iostream>
    #include <string>

    void filesystem() {
        std::cout << "harmless filesystem function" << std::endl;
    }

    void subsystem_init() {
        std::cout << "harmless subsystem" << std::endl;
    }

    void ecosystem_check() {
        std::cout << "harmless ecosystem" << std::endl;
    }

    void execute_plan() {
        std::cout << "harmless execute" << std::endl;
    }

    void reopen_file() {
        std::cout << "harmless reopen" << std::endl;
    }

    void forklift_cargo() {
        std::cout << "harmless forklift" << std::endl;
    }

    int main() {
        filesystem();
        subsystem_init();
        ecosystem_check();
        execute_plan();
        reopen_file();
        forklift_cargo();
        return 0;
    }
    """
    assert _sanitize_code(harmless_code) is True


def test_sanitizer_blocks_genuine_dangerous_calls():
    """Verify genuine system(), exec(), popen(), fork() calls are strictly blocked."""
    dangerous_cases = [
        'int main() { system("ls"); return 0; }',
        'int main() { system ("ls"); return 0; }',
        'int main() { system    ("/bin/sh"); return 0; }',
        'int main() { exec("/bin/sh"); return 0; }',
        'int main() { popen("ls", "r"); return 0; }',
        'int main() { fork(); return 0; }',
    ]
    for case in dangerous_cases:
        assert _sanitize_code(case) is False, f"Sanitizer failed to block dangerous call in: {case}"


def test_compiler_runner_sec13_decoy_filesystem_clean():
    """Verify benchmark/security/sec13_decoy_filesystem.cpp compiles cleanly with no security error."""
    sec13_path = os.path.join(PROJECT, "benchmark", "security", "sec13_decoy_filesystem.cpp")
    errors = run_cpp_compiler(sec13_path)
    # With word boundary anchor, it should compile clean (0 errors)
    assert errors == [], f"Expected 0 compile errors for sec13_decoy_filesystem.cpp, got: {errors}"


def test_compiler_runner_blocks_malicious_system_call():
    """Verify run_cpp_compiler still returns synthetic security error on actual system() call."""
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as f:
        f.write('#include <cstdlib>\nint main() { system("rm -rf /"); return 0; }\n')
        tpath = f.name
    try:
        errors = run_cpp_compiler(tpath)
        assert len(errors) == 1
        assert "Security Error" in errors[0]["message"]
        assert errors[0]["type"] == "error"
    finally:
        if os.path.exists(tpath):
            os.unlink(tpath)
