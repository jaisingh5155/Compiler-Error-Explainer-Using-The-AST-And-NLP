#!/usr/bin/env python3
"""
tests/week8_verification/test_gate2_diff_size.py

Verification tests for Gate 2: Minimal Diff Size Check.
Confirms:
1. Well-behaved S0 fix (1-2 lines) passes Gate 2.
2. Synthetic bad patch tagged S0 touching excessive lines (10+ lines) FAILS Gate 2.
3. S1 fixes within threshold (<= 8 lines) pass; over threshold fail.
4. S2 fixes within threshold (<= 20 lines) pass; over threshold fail.
5. Isolation: A patch can pass Gate 1 (compiles clean) but fail Gate 2 specifically on diff size.
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from diagnostic import Diagnostic, Patch
from tools.verify_gates import gate_minimal_diff_check, gate_recompile_check


def test_gate2_normal_s0_patch_passes():
    """Trivial S0 patch touching 1-2 lines passes Gate 2."""
    orig = """int main() {
    int x = 10
    return 0;
}"""
    patched = """int main() {
    int x = 10;
    return 0;
}"""
    patch = Patch(
        original_file="<memory>",
        patched_source=patched,
        safety_level="S0",
    )
    res = gate_minimal_diff_check(patch=patch, original_source=orig)
    assert res.passed is True
    assert res.details["modified_lines"] <= 4


def test_gate2_fails_s0_patch_with_excessive_diff():
    """
    Synthetic failure test for Gate 2:
    A patch tagged S0 (which should touch only 1-2 lines) modifies 10+ lines.
    Must FAIL Gate 2 specifically due to diff size exceeding S0 threshold.
    """
    orig = """int main() {
    int a = 1;
    int b = 2;
    int c = 3;
    int d = 4;
    int e = 5;
    int f = 6;
    int g = 7;
    int h = 8;
    int x = 10
    return 0;
}"""
    # Overwrites entire body with 10+ modified lines despite being tagged S0
    patched = """int main() {
    int val_a = 100;
    int val_b = 200;
    int val_c = 300;
    int val_d = 400;
    int val_e = 500;
    int val_f = 600;
    int val_g = 700;
    int val_h = 800;
    int x = 10;
    return 0;
}"""
    patch = Patch(
        original_file="<memory>",
        patched_source=patched,
        safety_level="S0",
    )
    res = gate_minimal_diff_check(patch=patch, original_source=orig)
    assert res.passed is False, "Expected Gate 2 to fail for bloated S0 patch"
    assert res.details["safety_level"] == "S0"
    assert res.details["modified_lines"] >= 10
    assert "exceeds S0 threshold" in res.reason


def test_gate2_s1_threshold_enforcement():
    """S1 allows up to 8 modified lines. Passes under 8, fails over 8."""
    orig = """int compute() {
    int x = 1;
    return x;
}"""
    # 2 lines changed: passes S1
    patch_ok = Patch(
        original_file="<memory>",
        patched_source="""int compute() {
    int x = 1;
    int y = 2;
    return x + y;
}""",
        safety_level="S1",
    )
    res_ok = gate_minimal_diff_check(patch_ok, original_source=orig)
    assert res_ok.passed is True

    # Bloated S1 patch touching 12 lines fails
    bloated_lines = "\n".join([f"    int var_{i} = {i};" for i in range(12)])
    patch_bad = Patch(
        original_file="<memory>",
        patched_source=f"int compute() {{\n{bloated_lines}\n    return 0;\n}}",
        safety_level="S1",
    )
    res_bad = gate_minimal_diff_check(patch_bad, original_source=orig)
    assert res_bad.passed is False
    assert "exceeds S1 threshold" in res_bad.reason


def test_gate2_s2_threshold_enforcement():
    """S2 allows up to 20 modified lines. Passes under 20, fails over 20."""
    orig = "int main() {\n" + "\n".join([f"    int x{i} = {i};" for i in range(25)]) + "\n    return 0;\n}"
    
    # 6 lines modified passes S2
    patched_small = "int main() {\n" + "\n".join([f"    int x{i} = {i*2};" for i in range(3)]) + "\n" + "\n".join([f"    int x{i} = {i};" for i in range(3, 25)]) + "\n    return 0;\n}"
    patch_s2_ok = Patch(original_file="<memory>", patched_source=patched_small, safety_level="S2")
    res_ok = gate_minimal_diff_check(patch_s2_ok, original_source=orig)
    assert res_ok.passed is True

    # 30 lines modified fails S2
    patched_massive = "int main() {\n" + "\n".join([f"    int new_var_{i} = {i*10};" for i in range(25)]) + "\n    return 0;\n}"
    patch_s2_bad = Patch(original_file="<memory>", patched_source=patched_massive, safety_level="S2")
    res_bad = gate_minimal_diff_check(patch_s2_bad, original_source=orig)
    assert res_bad.passed is False
    assert "exceeds S2 threshold" in res_bad.reason


def test_patch_fails_gate2_only():
    """
    Independence check:
    A patch that compiles cleanly and fixes the error (passes Gate 1),
    but violates the S0 line threshold (fails Gate 2).
    Confirms Gate 2 operates independently of compiler exit codes.
    """
    orig = """int main() {
    int a = 1;
    int b = 2;
    int c = 3;
    int d = 4;
    int e = 5;
    int f = 6;
    int g = 7;
    int missing_semi = 0
    return 0;
}"""
    # Fixes semicolon AND rewrites 7 variables. Compiles clean (Gate 1 PASS), but 12 lines diff on S0 (Gate 2 FAIL).
    patched = """int main() {
    int a = 10;
    int b = 20;
    int c = 30;
    int d = 40;
    int e = 50;
    int f = 60;
    int g = 70;
    int missing_semi = 0;
    return 0;
}"""
    target_diag = Diagnostic(
        kind="error",
        message="expected ';' at end of declaration",
        line=9,
        category="syntax_error",
    )
    patch = Patch(
        original_file="<memory>",
        patched_source=patched,
        diagnostic=target_diag,
        safety_level="S0",
    )

    g1 = gate_recompile_check(patch, target_diagnostic=target_diag, original_source=orig)
    g2 = gate_minimal_diff_check(patch, original_source=orig)

    assert g1.passed is True, f"Gate 1 should pass (compiles cleanly): {g1.reason}"
    assert g2.passed is False, f"Gate 2 should FAIL (12 lines modified on S0): {g2.reason}"
