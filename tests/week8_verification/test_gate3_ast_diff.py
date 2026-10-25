#!/usr/bin/env python3
"""
tests/week8_verification/test_gate3_ast_diff.py
───────────────────────────────────────────────
Verification tests for Gate 3: AST-Diff Structural Check.
Confirms:
1. A well-behaved patch preserving function structure passes Gate 3.
2. Synthetic bad patch that deletes a function fails Gate 3 (specifically Gate 3).
3. Synthetic bad patch that alters a function signature (parameter types / return type) fails Gate 3.
4. Synthetic bad patch that introduces an unexpected new function fails Gate 3.
5. Pre-existing functions unblocked by fixing syntax/brace errors pass Gate 3.
6. Independence: A patch that compiles cleanly (passes Gate 1) fails Gate 3 if a function was removed.
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from diagnostic import Diagnostic, Patch
from tools.verify_gates import gate_ast_diff_check, gate_recompile_check


def test_gate3_valid_patch_preserves_structure():
    """Well-behaved patch fixes syntax while keeping all function signatures intact -> PASS."""
    orig_code = """
int compute(int x, int y) {
    int res = x + y
    return res;
}
int main() {
    return compute(1, 2);
}
"""
    patched_code = """
int compute(int x, int y) {
    int res = x + y;
    return res;
}
int main() {
    return compute(1, 2);
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched_code)
    res = gate_ast_diff_check(patch, original_source=orig_code)
    assert res.passed is True
    assert "preserved" in res.reason.lower()


def test_gate3_fails_when_function_deleted():
    """
    Synthetic failure test for Gate 3:
    A patch 'fixes' a compile problem by deleting the offending helper function entirely.
    Must FAIL Gate 3 specifically with function_removed condition.
    """
    orig_code = """
int broken_helper(int a) {
    int x = a * 2;
    return x;
}
int main() {
    return 0;
}
"""
    # Helper deleted
    patched_code = """
int main() {
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched_code)
    res = gate_ast_diff_check(patch, original_source=orig_code)
    assert res.passed is False
    assert res.details.get("failure_condition") == "function_removed"
    assert "broken_helper" in res.reason


def test_gate3_fails_when_function_signature_changed():
    """
    Synthetic failure test for Gate 3:
    A patch modifies the parameter types or return type of an existing function.
    Must FAIL Gate 3 with signature_changed condition.
    """
    orig_code = """
int calculate(int a, int b) {
    return a + b;
}
int main() {
    return 0;
}
"""
    # Signature changed: int (int, int) -> int (double, int)
    patched_code = """
int calculate(double a, int b) {
    return (int)(a + b);
}
int main() {
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched_code)
    res = gate_ast_diff_check(patch, original_source=orig_code)
    assert res.passed is False
    assert res.details.get("failure_condition") == "signature_changed"
    assert "calculate" in res.reason


def test_gate3_fails_when_unexpected_function_added():
    """
    Synthetic failure test for Gate 3:
    A patch injects an unexpected helper function not present in original code.
    Must FAIL Gate 3 with unexpected_function_added condition.
    """
    orig_code = """
int main() {
    return 0;
}
"""
    patched_code = """
void injected_backdoor_func() {
}
int main() {
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched_code)
    res = gate_ast_diff_check(patch, original_source=orig_code)
    assert res.passed is False
    assert res.details.get("failure_condition") == "unexpected_function_added"
    assert "injected_backdoor_func" in res.reason


def test_gate3_unblocked_function_not_flagged_as_added():
    """
    When an unclosed brace/bracket prevented Clang from initially parsing a function
    that was already in the source text, fixing the brace makes it visible in AST.
    Gate 3 must recognize it as pre-existing and PASS.
    """
    orig_code = """
void process(int x) {
    if (x > 0) {
        int y = x;
// Missing closing brace for process
int main() {
    return 0;
}
"""
    patched_code = """
void process(int x) {
    if (x > 0) {
        int y = x;
    }
}
int main() {
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched_code)
    res = gate_ast_diff_check(patch, original_source=orig_code)
    assert res.passed is True


def test_gate3_independence_clean_compilation_fails_gate3():
    """
    Independence test:
    The patched code compiles 100% cleanly without errors or warnings (passes Gate 1),
    but fails Gate 3 specifically because it achieved clean compilation by deleting a function.
    """
    orig_code = """
int problematic_func() {
    int x = 10
    return x;
}
int main() {
    return 0;
}
"""
    # Deleting the function fixes the compile error cleanly!
    patched_code = """
int main() {
    return 0;
}
"""
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        diagnostic=Diagnostic(kind="error", message="expected ';'", line=3),
    )

    # Gate 1 passes because target error is gone and no new errors exist
    g1 = gate_recompile_check(patch, original_source=orig_code)
    assert g1.passed is True

    # Gate 3 MUST FAIL because a function was deleted
    g3 = gate_ast_diff_check(patch, original_source=orig_code)
    assert g3.passed is False
    assert g3.details.get("failure_condition") == "function_removed"


def test_gate3_declared_exception_rt02_passes():
    """
    Task 4: Declared structural exception for rt02.
    rt02 (void main() -> int main()) declares {"main": "return_type"}.
    Gate 3 must accept this declared signature change and PASS.
    """
    from tools.repair import repair

    rt02_path = os.path.join(BASE_DIR, "benchmark", "return_type", "rt02_void_main.cpp")
    with open(rt02_path) as f:
        src = f.read()

    diag = Diagnostic(
        kind="error",
        message="'main' must return 'int'",
        line=4,
        category="return_type_error",
        raw=f"{rt02_path}:4:1: error: 'main' must return 'int'",
    )

    patch = repair(rt02_path, diag)
    assert patch is not None, "Repair should produce a patch for rt02"
    assert patch.expected_structural_changes == {"main": "return_type"}

    res = gate_ast_diff_check(patch, original_source=src)
    assert res.passed is True, f"Gate 3 should pass rt02 with declared exception: {res.reason}"


def test_gate3_undeclared_signature_change_still_fails():
    """
    Task 4: Undeclared signature changes must still fail Gate 3.
    Even for main(), if expected_structural_changes is None or empty,
    Gate 3 must reject the signature change.
    """
    orig_code = """
void main() {
    int x = 5;
}
"""
    patched_code = """
int main() {
    int x = 5;
}
"""
    # No declared exceptions
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        expected_structural_changes=None,
    )
    res = gate_ast_diff_check(patch, original_source=orig_code)
    assert res.passed is False, "Gate 3 should fail undeclared signature change"
    assert res.details.get("failure_condition") == "signature_changed"


def test_gate3_declared_exception_disallows_other_signature_changes():
    """
    Task 4: Declared exception {"main": "return_type"} must NOT allow
    parameter changes to main or return type changes to other functions.
    """
    orig_code = """
int helper(int a) { return a; }
void main() {
    helper(1);
}
"""
    # main's return type changed, but helper's return type also changed
    patched_code = """
void* helper(int a) { return (void*)0; }
int main() {
    helper(1);
}
"""
    patch = Patch(
        original_file="<memory>",
        patched_source=patched_code,
        expected_structural_changes={"main": "return_type"},
    )
    res = gate_ast_diff_check(patch, original_source=orig_code)
    assert res.passed is False, "Gate 3 must reject undeclared helper signature change"
    assert res.details.get("failure_condition") == "signature_changed"
    assert "helper" in res.reason

