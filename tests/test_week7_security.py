"""
tests/test_week7_security.py
────────────────────────────
Regression and verification test suite for Week 7 security analyzers:
1. CWE-190 false positive fix on sec15 (decoy safe allocation) while retaining sec10/me04 true positives.
2. CWE-476 null pointer dereference detection on sec07, sec08, sec09, sec19, and clean passes on sec17, sec18.
3. CWE-457 uninitialized variable use detection on sec11, sec21, and clean passes on sec20, sec22.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath("src"))

from security_analyzer import analyze


def test_cwe190_sec15_decoy_eliminated():
    """Verify sec15_decoy_safe_alloc is NOT flagged for CWE-190 integer overflow."""
    findings = analyze("benchmark/security/sec15_decoy_safe_alloc.cpp", [])
    cwe190_findings = [f for f in findings if f.vulnerability_type == "Integer Overflow"]
    assert len(cwe190_findings) == 0, f"sec15 had unexpected findings: {cwe190_findings}"


def test_cwe190_genuine_cases_preserved():
    """Verify sec10 and me04 genuine integer overflow cases are still detected."""
    findings_sec10 = analyze("benchmark/security/sec10_integer_overflow.cpp", [])
    assert any(f.vulnerability_type == "Integer Overflow" for f in findings_sec10), "sec10 integer overflow not detected"

    findings_me04 = analyze("benchmark/multi_error/me04_name_and_overflow.cpp", [])
    assert any(f.vulnerability_type == "Integer Overflow" for f in findings_me04), "me04 integer overflow not detected"


def test_cwe476_null_pointer_dereference():
    """Verify CWE-476 detections on sec07, sec08, sec09, sec19."""
    for path, expected_line in [
        ("benchmark/security/sec07_null_deref_direct.cpp", 5),
        ("benchmark/security/sec08_null_deref_struct.cpp", 6),
        ("benchmark/security/sec09_null_deref_return.cpp", 8),
        ("benchmark/security/sec19_null_deref_struct_arrow.cpp", 9),
    ]:
        findings = analyze(path, [])
        cwe476 = [f for f in findings if f.vulnerability_type == "Null Pointer Dereference"]
        assert len(cwe476) >= 1, f"Expected CWE-476 on {path}, got none"
        assert cwe476[0].line == expected_line, f"Expected line {expected_line} on {path}, got {cwe476[0].line}"


def test_cwe476_false_positive_guards():
    """Verify sec17 (guarded check) and sec18 (reassigned valid pointer) are NOT flagged."""
    for path in [
        "benchmark/security/sec17_null_check_guarded.cpp",
        "benchmark/security/sec18_null_reassigned_valid.cpp",
    ]:
        findings = analyze(path, [])
        cwe476 = [f for f in findings if f.vulnerability_type == "Null Pointer Dereference"]
        assert len(cwe476) == 0, f"Unexpected CWE-476 false positive on {path}: {cwe476}"


def test_cwe457_uninitialized_variable_use():
    """Verify CWE-457 detections on sec11 and sec21."""
    findings_sec11 = analyze("benchmark/security/sec11_uninit_use.cpp", [])
    cwe457_11 = [f for f in findings_sec11 if f.vulnerability_type == "Uninitialized Memory"]
    assert len(cwe457_11) >= 1, "Expected CWE-457 on sec11, got none"
    assert cwe457_11[0].line == 5

    findings_sec21 = analyze("benchmark/security/sec21_uninit_branch_leak.cpp", [])
    cwe457_21 = [f for f in findings_sec21 if f.vulnerability_type == "Uninitialized Memory"]
    assert len(cwe457_21) >= 1, "Expected CWE-457 on sec21, got none"
    assert cwe457_21[0].line == 9


def test_cwe457_false_positive_guards():
    """Verify sec20 (all branches assigned) and sec22 (output parameter) are NOT flagged."""
    for path in [
        "benchmark/security/sec20_uninit_all_branches.cpp",
        "benchmark/security/sec22_uninit_output_param.cpp",
        "benchmark/warnings_only/wo04_uninit_var.cpp",
        "benchmark/syntax/sx14_mismatched_paren_bracket.cpp",
        "benchmark/type_error/te05_wrong_stream_op.cpp",
    ]:
        findings = analyze(path, [])
        cwe457 = [f for f in findings if f.vulnerability_type == "Uninitialized Memory"]
        assert len(cwe457) == 0, f"Unexpected CWE-457 false positive on {path}: {cwe457}"


def test_auto_healer_safety_tiers():
    """Verify auto_healer classifies repairs into 3 safety tiers and repair() propagates them."""
    from auto_healer import get_safety_tier, SafetyTier, get_tier_info
    from tools.repair import repair
    from diagnostic import Diagnostic

    assert get_safety_tier("missing_include") == SafetyTier.TIER_1_MECHANICAL
    assert get_safety_tier("syntax_error") == SafetyTier.TIER_1_MECHANICAL
    assert get_safety_tier("type_error") == SafetyTier.TIER_2_SIGNATURE
    assert get_safety_tier("return_type_error") == SafetyTier.TIER_2_SIGNATURE
    assert get_safety_tier("uninitialized_memory") == SafetyTier.TIER_3_HEURISTIC
    assert get_safety_tier("integer_overflow") == SafetyTier.TIER_3_HEURISTIC

    diag = Diagnostic(
        kind="error",
        file="benchmark/syntax/sx01_missing_semi_decl.cpp",
        line=5,
        message="expected ';' at end of declaration",
        category="syntax_error",
    )
    patch = repair("benchmark/syntax/sx01_missing_semi_decl.cpp", diag)
    assert patch is not None
    assert patch.safety_tier == 1
    assert "Tier 1" in patch.tier_name


def test_optimize_tool():
    """Verify optimize() provides actionable suggestions for modernization and performance."""
    from tools.optimize import optimize

    sample_code = """#include <iostream>
#include <iostream>
#include <string>

void process_data(std::string text) {
    int* ptr = NULL;
    for (int i = 0; i < 100; i++) {
        std::cout << text << std::endl;
    }
}
"""
    suggestions = optimize(sample_code)
    assert len(suggestions) >= 4

    desc_text = " ".join(s.description for s in suggestions)
    assert "nullptr" in desc_text
    assert "duplicate include" in desc_text.lower()
    assert "const reference" in desc_text.lower()
    assert "prefix increment" in desc_text.lower()

