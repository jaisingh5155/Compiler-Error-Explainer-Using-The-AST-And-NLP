"""
tests/week9_verification/test_part3_grouped_errors_and_security.py
──────────────────────────────────────────────────────────────────
Week 9 Part 3 Verification Suite:
- Grouping View-Model (Group, group_view_model, cascading error folding)
- me06_cascade_semicolons.cpp and me07_cascade_class_errors.cpp grouping parity (GUI vs CLI)
- CWE mapping: all scanner vulnerability types map to a non-empty canonical CWE ID
- CWE present for all 17 security benchmark findings
- Decoy false positive check: 0 findings across all 16 clean / decoy files
- Offscreen GUI smoke test for SecurityPage with CWE badges and grouped error cards
"""

import json
import os
import sys
import pytest

# Ensure src is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from diagnostic import Diagnostic, from_security_finding
from root_cause_grouper import Group, group_view_model, group_by_root_cause
from security_analyzer import (
    VULNERABILITY_CWE_MAP,
    get_cwe_for_vulnerability,
    SecurityFinding,
    analyze as analyze_security,
    _DIAGNOSTIC_RULES,
)
from tools.understand import understand
from tools.detect import detect


def test_group_view_model_unit():
    """Verify group_view_model handles empty, single, independent, and cascading errors."""
    # 1. Empty list
    assert group_view_model([]) == []

    # 2. Single diagnostic
    d1 = Diagnostic(kind="error", file="test.cpp", line=10, column=5, message="syntax error")
    groups = group_view_model([d1])
    assert len(groups) == 1
    assert groups[0].count == 1
    assert groups[0].root is d1
    assert groups[0].children == []

    # 3. Independent diagnostics (more than 5 lines apart)
    d2 = Diagnostic(kind="error", file="test.cpp", line=30, column=5, message="type mismatch")
    groups = group_view_model([d1, d2])
    assert len(groups) == 2
    assert groups[0].root.line == 10
    assert groups[0].count == 1
    assert groups[1].root.line == 30
    assert groups[1].count == 1

    # 4. Cascading diagnostics (within 5 lines)
    d3 = Diagnostic(kind="error", file="test.cpp", line=12, column=8, message="expected ';'")
    groups_cascade = group_view_model([d1, d3])
    assert len(groups_cascade) == 1
    assert groups_cascade[0].count == 2
    assert groups_cascade[0].root.line == 10
    assert len(groups_cascade[0].children) == 1
    assert groups_cascade[0].children[0].line == 12

    # 5. Dict representation parity (as received in GUI from JSON)
    dicts = [d1.to_dict(), d3.to_dict()]
    dict_groups = group_view_model(dicts)
    assert len(dict_groups) == 1
    assert dict_groups[0].count == 2
    assert dict_groups[0].root["line"] == 10
    assert dict_groups[0].children[0]["line"] == 12


