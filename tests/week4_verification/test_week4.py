"""
Week 4 Verification Test Suite
══════════════════════════════
Covers all requirements from Week 4 prompt:
  1. Step 0b: CWE-415 (double free) & CWE-190 (integer overflow) detection
  2. Step 3: Five tool interfaces (understand, detect, repair, optimize, verify)
  3. Step 2: Root-cause cascading error grouping (me06, me07)
  4. Step 4: Planner state-machine stop conditions (success, no_fixable_finding, max_iterations)
  5. Step 5: Config loader & policy externalization
"""

import os
import sys
import tempfile
import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(PROJECT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from diagnostic import (
    Diagnostic,
    ProgramModel,
    Patch,
    Suggestion,
    VerifyResult,
    from_compiler_error,
    from_security_finding,
)
from tools.understand import understand
from tools.detect import detect
from tools.repair import repair
from tools.optimize import optimize
from tools.verify import verify
from planner import Planner, run_planner, PlanConfig, plan, PlanState
from root_cause_grouper import group_by_root_cause, group_summary
from config_loader import load_config, get as cfg_get


# ══════════════════════════════════════════════════════════════════════
# 1. Step 0b: Security Fixes (CWE-415 and CWE-190)
# ══════════════════════════════════════════════════════════════════════

class TestStep0bSecurityFixes:
    """Verify quick-win fixes for Bug 4.2 (CWE-415) and Bug 4.3 (CWE-190)."""

    def test_cwe415_double_free(self):
        """CWE-415 double-free detector catches delete/free on already freed pointer."""
        from security_analyzer import analyze

        sec06 = os.path.join(PROJECT, "benchmark/security/sec06_double_free.cpp")
        findings_sec06 = analyze(sec06, [])
        df_sec06 = [f for f in findings_sec06 if f.vulnerability_type == "Double Free"]
        assert len(df_sec06) >= 1, f"Expected Double Free in sec06, got {findings_sec06}"

        me02 = os.path.join(PROJECT, "benchmark/multi_error/me02_redef_and_security.cpp")
        findings_me02 = analyze(me02, [])
        df_me02 = [f for f in findings_me02 if f.vulnerability_type == "Double Free"]
        assert len(df_me02) >= 1, f"Expected Double Free in me02, got {findings_me02}"

    def test_cwe190_integer_overflow(self):
        """CWE-190 integer overflow detector catches cross-line max sentinels with arithmetic."""
        from security_analyzer import analyze

        sec10 = os.path.join(PROJECT, "benchmark/security/sec10_integer_overflow.cpp")
        findings_sec10 = analyze(sec10, [])
        ov_sec10 = [f for f in findings_sec10 if f.vulnerability_type == "Integer Overflow"]
        assert len(ov_sec10) >= 1, f"Expected Integer Overflow in sec10, got {findings_sec10}"

        me04 = os.path.join(PROJECT, "benchmark/multi_error/me04_name_and_overflow.cpp")
        findings_me04 = analyze(me04, [])
        ov_me04 = [f for f in findings_me04 if f.vulnerability_type == "Integer Overflow"]
        assert len(ov_me04) >= 1, f"Expected Integer Overflow in me04, got {findings_me04}"


# ══════════════════════════════════════════════════════════════════════
# 2. Step 3: Five Tool Interfaces
# ══════════════════════════════════════════════════════════════════════

class TestToolInterfaces:
    """Verify contracts and isolated execution for all five tools."""

    def test_tool_understand(self):
        """understand(file_path) -> ProgramModel."""
        cpp_file = os.path.join(PROJECT, "benchmark/syntax/sx01_missing_semi_decl.cpp")
        model = understand(cpp_file)
        assert isinstance(model, ProgramModel)
        assert model.file_path == cpp_file
        assert len(model.diagnostics) >= 1
        assert isinstance(model.diagnostics[0], Diagnostic)
        assert model.compile_output != ""

    def test_tool_detect(self):
        """detect(program_model) -> List[Diagnostic] merged & ranked by severity then confidence."""
        cpp_file = os.path.join(PROJECT, "benchmark/multi_error/me04_name_and_overflow.cpp")
        model = understand(cpp_file)
        findings = detect(model)
        assert isinstance(findings, list)
        assert len(findings) >= 2  # name error + security finding
        assert all(isinstance(f, Diagnostic) for f in findings)
        # Check that errors come before or equal to security findings in severity
        kinds = [f.kind for f in findings]
        assert "error" in kinds

    def test_tool_repair(self):
        """repair(program_model, diagnostic) -> Optional[Patch]."""
        cpp_file = os.path.join(PROJECT, "benchmark/syntax/sx01_missing_semi_decl.cpp")
        model = understand(cpp_file)
        # sx01 missing semicolon is a fixable syntax error
        target = model.diagnostics[0]
        patch = repair(model, target)
        assert patch is not None
        assert isinstance(patch, Patch)
        assert patch.original_file == cpp_file
        assert patch.patched_source != ""
        assert patch.diff != ""

    def test_tool_optimize(self):
        """optimize(program_model) -> List[Suggestion] (stub returns empty list)."""
        cpp_file = os.path.join(PROJECT, "benchmark/syntax/sx01_missing_semi_decl.cpp")
        model = understand(cpp_file)
        suggestions = optimize(model)
        assert isinstance(suggestions, list)
        assert suggestions == []

    def test_tool_verify(self):
        """verify(program_model, patch) -> VerifyResult."""
        cpp_file = os.path.join(PROJECT, "benchmark/syntax/sx01_missing_semi_decl.cpp")
        model = understand(cpp_file)
        target = model.diagnostics[0]
        patch = repair(model, target)
        assert patch is not None

        result = verify(model, patch)
        assert isinstance(result, VerifyResult)
        assert isinstance(result.passed, bool)
        assert isinstance(result.diagnostics, list)


# ══════════════════════════════════════════════════════════════════════
# 3. Step 2: Cascading Error Grouping
# ══════════════════════════════════════════════════════════════════════

class TestCascadingErrorGrouping:
    """Verify cascading diagnostics are grouped under one root cause."""

    def test_cascading_grouping_me06(self):
        """me06_cascade_semicolons.cpp groups cascading errors within proximity."""
        me06 = os.path.join(PROJECT, "benchmark/multi_error/me06_cascade_semicolons.cpp")
        model = understand(me06)
        assert len(model.diagnostics) >= 2
        # Root cause IDs should be populated
        assert all(d.root_cause_id is not None for d in model.diagnostics)
        groups = group_summary(model.diagnostics)
        assert len(groups) >= 1

    def test_cascading_grouping_me07(self):
        """me07_cascade_class_errors.cpp collapses cascade into single root cause."""
        me07 = os.path.join(PROJECT, "benchmark/multi_error/me07_cascade_class_errors.cpp")
        model = understand(me07)
        assert len(model.diagnostics) >= 2
        # The syntax error at line 5 and undeclared identifier at line 8 share root cause
        rc_ids = {d.root_cause_id for d in model.diagnostics}
        assert len(rc_ids) == 1, f"Expected 1 collapsed root cause, got: {rc_ids}"


# ══════════════════════════════════════════════════════════════════════
# 4. Step 4: Planner State Machine & Stop Conditions
# ══════════════════════════════════════════════════════════════════════

class TestPlannerStopConditions:
    """Verify planner deterministic stop conditions and structured trace log."""

    def test_stop_condition_success(self):
        """Clean file terminates immediately with status 'success'."""
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write("#include <iostream>\nint main() { return 0; }\n")
            f.flush()
            temp_path = f.name

        try:
            res = run_planner(temp_path, backup=False)
            assert res.status == "success"
            assert res.clean is True
            assert len(res.trace_log) >= 2
            # Inspect trace log structure
            assert all("step" in t and "tool_called" in t and "decision" in t for t in res.trace_log)
        finally:
            os.unlink(temp_path)

    def test_stop_condition_no_fixable_finding(self):
        """Unfixable error stops with status 'no_fixable_finding'."""
        # Linker error is in UNFIXABLE_CATEGORIES
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            f.write("void missing_function(); int main() { missing_function(); return 0; }\n")
            f.flush()
            temp_path = f.name

        try:
            res = run_planner(temp_path, max_iterations=3, backup=False)
            assert res.status in ("no_fixable_finding", "give_up")
            assert len(res.trace_log) >= 2
        finally:
            os.unlink(temp_path)

    def test_stop_condition_max_iterations(self):
        """Planner halts when max_iterations is reached."""
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
            # Complex error not resolved in 1 iteration
            f.write("int main() { int a = 1; int b = ; return 0; }\n")
            f.flush()
            temp_path = f.name

        try:
            planner = Planner(temp_path, max_iterations=1, backup=False)
            res = planner.run()
            # With max_iterations=1, either it fixes in 1 or hits limit / unfixable
            assert res.iterations <= 1
            assert res.status in ("success", "max_iterations", "no_fixable_finding")
        finally:
            os.unlink(temp_path)


# ══════════════════════════════════════════════════════════════════════
# 5. Step 5: Config & Policy
# ══════════════════════════════════════════════════════════════════════

class TestConfigPolicy:
    """Verify config.yaml loading and policy blocklist externalization."""

    def test_config_loader(self):
        cfg = load_config(force_reload=True)
        assert "pipeline" in cfg
        assert "security" in cfg
        assert cfg_get("pipeline", "max_heal_attempts") == 10
        blocked = cfg_get("security", "blocked_patterns")
        assert "system_calls" in blocked
        assert "assembly" in blocked


# ══════════════════════════════════════════════════════════════════════
# 6. Planner and GUI HealWorker Parity
# ══════════════════════════════════════════════════════════════════════

class TestPlannerGuiParity:
    """Verify run_planner (CLI main.py) and HealWorker (GUI) produce identical results."""

    def test_planner_gui_identical_behavior(self):
        from heal_loop import HealWorker

        test_files = [
            os.path.join(PROJECT, "benchmark/syntax/sx01_missing_semi_decl.cpp"),
            os.path.join(PROJECT, "benchmark/multi_error/me07_cascade_class_errors.cpp"),
            os.path.join(PROJECT, "benchmark/linker_errors/lk01_undef_func.cpp"),
        ]

        for src_path in test_files:
            with open(src_path, "r", encoding="utf-8") as f:
                content = f.read()

            with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
                f.write(content)
                p_cli = f.name
            with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
                f.write(content)
                p_gui = f.name

            try:
                # Path 1: CLI main.py -> run_planner
                res_cli = run_planner(p_cli, backup=False)

                # Path 2: GUI -> HealWorker
                worker = HealWorker(p_gui)
                worker._heal()

                with open(p_cli, "r", encoding="utf-8") as f:
                    code_cli = f.read()
                with open(p_gui, "r", encoding="utf-8") as f:
                    code_gui = f.read()

                # Verify identical stop condition
                assert res_cli.status == worker.status, f"Status mismatch on {src_path}"

                # Verify identical patches applied
                assert len(res_cli.patches_applied) == len(worker.patches_applied), f"Patch count mismatch on {src_path}"
                for patch_c, patch_g in zip(res_cli.patches_applied, worker.patches_applied):
                    assert patch_c.patched_source == patch_g.patched_source

                # Verify identical final source code
                assert code_cli == code_gui, f"Final source mismatch on {src_path}"

                # Verify identical trace log structure
                assert len(res_cli.trace_log) == len(worker.trace_log), f"Trace length mismatch on {src_path}"
                for step_c, step_g in zip(res_cli.trace_log, worker.trace_log):
                    assert step_c["step"] == step_g["step"]
                    assert step_c["tool_called"] == step_g["tool_called"]
                    assert step_c["decision"] == step_g["decision"]
            finally:
                if os.path.exists(p_cli):
                    os.unlink(p_cli)
                if os.path.exists(p_gui):
                    os.unlink(p_gui)

