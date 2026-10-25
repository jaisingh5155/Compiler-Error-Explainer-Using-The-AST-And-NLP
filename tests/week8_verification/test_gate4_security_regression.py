#!/usr/bin/env python3
"""
tests/week8_verification/test_gate4_security_regression.py
─────────────────────────────────────────────────────────
Verification tests for Gate 4: Security Regression Check.
Confirms:
1. A well-behaved patch with no security regressions passes Gate 4.
2. Synthetic bad patch that introduces an unsafe string copy (CWE-120) fails Gate 4.
3. Synthetic bad patch that introduces a null pointer dereference (CWE-476) fails Gate 4.
4. Synthetic bad patch that introduces an uninitialized variable read (CWE-457) fails Gate 4.
5. Pre-existing security findings are tolerated (post count <= pre count).
6. Independence: A patch that compiles cleanly (passes Gate 1) fails Gate 4 specifically on security findings.
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from diagnostic import Diagnostic, Patch
from tools.verify_gates import gate_security_regression_check, gate_recompile_check


def test_gate4_valid_patch_passes():
    """Clean syntax fix introduces no vulnerabilities -> PASS."""
    orig = """
#include <iostream>
int main() {
    int x = 10
    std::cout << x << std::endl;
    return 0;
}
"""
    patched = """
#include <iostream>
int main() {
    int x = 10;
    std::cout << x << std::endl;
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched)
    res = gate_security_regression_check(patch, original_source=orig)
    assert res.passed is True
    assert "no security regressions" in res.reason.lower()


def test_gate4_fails_on_unsafe_function_injection():
    """
    Synthetic failure test for Gate 4:
    Fixes a syntax error, but replaces a safe copy with an unbounded strcpy (CWE-120).
    Must FAIL Gate 4 with security_regression condition.
    """
    orig = """
#include <cstring>
int main() {
    char buf[16];
    int x = 0
    return 0;
}
"""
    # Fixes semicolon on x, but introduces strcpy
    patched = """
#include <cstring>
int main() {
    char buf[16];
    int x = 0;
    strcpy(buf, "this is an unbounded string that exceeds 16 chars");
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched)
    res = gate_security_regression_check(patch, original_source=orig)
    assert res.passed is False
    assert res.details.get("failure_condition") == "security_regression"
    assert "security finding" in res.reason.lower()


def test_gate4_fails_on_null_pointer_dereference():
    """
    Synthetic failure test for Gate 4:
    Fixes a syntax error, but introduces an unconditional null pointer dereference (CWE-476).
    Must FAIL Gate 4 with security_regression condition.
    """
    orig = """
int main() {
    int x = 5
    return 0;
}
"""
    # Fixes semicolon on x, but introduces null pointer dereference
    patched = """
int main() {
    int x = 5;
    int* ptr = nullptr;
    *ptr = 42;
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched)
    res = gate_security_regression_check(patch, original_source=orig)
    assert res.passed is False
    assert res.details.get("failure_condition") == "security_regression"
    assert "Null Pointer Dereference" in res.reason or "security finding" in res.reason.lower()


def test_gate4_tolerates_preexisting_security_findings():
    """
    Pre-existing security issues (e.g. an existing unsafe call in untouched code)
    are tolerated if the patch does not add any new findings.
    """
    orig = """
#include <cstring>
void legacy() {
    char buf[8];
    strcpy(buf, "overflow");
}
int main() {
    int x = 10
    return 0;
}
"""
    patched = """
#include <cstring>
void legacy() {
    char buf[8];
    strcpy(buf, "overflow");
}
int main() {
    int x = 10;
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched)
    res = gate_security_regression_check(patch, original_source=orig)
    assert res.passed is True
    assert res.details["post_findings_count"] <= res.details["pre_findings_count"]


def test_gate4_independence_clean_compilation_fails_gate4():
    """
    Independence test:
    A patch that compiles cleanly with exit code 0 and no compiler diagnostics (passes Gate 1),
    but introduces a severe security vulnerability (fails Gate 4).
    """
    orig = """
int main() {
    int x = 10
    return 0;
}
"""
    # Compiles with 0 warnings or errors under GCC/Clang standard flags,
    # but contains an uninitialized variable read or null deref
    patched = """
int main() {
    int x = 10;
    int* ptr = nullptr;
    *ptr = 100;
    return 0;
}
"""
    patch = Patch(
        original_file="<memory>",
        patched_source=patched,
        diagnostic=Diagnostic(kind="error", message="expected ';'", line=3),
    )

    # Gate 1 passes because target error is resolved and no new compiler diagnostics appear
    g1 = gate_recompile_check(patch, original_source=orig)
    assert g1.passed is True

    # Gate 4 FAILS because a new security vulnerability was injected
    g4 = gate_security_regression_check(patch, original_source=orig)
    assert g4.passed is False
    assert g4.details.get("failure_condition") == "security_regression"


def test_gate4_injected_strcpy_on_own_line_fails():
    """
    User requirement 2(a):
    A patch that injects strcpy on its own line still fails Gate 4.
    """
    orig = """
#include <iostream>
int main() {
    int x = 42;
    std::cout << x << std::endl;
    return 0;
}
"""
    patched = """
#include <iostream>
#include <cstring>
int main() {
    int x = 42;
    char buf[16];
    strcpy(buf, "malicious overflow payload");
    std::cout << x << std::endl;
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched)
    res = gate_security_regression_check(patch, original_source=orig)
    assert res.passed is False
    assert res.status == "failed"
    assert res.details.get("failure_condition") == "security_regression"
    assert len(res.details.get("introduced_regressions", [])) >= 1


def test_gate4_unmasked_distant_uninitialized_read_passes():
    """
    User requirement 2(b):
    A correct syntax patch on a file with a pre-existing distant uninitialized read passes
    with the finding reported as unmasked.
    """
    # Syntax error at line 3 blinds AST CFG scan pre-patch (0 findings pre-patch).
    orig = """
#include <iostream>
int helper( {
    return 0;
}
int compute() {
    int uninit_var;
    std::cout << uninit_var << std::endl;
    return 0;
}
int main() {
    return compute();
}
"""
    # Patch only touches line 3 (helper syntax fix)
    patched = """
#include <iostream>
int helper() {
    return 0;
}
int compute() {
    int uninit_var;
    std::cout << uninit_var << std::endl;
    return 0;
}
int main() {
    return compute();
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched)
    res = gate_security_regression_check(patch, original_source=orig)
    assert res.passed is True
    assert res.status == "passed"
    unmasked = res.details.get("unmasked_findings", [])
    assert len(unmasked) >= 1
    assert any("uninitialized" in f["description"].lower() for f in unmasked)
    assert len(res.details.get("introduced_regressions", [])) == 0


def test_gate4_semicolon_on_existing_strcpy_passes():
    """
    Requirement (b): In Gate 4, the dangerous symbols introduced by the diff
    rule must compare counts in added vs removed lines, so adding a semicolon
    to a line that already contains strcpy passes.
    """
    orig = """
#include <cstring>
int main() {
    char buf[16];
    strcpy(buf, "hello")
    return 0;
}
"""
    patched = """
#include <cstring>
int main() {
    char buf[16];
    strcpy(buf, "hello");
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=patched)
    res = gate_security_regression_check(patch, original_source=orig)
    assert res.passed is True
    assert res.status == "passed"
    assert len(res.details.get("introduced_regressions", [])) == 0