def test_me06_and_me07_grouping_parity():
    """Verify grouping on me06_cascade_semicolons.cpp and me07_cascade_class_errors.cpp matches CLI."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    
    # ── me06: 2 missing semicolons on lines 5 & 7 ──
    me06_path = os.path.join(repo_root, "benchmark", "multi_error", "me06_cascade_semicolons.cpp")
    model_me06 = understand(me06_path)
    findings_me06 = detect(model_me06)
    compiler_me06 = [d for d in findings_me06 if d.kind in ("error", "warning")]
    
    cli_groups_me06 = group_view_model(compiler_me06)
    assert len(cli_groups_me06) == 1, f"Expected 1 cascade group for me06, got {len(cli_groups_me06)}"
    assert cli_groups_me06[0].root.line == 5
    assert cli_groups_me06[0].count == 2
    assert cli_groups_me06[0].children[0].line == 7

    # Verify dict representation (GUI path)
    gui_dicts_me06 = [d.to_dict() for d in compiler_me06]
    gui_groups_me06 = group_view_model(gui_dicts_me06)
    assert len(gui_groups_me06) == 1
    assert gui_groups_me06[0].root["line"] == 5
    assert gui_groups_me06[0].count == 2
    assert gui_groups_me06[0].children[0]["line"] == 7

    # ── me07: class error at line 5 cascading to line 8 ──
    me07_path = os.path.join(repo_root, "benchmark", "multi_error", "me07_cascade_class_errors.cpp")
    model_me07 = understand(me07_path)
    findings_me07 = detect(model_me07)
    compiler_me07 = [d for d in findings_me07 if d.kind in ("error", "warning")]

    cli_groups_me07 = group_view_model(compiler_me07)
    assert len(cli_groups_me07) == 1, f"Expected 1 cascade group for me07, got {len(cli_groups_me07)}"
    assert cli_groups_me07[0].root.line == 5
    assert cli_groups_me07[0].count == 2
    assert cli_groups_me07[0].children[0].line == 8

    gui_dicts_me07 = [d.to_dict() for d in compiler_me07]
    gui_groups_me07 = group_view_model(gui_dicts_me07)
    assert len(gui_groups_me07) == 1
    assert gui_groups_me07[0].root["line"] == 5
    assert gui_groups_me07[0].count == 2
    assert gui_groups_me07[0].children[0]["line"] == 8


def test_vulnerability_cwe_mapping_completeness():
    """Verify that every vulnerability type emitted by scanner rules has a canonical CWE ID."""
    assert len(VULNERABILITY_CWE_MAP) >= 20
    for vuln_type, cwe in VULNERABILITY_CWE_MAP.items():
        assert cwe.startswith("CWE-"), f"{vuln_type} mapped to invalid CWE: {cwe}"
        assert cwe != "CWE-Other"

    # Verify all diagnostic rules map to a valid CWE
    for rule in _DIAGNOSTIC_RULES:
        vuln_type = rule[2]
        cwe = get_cwe_for_vulnerability(vuln_type)
        assert cwe.startswith("CWE-") and cwe != "CWE-Other", f"Rule vuln_type {vuln_type} missing CWE mapping!"

    # Verify from_security_finding populates Diagnostic.cwe
    sf = SecurityFinding(
        file="test.cpp",
        line=1,
        column=1,
        severity="High",
        vulnerability_type="Command Injection",
        description="test",
        recommendation="test",
        source="static_scan",
    )
    diag = from_security_finding(sf)
    assert diag.cwe == "CWE-78"
    assert sf.to_dict()["cwe"] == "CWE-78"


def test_cwe_present_for_all_17_security_benchmarks():
    """Verify that every one of the 17 security benchmark targets produces findings with expected CWE."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    manifest_path = os.path.join(repo_root, "benchmark", "manifest.json")
    with open(manifest_path) as fp:
        manifest = json.load(fp)

    vuln_targets = [v for v in manifest["files"] if v.get("cwe")]
    assert len(vuln_targets) == 17, f"Expected exactly 17 vulnerable files in manifest, got {len(vuln_targets)}"

    for item in vuln_targets:
        file_path = os.path.join(repo_root, item["filepath"])
        expected_cwe = item["cwe"]

        model = understand(file_path)
        findings = detect(model)

        # Collect CWEs from security findings on diagnostics
        found_cwes = set()
        for d in findings:
            if d.cwe:
                found_cwes.add(d.cwe)
            for sf in d.security_findings:
                cwe_val = getattr(sf, "cwe", None) or (sf.get("cwe") if isinstance(sf, dict) else None)
                if cwe_val:
                    found_cwes.add(cwe_val)

        assert expected_cwe in found_cwes, (
            f"{item['filepath']}: Expected CWE {expected_cwe} was not found in detected CWEs: {found_cwes}"
        )


