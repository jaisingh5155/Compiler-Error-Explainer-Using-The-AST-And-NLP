"""
tests/week7_verification/test_week7.py
──────────────────────────────────────
Week 7 Verification Test Suite:
1. sec15 fix + genuine CWE-190 cases still work (regression test).
2. CWE-476 detector (3 recovered files + 3 new edge-case files).
3. CWE-457 detector (1 recovered file + 3 new edge-case files).
4. Safety-level tagging & gating (S0 auto-applies, S2 is marked suggestion-only and not auto-applied).
5. optimize() tool (finds target patterns in optimization test files, zero false positives on existing benchmark).
"""

import os
import sys
import tempfile
import pytest

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)
_SRC = os.path.join(_PROJECT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from diagnostic import ProgramModel, Diagnostic, Patch
from security_analyzer import analyze
from tools.understand import understand
from tools.detect import detect
from tools.repair import repair
from tools.optimize import optimize
from auto_healer import attempt_fix_tiered, attempt_fix
from planner import Planner


# ── 1. sec15 fix + genuine CWE-190 regression test ────────────────────────────

def test_sec15_fix_and_genuine_cwe190():
    """Verify sec15 decoy produces 0 CWE-190 findings while sec10 and me04 still detect genuine CWE-190."""
    p_sec15 = os.path.join(_PROJECT, "benchmark", "security", "sec15_decoy_safe_alloc.cpp")
    findings_15 = analyze(p_sec15, [])
    cwe190_15 = [f for f in findings_15 if f.vulnerability_type == "Integer Overflow"]
    assert len(cwe190_15) == 0, f"sec15 false alarm: {cwe190_15}"

    p_sec10 = os.path.join(_PROJECT, "benchmark", "security", "sec10_integer_overflow.cpp")
    findings_10 = analyze(p_sec10, [])
    cwe190_10 = [f for f in findings_10 if f.vulnerability_type == "Integer Overflow"]
    assert len(cwe190_10) >= 1, "sec10 failed to detect genuine CWE-190 integer overflow"

    p_me04 = os.path.join(_PROJECT, "benchmark", "multi_error", "me04_name_and_overflow.cpp")
    findings_me04 = analyze(p_me04, [])
    cwe190_me04 = [f for f in findings_me04 if f.vulnerability_type == "Integer Overflow"]
    assert len(cwe190_me04) >= 1, "me04 failed to detect genuine CWE-190 integer overflow"


# ── 2. CWE-476 Null Pointer Dereference Detector ──────────────────────────────

def test_cwe476_detector_benchmark_files():
    """Verify CWE-476 detection on 3 recovered files + 3 edge-case files."""
    # 3 Recovered files
    for fn in ("sec07_null_deref_direct.cpp", "sec08_null_deref_struct.cpp", "sec09_null_deref_return.cpp"):
        p = os.path.join(_PROJECT, "benchmark", "security", fn)
        findings = analyze(p, [])
        cwe476 = [f for f in findings if f.vulnerability_type == "Null Pointer Dereference"]
        assert len(cwe476) >= 1, f"Failed to detect CWE-476 in {fn}"

    # New vulnerable edge case: sec19 arrow deref
    p_sec19 = os.path.join(_PROJECT, "benchmark", "security", "sec19_null_deref_struct_arrow.cpp")
    findings_19 = analyze(p_sec19, [])
    assert any(f.vulnerability_type == "Null Pointer Dereference" for f in findings_19), "Failed to detect CWE-476 in sec19_null_deref_struct_arrow"

    # 2 Clean edge cases: sec17 (guarded) and sec18 (reassigned)
    p_sec17 = os.path.join(_PROJECT, "benchmark", "security", "sec17_null_check_guarded.cpp")
    findings_17 = analyze(p_sec17, [])
    assert not any(f.vulnerability_type == "Null Pointer Dereference" for f in findings_17), f"False positive CWE-476 in sec17: {findings_17}"

    p_sec18 = os.path.join(_PROJECT, "benchmark", "security", "sec18_null_reassigned_valid.cpp")
    findings_18 = analyze(p_sec18, [])
    assert not any(f.vulnerability_type == "Null Pointer Dereference" for f in findings_18), f"False positive CWE-476 in sec18: {findings_18}"


# ── 3. CWE-457 Uninitialized Variable Use Detector ───────────────────────────

def test_cwe457_detector_benchmark_files():
    """Verify CWE-457 detection on 1 recovered file + 3 edge-case files."""
    # Recovered file: sec11
    p_sec11 = os.path.join(_PROJECT, "benchmark", "security", "sec11_uninit_use.cpp")
    findings_11 = analyze(p_sec11, [])
    assert any(f.vulnerability_type == "Uninitialized Memory" for f in findings_11), "Failed to detect CWE-457 in sec11_uninit_use"

    # New vulnerable edge case: sec21 branch leak
    p_sec21 = os.path.join(_PROJECT, "benchmark", "security", "sec21_uninit_branch_leak.cpp")
    findings_21 = analyze(p_sec21, [])
    assert any(f.vulnerability_type == "Uninitialized Memory" for f in findings_21), "Failed to detect CWE-457 in sec21_uninit_branch_leak"

    # 2 Clean edge cases: sec20 (assigned in all branches) and sec22 (output param)
    p_sec20 = os.path.join(_PROJECT, "benchmark", "security", "sec20_uninit_all_branches.cpp")
    findings_20 = analyze(p_sec20, [])
    assert not any(f.vulnerability_type == "Uninitialized Memory" for f in findings_20), f"False positive CWE-457 in sec20: {findings_20}"

    p_sec22 = os.path.join(_PROJECT, "benchmark", "security", "sec22_uninit_output_param.cpp")
    findings_22 = analyze(p_sec22, [])
    assert not any(f.vulnerability_type == "Uninitialized Memory" for f in findings_22), f"False positive CWE-457 in sec22: {findings_22}"


# ── 4. Safety-Level Tagging, Gating, and Unsafe Function Repairs ──────────────

def test_safety_level_tagging_and_unsafe_repairs():
    """Verify safety_level tagging on Patch objects, unsafe function fixes, and Planner gating."""
    # S0 test: missing semicolon
    s0_src = "int main() {\n    int x = 5\n    return 0;\n}\n"
    s0_diag = Diagnostic(kind="error", line=2, column=14, message="expected ';' at end of declaration", category="syntax_error")
    s0_patch = repair(s0_src, s0_diag)
    assert s0_patch is not None
    assert s0_patch.safety_level == "S0"
    assert s0_patch.suggestion_only is False

    # S1 test: gets() -> fgets()
    gets_src = "int main() {\n    char buf[16];\n    gets(buf);\n    return 0;\n}\n"
    gets_diag = Diagnostic(kind="warning", line=3, column=5, message="call to gets is unsafe", category="security_vulnerability", cwe="CWE-120")
    gets_patch = repair(gets_src, gets_diag)
    assert gets_patch is not None
    assert "fgets(buf, sizeof(buf), stdin)" in gets_patch.patched_source
    assert gets_patch.safety_level == "S1"
    assert gets_patch.suggestion_only is False

    # S1 test: sprintf() -> snprintf()
    sprintf_src = 'int main() {\n    char buf[16];\n    sprintf(buf, "%d", 42);\n    return 0;\n}\n'
    sprintf_diag = Diagnostic(kind="warning", line=3, column=5, message="call to sprintf is unsafe", category="security_vulnerability", cwe="CWE-134")
    sprintf_patch = repair(sprintf_src, sprintf_diag)
    assert sprintf_patch is not None
    assert "snprintf(buf, sizeof(buf), " in sprintf_patch.patched_source
    assert sprintf_patch.safety_level == "S1"
    assert sprintf_patch.suggestion_only is False

    # S2 test: strcpy() -> strncpy()
    strcpy_src = 'int main() {\n    char dst[8];\n    strcpy(dst, "hello");\n    return 0;\n}\n'
    strcpy_diag = Diagnostic(kind="warning", line=3, column=5, message="call to strcpy is unsafe", category="security_vulnerability", cwe="CWE-120")
    strcpy_patch = repair(strcpy_src, strcpy_diag)
    assert strcpy_patch is not None
    assert "strncpy(dst," in strcpy_patch.patched_source
    assert strcpy_patch.safety_level == "S2"
    assert strcpy_patch.suggestion_only is True


def test_planner_s0_auto_applied_and_s2_not_applied():
    """Verify S0 patch is auto-applied by Planner, while S2 patch is surfaced as suggestion only."""
    # Test S0 auto-application end-to-end
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as f:
        f.write("int main() {\n    int x = 5\n    return 0;\n}\n")
        tmp_s0 = f.name

    try:
        # 1. Universal Review Safe Default (no direct disk writes without explicit Accept)
        planner_s0 = Planner(tmp_s0, max_iterations=3, apply_to_disk=False)
        res_s0 = planner_s0.run()
        assert res_s0.status in ("success", "clean")
        assert len(res_s0.pending_patches) >= 1
        assert len(res_s0.patches_applied) == 0
        with open(tmp_s0) as f:
            untouched_code = f.read()
        assert "int x = 5\n" in untouched_code, "File was modified in safe review mode!"

        # 2. Explicit Apply (User clicks Accept Patch or CLI --apply)
        planner_s0_apply = Planner(tmp_s0, max_iterations=3, apply_to_disk=True)
        res_s0_apply = planner_s0_apply.run()
        assert len(res_s0_apply.patches_applied) >= 1
        with open(tmp_s0) as f:
            final_code = f.read()
        assert "int x = 5;" in final_code
    finally:
        os.unlink(tmp_s0)

    # Test S2 gating: division by zero or uninit variable
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as f:
        f.write("int main() {\n    int x = 10 / 0;\n    return 0;\n}\n")
        tmp_s2 = f.name

    try:
        planner_s2 = Planner(tmp_s2, max_iterations=3)
        res_s2 = planner_s2.run()
        # S2 patch must NOT be applied to source file
        assert len(res_s2.patches_applied) == 0
        with open(tmp_s2) as f:
            unchanged_code = f.read()
        assert "int x = 10 / 0;" in unchanged_code
    finally:
        os.unlink(tmp_s2)


# ── 5. optimize() tool verification ───────────────────────────────────────────

def test_optimize_tool_on_target_patterns():
    """Verify optimize() identifies dead code, redundant computation, and modern C++ opportunities."""
    # 1. Dead code
    opt1_path = os.path.join(_PROJECT, "benchmark", "optimization", "opt01_dead_code.cpp")
    opt1_suggs = optimize(opt1_path)
    dead_code_suggs = [s for s in opt1_suggs if s.optimization_type == "dead_code"]
    assert len(dead_code_suggs) >= 1, "Failed to detect dead code in opt01_dead_code.cpp"
    assert any("Unreachable" in s.description for s in dead_code_suggs)

    # 2. Redundant computation
    opt2_path = os.path.join(_PROJECT, "benchmark", "optimization", "opt02_redundant_computation.cpp")
    opt2_suggs = optimize(opt2_path)
    redundant_suggs = [s for s in opt2_suggs if s.optimization_type == "redundant_computation"]
    assert len(redundant_suggs) >= 1, "Failed to detect redundant computation in opt02_redundant_computation.cpp"
    assert any("a * b" in s.description for s in redundant_suggs)

    # 3. Modern nullptr
    opt3_path = os.path.join(_PROJECT, "benchmark", "optimization", "opt03_modern_nullptr.cpp")
    opt3_suggs = optimize(opt3_path)
    modern_suggs = [s for s in opt3_suggs if s.optimization_type == "modern_cpp"]
    assert len(modern_suggs) >= 1, "Failed to detect NULL macro in opt03_modern_nullptr.cpp"

    # 4. Pass container by const reference
    opt4_path = os.path.join(_PROJECT, "benchmark", "optimization", "opt04_const_ref_param.cpp")
    opt4_suggs = optimize(opt4_path)
    const_ref_suggs = [s for s in opt4_suggs if s.optimization_type == "const_reference"]
    assert len(const_ref_suggs) >= 1, "Failed to detect value container param in opt04_const_ref_param.cpp"

    # 5. Clean benchmark file has zero false positives
    cl01_path = os.path.join(_PROJECT, "benchmark", "clean", "cl01_hello.cpp")
    model_cl01 = understand(cl01_path)
    cl01_suggs = optimize(model_cl01)
    spurious = [s for s in cl01_suggs if s.optimization_type in ("dead_code", "redundant_computation")]
    assert len(spurious) == 0, f"False positive optimization suggestions on cl01_hello: {spurious}"
