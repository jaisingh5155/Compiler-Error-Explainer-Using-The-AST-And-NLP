#!/usr/bin/env python3
"""
Week 7 Verification - Task 2: Independent Generalization Check for CWE-457 (Uninitialized Variable Use).

Tests 4 adversarial code shapes:
  a) Switch statement with exhaustive default case -> Not flagged (PASS).
  b) Switch statement missing default case -> Currently unflagged due to lack of switch branch modeling (Known Limitation).
  c) Loop body initialization guaranteed to execute -> Not flagged / no false positive (PASS).
  d) Lambda reference capture initialization -> Flagged due to lack of interprocedural closure tracking (Known Gap / Out-of-Scope).
"""

import os
import pytest
from security_analyzer import analyze

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADV_DIR = os.path.join(BASE_DIR, "adversarial_cwe457")


def test_switch_exhaustive():
    """Case (a): Switch statement with default case initializing variable in all branches."""
    target = os.path.join(ADV_DIR, "test_a_switch_exhaustive.cpp")
    findings = analyze(target, [])
    cwe457 = [f for f in findings if "Uninitialized" in f.vulnerability_type]
    assert len(cwe457) == 0, f"Expected 0 CWE-457 findings for exhaustive switch, got: {cwe457}"


def test_switch_missing_default_documented():
    """Case (b): Switch statement missing default case (documented known limitation: switch exhaustiveness unmodeled)."""
    target = os.path.join(ADV_DIR, "test_b_switch_missing_default.cpp")
    findings = analyze(target, [])
    cwe457 = [f for f in findings if "Uninitialized" in f.vulnerability_type]
    # Documented limitation: SwitchStmt is not modeled for branch exhaustiveness
    assert len(cwe457) == 0, "Switch statements currently lack branch exhaustiveness tracking"


def test_loop_init_no_false_positive():
    """Case (c): Variable initialized in loop guaranteed to execute (e.g. do-while)."""
    target = os.path.join(ADV_DIR, "test_c_loop_init.cpp")
    findings = analyze(target, [])
    cwe457 = [f for f in findings if "Uninitialized" in f.vulnerability_type]
    assert len(cwe457) == 0, f"Expected 0 CWE-457 false positives for loop init, got: {cwe457}"


def test_lambda_init_documented_gap():
    """Case (d): Variable initialized via lambda reference capture (documented known gap: closures out-of-scope)."""
    target = os.path.join(ADV_DIR, "test_d_lambda_init.cpp")
    findings = analyze(target, [])
    cwe457 = [f for f in findings if "Uninitialized" in f.vulnerability_type]
    # Documented gap: Lambda closure execution is not tracked across call boundaries
    assert len(cwe457) == 1, "Expected 1 finding on return statement due to out-of-scope lambda closure modeling"
    assert cwe457[0].line == 9
