#!/usr/bin/env python3
"""
tests/week8_verification/test_end_to_end_gate_failure.py
────────────────────────────────────────────────────────
End-to-end integration tests for multi-gate verification wired into planner.py.

Verifies:
1. End-to-end Gate 1 failure: patch introducing new error/warning fails verification,
   is rolled back to original file content, and is reported as suggestion-only.
2. End-to-end Gate 2 failure: patch with excessive diff size fails verification,
   is rolled back to original file content, and is reported as suggestion-only.
3. End-to-end Gate 3 failure: patch deleting a function fails verification,
   is rolled back to original file content, and is reported as suggestion-only.
4. End-to-end Gate 4 failure: patch introducing a security regression fails verification,
   is rolled back to original file content, and is reported as suggestion-only.
5. Trace log confirmation: planner's trace log records gate-level pass/fail detail
   including failing_gate and gate_details on every patch attempt.
6. Clean patch application: a valid patch passing all gates is auto-applied and achieves
   clean compilation.
"""

import os
import sys
import tempfile
import unittest.mock as mock
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from diagnostic import Diagnostic, Patch, ProgramModel
from planner import Planner, run_planner
from tools.verify import verify


def test_end_to_end_gate1_failure_rollback_and_suggestion():
    """
    Candidate patch that introduces a brand new error must fail Gate 1,
    roll back file to pre-patch state, and downgrade patch to suggestion-only.
    """
    orig_content = """#include <iostream>
int main() {
    int x = 5
    return 0;
}
"""
    # Bad patch that fixes missing semicolon on x, but introduces an undeclared symbol foo
    bad_patched = """#include <iostream>
int main() {
    int x = 5;
    foo = 10;
    return 0;
}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as tf:
        tf.write(orig_content)
        tpath = tf.name

    try:
        # Mock repair to return this bad patch
        with mock.patch("planner.repair") as mock_rep:
            mock_rep.return_value = Patch(
                original_file=tpath,
                patched_source=bad_patched,
                diff="- int x = 5\n+ int x = 5;\n+ foo = 10;",
                safety_level="S0",
                safety_tier=1,
            )
            result = run_planner(tpath, max_iterations=2, backup=True)

        # File must be rolled back to original content
        with open(tpath) as f:
            final_content = f.read()
        assert final_content == orig_content, "File was not rolled back to original content after Gate 1 failure"

        # Planner did not auto-apply bad patch
        assert len(result.patches_applied) == 0
        assert result.status != "success"

        # Patch must be recorded as suggestion-only
        assert len(result.suggestions) >= 1
        assert result.suggestions[0].suggestion_only is True

        # Trace log must contain failing_gate and gate_details
        verify_entries = [e for e in result.trace_log if e.get("tool_called") == "verify"]
        assert len(verify_entries) >= 1
        last_v = verify_entries[-1]
        assert last_v.get("failing_gate") == "gate1_recompile"
        assert "gate1_recompile" in last_v.get("output_summary")
        assert "gate_details" in last_v
    finally:
        if os.path.exists(tpath):
            os.unlink(tpath)
        if os.path.exists(tpath + ".bak"):
            os.unlink(tpath + ".bak")


def test_end_to_end_gate2_failure_rollback_and_suggestion():
    """
    Candidate patch tagged S0 that modifies 15 lines (exceeding S0 threshold of 3 lines)
    must fail Gate 2, roll back, and be marked suggestion-only.
    """
    orig_content = """#include <iostream>
int main() {
    int x = 5
    return 0;
}
"""
    # 15 lines of additions
    lines_added = "\n".join([f"    int y{i} = {i};" for i in range(15)])
    bad_patched = f"""#include <iostream>
int main() {{
    int x = 5;
{lines_added}
    return 0;
}}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as tf:
        tf.write(orig_content)
        tpath = tf.name

    try:
        with mock.patch("planner.repair") as mock_rep:
            diff_str = "\n".join([f"+ int y{i} = {i};" for i in range(15)])
            mock_rep.return_value = Patch(
                original_file=tpath,
                patched_source=bad_patched,
                diff=diff_str,
                safety_level="S0",
                safety_tier=1,
            )
            result = run_planner(tpath, max_iterations=2, backup=True)

        with open(tpath) as f:
            final_content = f.read()
        assert final_content == orig_content

        assert len(result.patches_applied) == 0
        assert len(result.suggestions) >= 1
        assert result.suggestions[0].suggestion_only is True

        verify_entries = [e for e in result.trace_log if e.get("tool_called") == "verify"]
        assert len(verify_entries) >= 1
        assert verify_entries[-1].get("failing_gate") == "gate2_diff_size"
    finally:
        if os.path.exists(tpath):
            os.unlink(tpath)
        if os.path.exists(tpath + ".bak"):
            os.unlink(tpath + ".bak")


