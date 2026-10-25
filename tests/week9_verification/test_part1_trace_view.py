import os
import sys
import shutil
import tempfile
import pytest

# Ensure repo root and src/ are in sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from trace_view import format_trace_text, format_trace_html, summarize_trace
from planner import Planner, run_planner


def test_empty_trace():
    """Trace formatters and summary must handle empty trace logs gracefully without raising."""
    text = format_trace_text([])
    assert "No trace steps recorded" in text

    html_out = format_trace_html([])
    assert "<html" in html_out or "<div" in html_out
    assert "No trace steps recorded" in html_out

    summary = summarize_trace([])
    assert summary["total_steps"] == 0
    assert summary["patches_applied"] == 0
    assert summary["patches_rolled_back"] == 0
    assert summary["patches_pending"] == 0
    assert summary["stop_reason"] == "unknown"


def test_clean_heal_trace():
    """Verify trace logging and formatting on a clean heal run (nr04 or sx01)."""
    src_file = os.path.join(REPO_ROOT, "benchmark", "name_resolution", "nr04_keyword_cosnt.cpp")
    if not os.path.exists(src_file):
        src_file = os.path.join(REPO_ROOT, "benchmark", "syntax", "sx01_missing_semi_decl.cpp")

    assert os.path.exists(src_file)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_target = os.path.join(tmpdir, os.path.basename(src_file))
        shutil.copyfile(src_file, tmp_target)

        live_steps = []
        def step_cb(step_dict):
            live_steps.append(step_dict)

        result = run_planner(tmp_target, on_trace_step=step_cb, apply_to_disk=True)

        # Confirm live callback received steps
        assert len(live_steps) == len(result.trace_log)
        assert len(result.trace_log) > 0

        # Summarize
        summary = summarize_trace(result.trace_log)
        assert summary["total_steps"] == len(result.trace_log)
        assert summary["patches_applied"] >= 1
        assert "clean" in summary["stop_reason"].lower() or "success" in summary["stop_reason"].lower() or result.status == "success"

        # Format text
        text = format_trace_text(result.trace_log)
        assert "[Step 1]" in text
        assert "Action:" in text
        assert "Output:" in text

        # Format HTML
        html_out = format_trace_html(result.trace_log)
        assert "<!DOCTYPE html>" in html_out
        assert "Agent Execution Trace" in html_out
        assert "Step 1" in html_out
        # Verify gate section rendering if verify tool was called
        if any(s.get("tool_called") == "verify" for s in result.trace_log):
            assert "Verification Gates:" in text
            assert "gate-box" in html_out


def test_rollback_gate_failure_trace():
    """Verify trace logging, summary, and formatting when a patch fails verify gates and rolls back."""
    src_file = os.path.join(REPO_ROOT, "benchmark", "redefinition", "rd01_global_var.cpp")
    assert os.path.exists(src_file)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_target = os.path.join(tmpdir, os.path.basename(src_file))
        shutil.copyfile(src_file, tmp_target)

        result = run_planner(tmp_target)
        assert len(result.trace_log) > 0

        summary = summarize_trace(result.trace_log)
        # In rd01_global_var.cpp, gate fails (syntax/AST regression), so patch is rejected/rolled back
        assert summary["patches_rolled_back"] >= 1

        text = format_trace_text(result.trace_log)
        html_out = format_trace_html(result.trace_log)

        # Check failing gate reporting
        assert "FAIL" in text or "Reject" in text or "REJECTED BY" in text
        assert "gate-box" in html_out or "FAIL" in html_out or "Rejected by" in html_out


