#!/usr/bin/env python3
"""
tests/week8_verification/test_gate5_differential.py
────────────────────────────────────────────────────
Verification tests for Gate 5: Differential Execution Check.
Confirms:
1. Inapplicable case: when pre-patch fails compilation (as with 0/56 repair targets)
   or original source is missing, returns status="not_applicable", passed=None,
   and details["status"] == "skipped".
2. verify_patch_gates() pipeline and trace_log report Gate 5 as "skipped".
3. Applicable path with warning-only file (pre-patch compiles cleanly):
   (a) Behavior-preserving patch: returns status="passed", passed=True.
   (b) Behavior-changing patch: returns status="failed", passed=False.
"""

import os
import sys
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from diagnostic import Patch
from tools.verify_gates import gate_differential_execution, verify_patch_gates


def test_gate5_not_applicable_when_prepatch_fails_compilation():
    """
    When pre-patch code fails compilation (as with all 56 benchmark repair targets),
    Gate 5 must return status='not_applicable' (not passed=True) and details['status'] = 'skipped'.
    """
    broken_orig = """
#include <iostream>
int main() {
    std::cout << "broken syntax" // missing semicolon
    return 0;
}
"""
    clean_patch = """
#include <iostream>
int main() {
    std::cout << "broken syntax";
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=clean_patch)
    res = gate_differential_execution(patch, original_source=broken_orig)

    assert res.status == "not_applicable"
    assert res.passed is None
    assert res.details.get("status") == "skipped"
    assert res.details.get("applicable") is False
    assert "no baseline execution exists" in res.reason.lower() or "inapplicable" in res.reason.lower()


def test_gate5_pipeline_trace_log_reports_skipped():
    """
    verify_patch_gates() pipeline with enable_gate5=True must record
    status='skipped' in trace_log and allow all_passed=True when Gate 5 is inapplicable.
    """
    broken_orig = """
#include <iostream>
int main() {
    int x = 10 // missing semicolon
    std::cout << x << std::endl;
    return 0;
}
"""
    clean_patch = """
#include <iostream>
int main() {
    int x = 10;
    std::cout << x << std::endl;
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=clean_patch)
    pipeline_res = verify_patch_gates(patch, original_source=broken_orig, enable_gate5=True)

    assert pipeline_res["passed"] is True
    g5_dict = pipeline_res["gate5_differential_execution"]
    assert g5_dict["status"] == "not_applicable"
    assert g5_dict["passed"] is None

    # Check trace_log entry
    trace_entry = next((e for e in pipeline_res["trace_log"] if e["gate"] == "gate5_differential_execution"), None)
    assert trace_entry is not None
    assert trace_entry["status"] == "skipped"
    assert trace_entry["passed"] is None


def test_gate5_applicable_behavior_preserving_patch_passes():
    """
    Applicable path: pre-patch compiles cleanly (warning-only file with unused variable).
    A behavior-preserving patch removes the unused variable and produces identical output -> PASS.
    """
    warning_orig = """
#include <iostream>
int main() {
    int unused_metric = 999;
    std::cout << "Sum: " << (5 + 10) << std::endl;
    return 0;
}
"""
    clean_preserving_patch = """
#include <iostream>
int main() {
    std::cout << "Sum: " << (5 + 10) << std::endl;
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=clean_preserving_patch)
    res = gate_differential_execution(patch, original_source=warning_orig)

    assert res.status == "passed"
    assert res.passed is True
    assert res.details.get("status") == "passed"
    assert res.details.get("applicable") is True
    assert "outputs match pre-patch baseline" in res.reason


def test_gate5_applicable_behavior_changing_patch_fails():
    """
    Applicable path: pre-patch compiles cleanly (warning-only file).
    A behavior-changing patch alters program output -> FAIL.
    """
    warning_orig = """
#include <iostream>
int main() {
    int unused_metric = 999;
    std::cout << "Expected Output" << std::endl;
    return 0;
}
"""
    behavior_altered_patch = """
#include <iostream>
int main() {
    std::cout << "Corrupted Output" << std::endl;
    return 0;
}
"""
    patch = Patch(original_file="<memory>", patched_source=behavior_altered_patch)
    res = gate_differential_execution(patch, original_source=warning_orig)

    assert res.status == "failed"
    assert res.passed is False
    assert res.details.get("status") == "failed"
    assert res.details.get("applicable") is True
    assert res.details.get("failure_condition") == "output_mismatch"
    assert "mismatch" in res.reason.lower()
