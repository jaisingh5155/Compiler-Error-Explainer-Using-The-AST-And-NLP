#!/usr/bin/env python3
"""
tests/week8_verification/test_gate1_recompile.py

Verification tests for Gate 1: Recompile Check.
Confirms:
1. A well-behaved patch passes Gate 1 cleanly.
2. A patch that fixes the target error but introduces a NEW error fails Gate 1.
3. A patch that leaves the target error unresolved fails Gate 1.
4. Pre-existing warnings that were present before the patch are tolerated.
5. A patch introducing a brand-new warning fails Gate 1.
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from diagnostic import Diagnostic, Patch
from tools.verify_gates import gate_recompile_check


def test_gate1_valid_patch_passes():
    """Well-behaved patch fixes the target error with no side effects -> PASS."""
    orig_code = """
int main() {
    int x = 10
    return 0;
}
"""
    patched_code = """
int main() {
    int x = 10;
    return 0;
}
"""
    target_diag = Diagnostic(
        kind="error",
        message="expected ';' at end of declaration",
        line=3,
        category="syntax_error",
    )
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        diagnostic=target_diag,
        safety_level="S0",
    )

    res = gate_recompile_check(
        patch=patch,
        target_diagnostic=target_diag,
        original_source=orig_code,
    )
    assert res.passed is True, f"Gate 1 failed on valid patch: {res.reason}"
    assert "resolved" in res.reason.lower()


def test_gate1_fails_when_new_error_introduced():
    """
    Synthetic failure test for Gate 1:
    The patch fixes the target syntax error but introduces a NEW error (undeclared identifier).
    Must FAIL Gate 1 specifically because a new error appeared.
    """
    orig_code = """
int main() {
    int x = 10
    return 0;
}
"""
    # Fixes the semicolon on x, but inserts an undeclared symbol call
    patched_code = """
int main() {
    int x = 10;
    unresolved_external_symbol_xyz();
    return 0;
}
"""
    target_diag = Diagnostic(
        kind="error",
        message="expected ';' at end of declaration",
        line=3,
        category="syntax_error",
    )
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        diagnostic=target_diag,
        safety_level="S0",
    )

    res = gate_recompile_check(
        patch=patch,
        target_diagnostic=target_diag,
        original_source=orig_code,
    )
    assert res.passed is False, "Gate 1 should have failed due to new error introduced"
    assert res.details.get("failure_condition") == "new_diagnostics_introduced"
    assert "new error" in res.reason.lower() or "unresolved_external_symbol" in res.reason.lower()


def test_gate1_fails_when_target_diagnostic_unresolved():
    """Patch changes comments but does NOT fix the target error -> FAIL Gate 1."""
    orig_code = """
int main() {
    int x = 10
    return 0;
}
"""
    # Did not fix semicolon
    patched_code = """
// Added comment
int main() {
    int x = 10
    return 0;
}
"""
    target_diag = Diagnostic(
        kind="error",
        message="expected ';' at end of declaration",
        line=4,
        category="syntax_error",
    )
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        diagnostic=target_diag,
        safety_level="S0",
    )

    res = gate_recompile_check(
        patch=patch,
        target_diagnostic=target_diag,
        original_source=orig_code,
    )
    assert res.passed is False, "Gate 1 should have failed because target error was not resolved"
    assert res.details.get("failure_condition") == "target_unresolved"


def test_gate1_tolerates_preexisting_warnings():
    """
    Pre-existing warning (unused variable in untouched function) should be tolerated
    if it was already present before the patch.
    """
    orig_code = """
void helper() {
    int unused_pre = 123;
}
int main() {
    int x = 5
    return 0;
}
"""
    patched_code = """
void helper() {
    int unused_pre = 123;
}
int main() {
    int x = 5;
    return 0;
}
"""
    target_diag = Diagnostic(
        kind="error",
        message="expected ';' at end of declaration",
        line=6,
        category="syntax_error",
    )
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        diagnostic=target_diag,
        safety_level="S0",
    )

    res = gate_recompile_check(
        patch=patch,
        target_diagnostic=target_diag,
        original_source=orig_code,
    )
    assert res.passed is True, f"Gate 1 should tolerate pre-existing warning: {res.reason}"


def test_gate1_fails_when_new_warning_introduced():
    """A patch introducing a brand-new warning that was not present before must fail Gate 1."""
    orig_code = """
int main() {
    int x = 5
    return 0;
}
"""
    # Fixes semicolon, but adds an unused variable generating a warning on -Wall/-Wunused
    patched_code = """
int main() {
    int x = 5;
    [[maybe_unused]] int ok = 1;
    #pragma clang diagnostic push
    #pragma clang diagnostic warning "-Wunused-variable"
    int brand_new_unused_variable = 999;
    #pragma clang diagnostic pop
    return 0;
}
"""
    target_diag = Diagnostic(
        kind="error",
        message="expected ';' at end of declaration",
        line=3,
        category="syntax_error",
    )
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        diagnostic=target_diag,
        safety_level="S0",
    )

    res = gate_recompile_check(
        patch=patch,
        target_diagnostic=target_diag,
        original_source=orig_code,
    )
    assert res.passed is False, "Gate 1 should fail when a brand-new warning is introduced"
    assert res.details.get("failure_condition") == "new_diagnostics_introduced"


def test_gate1_target_resolved_with_multiple_identical_errors():
    """
    Task 3: Line-aware target diagnostic matching.
    File contains three identical 'expected ;' errors (lines 3, 4, 5).
    The patch fixes the second one (line 4).
    Target at line 4 is resolved; lines 3 and 5 are pre-existing, so Gate 1 passes.
    """
    orig_code = """
int main() {
    int a = 1
    int b = 2
    int c = 3
    return 0;
}
"""
    # Fix line 4 (int b = 2)
    patched_code = """
int main() {
    int a = 1
    int b = 2;
    int c = 3
    return 0;
}
"""
    target_diag = Diagnostic(
        kind="error",
        message="expected ';' at end of declaration",
        line=4,
        category="syntax_error",
    )
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        diagnostic=target_diag,
        safety_level="S0",
    )

    res = gate_recompile_check(
        patch=patch,
        target_diagnostic=target_diag,
        original_source=orig_code,
    )
    assert res.passed is True, f"Gate 1 should pass: {res.reason}"
    assert "resolved" in res.reason.lower()