def test_no_fixable_finding_trace():
    """Verify trace logging when planner immediately gives up with no fixable findings."""
    src_file = os.path.join(REPO_ROOT, "benchmark", "linker_errors", "lk01_undef_func.cpp")
    assert os.path.exists(src_file)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_target = os.path.join(tmpdir, os.path.basename(src_file))
        shutil.copyfile(src_file, tmp_target)

        result = run_planner(tmp_target)
        summary = summarize_trace(result.trace_log)

        assert "no fixable finding" in summary["stop_reason"].lower()
        assert result.status == "no_fixable_finding"
        assert summary["patches_applied"] == 0

        text = format_trace_text(result.trace_log)
        assert "no fixable finding" in text.lower()

        html_out = format_trace_html(result.trace_log)
        assert "no fixable finding" in html_out.lower()


def test_max_iterations_trace():
    """Verify trace summary and formatting when max_iterations stops the planner."""
    synthetic_trace = [
        {"step": 1, "tool_called": "understand", "input_summary": "file.cpp", "output_summary": "AST built", "decision": "proceed"},
        {"step": 2, "tool_called": "detect", "input_summary": "errors", "output_summary": "1 error", "decision": "proceed"},
        {"step": 3, "tool_called": "repair", "input_summary": "error 1", "output_summary": "patch proposed", "decision": "proceed"},
        {"step": 4, "tool_called": "verify", "input_summary": "patch 1", "output_summary": "gate failed", "decision": "rollback",
         "gate_details": {"clean_compile": {"passed": False, "reason": "compilation failed"}}, "failing_gate": "clean_compile"},
        {"step": 5, "tool_called": "planner", "input_summary": "iteration check", "output_summary": "limit reached", "decision": "max_iterations"},
    ]

    summary = summarize_trace(synthetic_trace)
    assert summary["total_steps"] == 5
    assert summary["stop_reason"] == "max_iterations"
    assert summary["patches_rolled_back"] == 1
    assert summary["tool_counts"]["understand"] == 1
    assert summary["tool_counts"]["verify"] == 1

    text = format_trace_text(synthetic_trace)
    assert "max_iterations" in text
    assert "clean_compile" in text

    html_out = format_trace_html(synthetic_trace)
    assert "max_iterations" in html_out
    assert "clean_compile" in html_out


def test_gui_offscreen_smoke():
    """Construct AgentTracePage and AppGUI in offscreen Qt mode to confirm no crashes."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PyQt6.QtWidgets import QApplication
        import gui
    except (ImportError, Exception) as e:
        pytest.skip(f"PyQt6 not available or cannot initialize in offscreen mode: {e}")

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    trace_page = gui.AgentTracePage()
    assert trace_page is not None

    sample_step = {
        "step": 1,
        "tool_called": "understand",
        "input_summary": "test.cpp",
        "output_summary": "parsed 1 function",
        "decision": "proceed"
    }
    trace_page.add_step(sample_step)
    assert trace_page.lbl_steps.text() == "Steps: 1"

    verify_step = {
        "step": 2,
        "tool_called": "verify",
        "input_summary": "check patch",
        "output_summary": "gate 1 passed",
        "decision": "applied",
        "gate_details": {
            "clean_compile": {"passed": True, "reason": "ok"},
            "no_error_cascades": {"passed": True, "reason": "no new errors"}
        },
        "failing_gate": None
    }
    trace_page.add_step(verify_step)
    assert trace_page.lbl_steps.text() == "Steps: 2"
    # In universal review flow, planner does not auto-apply; applied count reflects user accepts
    assert trace_page.lbl_patches.text() == "Patches: Applied 0 | Rollbacks 0 | Pending 0"
    trace_page.set_user_applied_count(1)
    assert trace_page.lbl_patches.text() == "Patches: Applied 1 | Rollbacks 0 | Pending 0"

    trace_page.clear_trace()
    assert trace_page.lbl_steps.text() == "Steps: 0"
    assert trace_page.tree.topLevelItemCount() == 0

    # Also test AppGUI creation and tab switch
    win = gui.AppGUI()
    assert hasattr(win, "trace_page")
    win.switch_to_trace()
    assert win.stack.currentIndex() == 6
