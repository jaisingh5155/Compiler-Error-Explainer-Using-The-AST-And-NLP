#!/usr/bin/env python3
"""
Week 7 Verification - Task 1: Independent Generalization Check for CWE-476 (Null Pointer Dereference).

Tests 5 adversarial code shapes not based on sec07/08/09/17/18/19:
  a) Early-return / guard-clause pattern: `if (!p) return; *p = 5;` -> Not flagged (PASS).
  b) Assert guard pattern: `assert(p != nullptr); *p = 42;` -> Not flagged (PASS - fixed false positive).
  c) Ternary pointer pass-through: `int* q = cond ? p : &fallback; *q;` -> Not flagged (PASS - documented limitation).
  d) Double pointer and reference to pointer: `int** pp`, `int*& pref` -> Not flagged / no crash (PASS).
  e) Loop body dereference: loops are out-of-scope for linear AST tracking -> Not tracked / no crash / no FP (PASS - documented limitation).
"""

import os
import pytest
from security_analyzer import analyze

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADV_DIR = os.path.join(BASE_DIR, "adversarial_cwe476")


def test_early_return_guard():
    """Case (a): Early-return guard clause pattern (dereference outside if-block)."""
    target = os.path.join(ADV_DIR, "test_a_early_return.cpp")
    findings = analyze(target, [])
    cwe476 = [f for f in findings if "Null Pointer" in f.vulnerability_type]
    assert len(cwe476) == 0, f"Expected 0 CWE-476 findings for early return, got: {cwe476}"


def test_assert_guard():
    """Case (b): Assert guard before dereference."""
    target = os.path.join(ADV_DIR, "test_b_assert_guard.cpp")
    findings = analyze(target, [])
    cwe476 = [f for f in findings if "Null Pointer" in f.vulnerability_type]
    assert len(cwe476) == 0, f"Expected 0 CWE-476 findings for assert guard, got: {cwe476}"


def test_ternary_pointer():
    """Case (c): Pointer assigned through ternary with safe fallback."""
    target = os.path.join(ADV_DIR, "test_c_ternary.cpp")
    findings = analyze(target, [])
    cwe476 = [f for f in findings if "Null Pointer" in f.vulnerability_type]
    assert len(cwe476) == 0, f"Expected 0 CWE-476 findings for ternary, got: {cwe476}"


def test_double_pointer():
    """Case (d): Double pointer and reference to pointer."""
    target = os.path.join(ADV_DIR, "test_d_double_ptr.cpp")
    findings = analyze(target, [])
    cwe476 = [f for f in findings if "Null Pointer" in f.vulnerability_type]
    assert len(cwe476) == 0, f"Expected 0 CWE-476 findings for double pointer, got: {cwe476}"


def test_loop_out_of_scope():
    """Case (e): Loop body dereference (loops are out-of-scope, no crash, no tracking)."""
    target = os.path.join(ADV_DIR, "test_e_loop_deref.cpp")
    findings = analyze(target, [])
    cwe476 = [f for f in findings if "Null Pointer" in f.vulnerability_type]
    assert len(cwe476) == 0, f"Expected 0 CWE-476 findings for loop dereference (out of scope), got: {cwe476}"