def test_end_to_end_gate3_failure_rollback_and_suggestion():
    """
    Candidate patch that compiles cleanly but deletes a function must fail Gate 3,
    roll back to pre-patch state, and be marked suggestion-only.
    """
    orig_content = """#include <iostream>
int helper() {
    return 42;
}
int main() {
    int x = 10
    return 0;
}
"""
    # Fixes x, but removes helper() entirely! Compiles cleanly, but alters AST structure.
    bad_patched = """#include <iostream>
int main() {
    int x = 10;
    return 0;
}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as tf:
        tf.write(orig_content)
        tpath = tf.name

    try:
        with mock.patch("planner.repair") as mock_rep:
            mock_rep.return_value = Patch(
                original_file=tpath,
                patched_source=bad_patched,
                diff="- int helper() { return 42; }\n+ int x = 10;",
                safety_level="S1",
                safety_tier=2,
            )
            result = run_planner(tpath, max_iterations=2, backup=True)

        with open(tpath) as f:
            final_content = f.read()
        assert final_content == orig_content

        assert len(result.patches_applied) == 0
        assert len(result.suggestions) >= 1
        assert result.suggestions[0].suggestion_only is True

        verify_entries = [e for e in result.trace_log if e.get("tool_called") == "verify"]
        assert len(verify_entries) >= 1
        assert verify_entries[-1].get("failing_gate") == "gate3_ast_diff"
    finally:
        if os.path.exists(tpath):
            os.unlink(tpath)
        if os.path.exists(tpath + ".bak"):
            os.unlink(tpath + ".bak")


def test_end_to_end_gate4_failure_rollback_and_suggestion():
    """
    Candidate patch that fixes syntax without warnings but introduces a null pointer
    dereference (CWE-476) must fail Gate 4, roll back to pre-patch state, and be marked suggestion-only.
    """
    orig_content = """#include <iostream>
int main() {
    int x = 5
    return 0;
}
"""
    # Fixes semicolon on x, but introduces null pointer dereference
    bad_patched = """#include <iostream>
int main() {
    int x = 5;
    int* ptr = nullptr;
    *ptr = 42;
    return 0;
}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as tf:
        tf.write(orig_content)
        tpath = tf.name

    try:
        with mock.patch("planner.repair") as mock_rep:
            mock_rep.return_value = Patch(
                original_file=tpath,
                patched_source=bad_patched,
                diff="+ int* ptr = nullptr;\n+ *ptr = 42;",
                safety_level="S1",
                safety_tier=2,
            )
            result = run_planner(tpath, max_iterations=2, backup=True)

        with open(tpath) as f:
            final_content = f.read()
        assert final_content == orig_content

        assert len(result.patches_applied) == 0
        assert len(result.suggestions) >= 1
        assert result.suggestions[0].suggestion_only is True

        verify_entries = [e for e in result.trace_log if e.get("tool_called") == "verify"]
        assert len(verify_entries) >= 1
        assert verify_entries[-1].get("failing_gate") == "gate4_security_regression"
    finally:
        if os.path.exists(tpath):
            os.unlink(tpath)
        if os.path.exists(tpath + ".bak"):
            os.unlink(tpath + ".bak")


def test_end_to_end_clean_patch_applies_successfully():
    """
    A well-behaved syntax patch that passes all gates must be auto-applied,
    recorded in patches_applied, and heal the file to clean status.
    """
    orig_content = """#include <iostream>
int main() {
    int x = 42
    return 0;
}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as tf:
        tf.write(orig_content)
        tpath = tf.name

    try:
        # Safe universal review mode: candidate patch verified and queued into pending_patches, 0 direct disk writes
        res_safe = run_planner(tpath, max_iterations=3, backup=True, apply_to_disk=False)
        assert res_safe.clean is True
        assert len(res_safe.pending_patches) >= 1
        assert len(res_safe.patches_applied) == 0
        with open(tpath) as f:
            assert f.read() == orig_content, "File was modified in safe universal review mode!"

        # Explicit apply mode (User Accept or CLI --apply)
        result = run_planner(tpath, max_iterations=3, backup=True, apply_to_disk=True)
        assert result.clean is True
        assert len(result.patches_applied) >= 1

        with open(tpath) as f:
            final_content = f.read()
        assert "int x = 42;" in final_content

        verify_entries = [e for e in result.trace_log if e.get("tool_called") == "verify"]
        assert len(verify_entries) >= 1
        assert verify_entries[-1].get("failing_gate") is None
        assert "passed=True" in verify_entries[-1].get("output_summary")
        assert len(verify_entries[-1].get("gate_details", [])) >= 4
    finally:
        if os.path.exists(tpath):
            os.unlink(tpath)
        if os.path.exists(tpath + ".bak"):
            os.unlink(tpath + ".bak")
