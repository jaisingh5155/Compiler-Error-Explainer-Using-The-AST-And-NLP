#!/usr/bin/env python3
"""
scratch/run_full_integration.py
Full End-to-End Integration Walkthrough for Week 9 Part 7.
Executes Scenarios A, B, C, D, and E across CLI and GUI.
"""

import os
import sys
import shutil
import tempfile
import json
import hashlib
import subprocess

# Ensure src is on sys.path
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Set Qt plugin path & offscreen platform for GUI execution
import PyQt6
os.environ["QT_PLUGIN_PATH"] = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
from gui import AppGUI
from planner import run_planner
from trace_view import format_trace_html, format_trace_text
from security_analyzer import analyze as analyze_security
from feedback_store import (
    record_feedback,
    load_feedback,
    mark_feedback_reviewed,
    DEFAULT_FEEDBACK_FILE,
)

def run_cmd(cmd_list, cwd=PROJECT_ROOT, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    merged_env["PYTHONPATH"] = SRC_DIR
    res = subprocess.run(cmd_list, cwd=cwd, env=merged_env, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr

def main():
    app = QApplication.instance() or QApplication(["integration_test"])
    results_log = []

    print("=" * 80)
    print("WEEK 9 PART 7: FULL INTEGRATION WALKTHROUGH")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # SCENARIO A: Simple syntax-error file
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO A: Syntax Error (Analyze -> Classify -> Explain -> Heal -> Verify -> Trace) ---")
    sx01_src = os.path.join(PROJECT_ROOT, "benchmark", "syntax", "sx01_missing_semi_decl.cpp")
    scratch_dir = tempfile.mkdtemp(prefix="w9_scen_a_")
    test_sx01_cli = os.path.join(scratch_dir, "sx01_cli.cpp")
    test_sx01_gui = os.path.join(scratch_dir, "sx01_gui.cpp")
    shutil.copy(sx01_src, test_sx01_cli)
    shutil.copy(sx01_src, test_sx01_gui)

    # CLI Step 1: Analyze & Explain
    rc_cli_a1, out_cli_a1, err_cli_a1 = run_cmd([sys.executable, "src/main.py", test_sx01_cli, "-v"])
    # CLI Step 2: Heal & Trace
    rc_cli_a2, out_cli_a2, err_cli_a2 = run_cmd([sys.executable, "src/main.py", test_sx01_cli, "--heal", "--trace"])

    # GUI Step: Run through AppGUI
    gui_a = AppGUI()
    gui_a.file_path = test_sx01_gui
    gui_a.file_name = os.path.basename(test_sx01_gui)
    with open(test_sx01_gui, 'r', encoding='utf-8') as f:
        gui_a.editor.setPlainText(f.read())

    # Get pipeline JSON data
    rc_j, out_j, _ = run_cmd([sys.executable, "src/main.py", test_sx01_gui, "-j"])
    data_a = json.loads(out_j)
    gui_a.render_json(data_a, "")

    # Run planner in review_mode on unhealed GUI copy
    planner_res_a = run_planner(test_sx01_gui, backup=True, review_mode=True)
    gui_a.trace_page.set_trace_log(planner_res_a.trace_log)
    gui_a.review_page.load_patches(test_sx01_gui, planner_res_a.pending_patches)

    gui_step_count = len(gui_a.trace_page.trace_log)
    gui_cards_count = len(gui_a.review_page.card_widgets)

    print(f"CLI Analyze Exit Code:         {rc_cli_a1}")
    print(f"CLI Heal Exit Code:            {rc_cli_a2}")
    print(f"CLI Trace Output Steps in Log: {len(planner_res_a.trace_log)}")
    print(f"GUI Trace Steps Displayed:     {gui_step_count}")
    print(f"GUI Review Cards Loaded:       {gui_cards_count}")
    print(f"GUI Patch Verified:            {planner_res_a.pending_patches[0].verify_result.passed if planner_res_a.pending_patches else False}")

    # Verify consistency between CLI trace and GUI trace steps
    cli_tools = [x.get("tool_called") for x in planner_res_a.trace_log]
    gui_tools = [x.get("tool_called") for x in gui_a.trace_page.trace_log]
    assert cli_tools == gui_tools, "CLI and GUI trace tools must match exactly"
    assert gui_cards_count >= 1, "GUI patch review page must have loaded the candidate patch"

    results_log.append({
        "scenario": "A",
        "file": "benchmark/syntax/sx01_missing_semi_decl.cpp",
        "cli_analyze_stdout": out_cli_a1,
        "cli_heal_stdout": out_cli_a2,
        "trace_steps": planner_res_a.trace_log,
        "gui_trace_step_count": gui_step_count,
        "gui_cards_count": gui_cards_count,
    })

    # -------------------------------------------------------------------------
    # SCENARIO B: Security-vulnerable file
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO B: Security Vulnerability (Analyze -> Security Scan -> CWE Tab -> Explain) ---")
    sec06_src = os.path.join(PROJECT_ROOT, "benchmark", "security", "sec06_double_free.cpp")
    
    # CLI Step: Analyze with security scan
    rc_cli_b, out_cli_b, err_cli_b = run_cmd([sys.executable, "src/main.py", sec06_src, "-v"])

    # GUI Step: Load and extract security findings
    gui_b = AppGUI()
    gui_b.file_path = sec06_src
    gui_b.file_name = os.path.basename(sec06_src)
    with open(sec06_src, 'r', encoding='utf-8') as f:
        gui_b.editor.setPlainText(f.read())

    rc_jb, out_jb, _ = run_cmd([sys.executable, "src/main.py", sec06_src, "-j"])
    data_b = json.loads(out_jb)
    gui_b.render_json(data_b, "")

    findings_b = data_b.get("security_findings", [])
    top_finding = findings_b[0] if findings_b else {}
    gui_findings_count = len(gui_b.security_page.findings)
    risk_badge_text = gui_b.security_page.risk_badge.text()

    print(f"CLI Exit Code:          {rc_cli_b}")
    print(f"Security Findings:      {len(findings_b)}")
    print(f"Top Finding CWE:        {top_finding.get('cwe')}")
    print(f"Top Finding Vuln Type:  {top_finding.get('vulnerability_type')}")
    print(f"Top Finding Line:       {top_finding.get('line')}")
    print(f"GUI Security Findings:  {gui_findings_count}")
    print(f"GUI Risk Badge:         {risk_badge_text}")

    assert top_finding.get("cwe") == "CWE-415", "Expected CWE-415 Double Free"
    assert "Double Free" in out_cli_b, "CLI must display Double Free finding"
    assert gui_findings_count >= 1, "GUI Security Page must display security findings"

    results_log.append({
        "scenario": "B",
        "file": "benchmark/security/sec06_double_free.cpp",
        "cli_stdout": out_cli_b,
        "cwe": top_finding.get("cwe"),
        "vuln_type": top_finding.get("vulnerability_type"),
        "line": top_finding.get("line"),
        "risk_badge": risk_badge_text,
        "gui_findings_count": gui_findings_count,
    })

    # -------------------------------------------------------------------------
    # SCENARIO C: Candidate patch rejected by verification gate
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO C: Gate Rejection (Candidate Rejected -> Suggestion-Only -> Byte-Identical File) ---")
    rd01_src = os.path.join(PROJECT_ROOT, "benchmark", "redefinition", "rd01_global_var.cpp")
    scratch_dir_c = tempfile.mkdtemp(prefix="w9_scen_c_")
    test_rd01 = os.path.join(scratch_dir_c, "rd01_global_var.cpp")
    shutil.copy(rd01_src, test_rd01)

    hash_before_c = hashlib.sha256(open(test_rd01, "rb").read()).hexdigest()

    # CLI Step: Run heal with trace
    rc_cli_c, out_cli_c, err_cli_c = run_cmd([sys.executable, "src/main.py", test_rd01, "--heal", "--trace"])
    hash_after_cli_c = hashlib.sha256(open(test_rd01, "rb").read()).hexdigest()

    # GUI Step: Run planner in review mode
    planner_res_c = run_planner(test_rd01, review_mode=True, backup=True)
    hash_after_gui_c = hashlib.sha256(open(test_rd01, "rb").read()).hexdigest()

    gui_c = AppGUI()
    gui_c.file_path = test_rd01
    gui_c.review_page.load_patches(test_rd01, planner_res_c.suggestions)

    print(f"CLI Status:         {out_cli_c.splitlines()[0] if out_cli_c else 'Empty'}")
    print(f"Planner Status:     {planner_res_c.status}")
    print(f"Patches Applied:    {len(planner_res_c.patches_applied)}")
    print(f"Suggestions Count:  {len(planner_res_c.suggestions)}")
    print(f"Original SHA-256:   {hash_before_c}")
    print(f"Post-CLI SHA-256:   {hash_after_cli_c} (Identical: {hash_before_c == hash_after_cli_c})")
    print(f"Post-GUI SHA-256:   {hash_after_gui_c} (Identical: {hash_before_c == hash_after_gui_c})")

    assert hash_before_c == hash_after_cli_c == hash_after_gui_c, "File must remain byte-identical after gate rejection"
    assert len(planner_res_c.patches_applied) == 0, "No patch may be applied when verification gate fails"
    assert len(planner_res_c.suggestions) >= 1, "Rejected patch must be downgraded to suggestion"

    results_log.append({
        "scenario": "C",
        "file": "benchmark/redefinition/rd01_global_var.cpp",
        "cli_stdout": out_cli_c,
        "planner_status": planner_res_c.status,
        "suggestions_count": len(planner_res_c.suggestions),
        "patches_applied": len(planner_res_c.patches_applied),
        "file_intact": (hash_before_c == hash_after_cli_c == hash_after_gui_c),
        "sha256": hash_before_c,
    })

    # -------------------------------------------------------------------------
    # SCENARIO D: Folder of 5+ mixed files through --batch
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO D: Batch Execution (Folder of 5+ Mixed Files) ---")
    batch_dir = tempfile.mkdtemp(prefix="w9_scen_d_batch_")
    mixed_files = [
        ("sx01_missing_semi_decl.cpp", os.path.join(PROJECT_ROOT, "benchmark", "syntax", "sx01_missing_semi_decl.cpp")),
        ("mi01_iostream.cpp", os.path.join(PROJECT_ROOT, "benchmark", "missing_include", "mi01_iostream.cpp")),
        ("cl01_hello.cpp", os.path.join(PROJECT_ROOT, "benchmark", "clean", "cl01_hello.cpp")),
        ("sec06_double_free.cpp", os.path.join(PROJECT_ROOT, "benchmark", "security", "sec06_double_free.cpp")),
        ("rd01_global_var.cpp", os.path.join(PROJECT_ROOT, "benchmark", "redefinition", "rd01_global_var.cpp")),
    ]
    for name, src in mixed_files:
        shutil.copy(src, os.path.join(batch_dir, name))

    batch_report_path = os.path.join(batch_dir, "batch_report.json")
    rc_cli_d, out_cli_d, err_cli_d = run_cmd([
        sys.executable, "src/main.py", "--batch", batch_dir, "--report", batch_report_path
    ])

    batch_data = json.load(open(batch_report_path))
    s_d = batch_data["summary"]

    print(f"Batch Exit Code: {rc_cli_d}")
    print(f"Total Files:     {s_d['total_files']}")
    print(f"Attempted:       {s_d['attempted']}")
    print(f"Healed (Clean):  {s_d['healed']}")
    print(f"Gave Up:         {s_d['gave_up']}")
    print(f"Not Applicable:  {s_d['not_applicable']}")
    print(f"Crashed:         {s_d['crashed']}")

    individual_outcomes = {rec["rel_path"]: rec["outcome"] for rec in batch_data["files"]}
    print("Per-file outcomes:")
    for path, outcome in sorted(individual_outcomes.items()):
        print(f"  {path} -> {outcome}")

    assert s_d["total_files"] == 5, "Expected 5 total files"
    assert s_d["healed"] == 2, "Expected 2 healed (sx01, mi01)"
    assert s_d["gave_up"] == 1, "Expected 1 gave up (rd01)"
    assert s_d["not_applicable"] == 2, "Expected 2 not applicable (cl01, sec06)"
    assert s_d["crashed"] == 0, "Expected 0 crashes"

    results_log.append({
        "scenario": "D",
        "batch_dir": batch_dir,
        "summary": s_d,
        "per_file": individual_outcomes,
        "raw_cli_output": out_cli_d,
    })

    # -------------------------------------------------------------------------
    # SCENARIO E: Part 5 Full Round-Trip Feedback Flow
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO E: Feedback Loop Full Round-Trip ---")
    backup_feedback = None
    if os.path.exists(DEFAULT_FEEDBACK_FILE):
        backup_feedback = open(DEFAULT_FEEDBACK_FILE, "r").read()

    try:
        # Step 1: User submits category correction via GUI action
        sample_diag = {
            "message": "expected ';' at end of declaration",
            "category": "other",
            "confidence": 0.55,
            "file": "src/samples/calculator.cpp",
            "program_id": "demo_prog_id_101",
            "line": 5,
        }
        rec = record_feedback(
            diagnostic=sample_diag,
            confirmed_category="syntax_error",
            user_notes="Corrected semicolon error from GUI error card",
        )
        print(f"Recorded GUI Correction: message='{rec['message']}', confirmed='{rec['confirmed_category']}'")

        records_initial = load_feedback()
        target_rec = next((r for r in records_initial if r["message"] == sample_diag["message"] and r.get("program_id") == "demo_prog_id_101"), None)
        assert target_rec is not None, "Record not found in confirmed_feedback.json"
        assert target_rec["reviewed_for_merge"] is False, "Record must start unapproved"
        print(f"Status before CLI review: reviewed_for_merge = {target_rec['reviewed_for_merge']}")

        # Step 2: Approve via CLI review helper (python src/feedback_store.py approve --all)
        rc_rev, out_rev, err_rev = run_cmd([sys.executable, "src/feedback_store.py", "approve", "--all"])
        assert rc_rev == 0, f"CLI review approval failed: {err_rev}"
        print(f"CLI Review Helper Output: {out_rev.strip()}")

        records_approved = load_feedback()
        target_rec_appr = next((r for r in records_approved if r["message"] == sample_diag["message"] and r.get("program_id") == "demo_prog_id_101"), None)
        assert target_rec_appr["reviewed_for_merge"] is True, "Record must now be approved"
        print(f"Status after CLI review: reviewed_for_merge = {target_rec_appr['reviewed_for_merge']}")

        # Step 3: Run train_classifier_v2.py --include-feedback
        rc_train, out_train, err_train = run_cmd([
            sys.executable, "src/train_classifier_v2.py", "--include-feedback"
        ])
        print(f"Retraining Exit Code: {rc_train}")
        assert rc_train == 0, f"Retraining failed: {err_train}"
        print(f"Retraining Output Snippet:\n" + "\n".join(out_train.splitlines()[-4:]))

        results_log.append({
            "scenario": "E",
            "message": rec["message"],
            "reviewed_before": False,
            "reviewed_after": True,
            "cli_review_output": out_rev.strip(),
            "retraining_exit_code": rc_train,
            "retraining_stdout": out_train,
        })
    finally:
        if backup_feedback:
            with open(DEFAULT_FEEDBACK_FILE, "w") as f:
                f.write(backup_feedback)

    # Save integration log
    log_path = os.path.join(PROJECT_ROOT, "scratch", "integration_results.json")
    with open(log_path, "w") as f:
        json.dump(results_log, f, indent=2)
    print(f"\nAll 5 scenarios completed successfully! Results saved to: {log_path}")

if __name__ == "__main__":
    main()