def test_no_false_positives_on_16_decoys():
    """Verify zero security false positives across the 16 clean / decoy files."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    
    # 16 clean/decoy files canonically defined in manifest:
    decoy_rel_paths = [
        # clean/
        "benchmark/clean/cl01_hello.cpp",
        "benchmark/clean/cl02_math.cpp",
        "benchmark/clean/cl03_loops.cpp",
        "benchmark/clean/cl04_struct.cpp",
        "benchmark/clean/cl05_class.cpp",
        "benchmark/clean/cl06_vector.cpp",
        "benchmark/clean/cl07_functions.cpp",
        "benchmark/clean/cl08_pointers.cpp",
        # security decoys & valid guarded patterns
        "benchmark/security/sec13_decoy_filesystem.cpp",
        "benchmark/security/sec14_decoy_safe_printf.cpp",
        "benchmark/security/sec15_decoy_safe_alloc.cpp",
        "benchmark/security/sec16_decoy_safe_delete.cpp",
        "benchmark/security/sec17_null_check_guarded.cpp",
        "benchmark/security/sec18_null_reassigned_valid.cpp",
        "benchmark/security/sec20_uninit_all_branches.cpp",
        "benchmark/security/sec22_uninit_output_param.cpp",
    ]
    assert len(decoy_rel_paths) == 16

    for rel_path in decoy_rel_paths:
        full_path = os.path.join(repo_root, rel_path)
        assert os.path.exists(full_path), f"Decoy file not found: {full_path}"

        model = understand(full_path)
        findings = detect(model)
        sec_findings = [d for d in findings if d.kind == "security" or (d.security_findings and d.kind != "error")]
        assert len(sec_findings) == 0, (
            f"False positive on decoy {rel_path}: {[d.message for d in sec_findings]}"
        )


def test_gui_offscreen_grouped_errors_and_security_smoke():
    """Offscreen smoke test verifying SecurityPage, SecurityCard with CWE, and grouped collapsible errors."""
    try:
        import PyQt6
        if "QT_PLUGIN_PATH" not in os.environ:
            plugin_dir = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins")
            if os.path.exists(plugin_dir):
                os.environ["QT_PLUGIN_PATH"] = plugin_dir
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        from gui import AppGUI, SecurityCard, SecurityPage
    except ImportError:
        pytest.skip("PyQt6 not available in this environment")

    app = QApplication.instance() or QApplication(sys.argv)

    window = AppGUI()
    assert window is not None

    # Test SecurityCard with CWE badge and Gate 4 status
    finding_dict = {
        "file": "test.cpp",
        "line": 42,
        "column": 5,
        "severity": "High",
        "vulnerability_type": "Command Injection",
        "cwe": "CWE-78",
        "description": "system() called with untrusted input",
        "recommendation": "Use execv",
        "source": "static_scan",
        "blocked_by_gate4": True,
    }
    card = SecurityCard(finding_dict, "#FF4D4D")
    assert card is not None
    assert "CWE-78" in card.title_label.text()

    # Test SecurityPage with findings
    sec_page = SecurityPage()
    sec_page.update_report([finding_dict])
    assert len(sec_page.findings) == 1
    assert sec_page.findings[0]["cwe"] == "CWE-78"
    assert sec_page.findings[0].get("blocked_by_gate4") is True

    # Test render_json with grouped errors in AppGUI
    test_json_data = {
        "status": "error",
        "error_count": 2,
        "warning_count": 0,
        "errors": [
            {
                "file": "me06.cpp",
                "line": 5,
                "column": 14,
                "error_type": "error",
                "message": "expected ';' at end of declaration",
                "root_cause_id": "rc-me06:5",
            },
            {
                "file": "me06.cpp",
                "line": 7,
                "column": 18,
                "error_type": "error",
                "message": "expected ';' at end of declaration",
                "root_cause_id": "rc-me06:5",
            },
        ],
        "security_findings": [finding_dict],
        "security_report": "1 high finding",
    }
    window.render_json(test_json_data, "")
    assert window.error_cards_layout.count() >= 2  # 1 root card + 1 follow-on collapsible widget

    # Find the collapsible follow-on widget and simulate clicking toggle
    collapsible = None
    toggle_btn = None
    for i in range(window.error_cards_layout.count()):
        w = window.error_cards_layout.itemAt(i).widget()
        # Look for the container holding the toggle QPushButton
        if w:
            for b in w.findChildren(type(card.toggle_btn)):
                if "follow-on" in b.text():
                    collapsible = w
                    toggle_btn = b
                    break
        if collapsible:
            break

    assert collapsible is not None
    assert toggle_btn is not None
    assert "1 follow-on error hidden" in toggle_btn.text()

    # Click toggle button to unfold
    toggle_btn.click()
    assert "Hide 1 follow-on error" in toggle_btn.text()

    # Click again to fold
    toggle_btn.click()
    assert "1 follow-on error hidden" in toggle_btn.text()
