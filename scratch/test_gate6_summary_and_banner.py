import os
import sys
import time

sys.path.insert(0, os.path.abspath("src"))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from gui import AppGUI
from planner import Planner
from tools.understand import understand

def test_headless_gui():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication(sys.argv)
    gui = AppGUI()
    gui.resize(1400, 900)
    gui.show()
    app.processEvents()

    # 1. Test C Scenario: attack_patch_01_env_exfil.cpp
    f_attack = os.path.abspath("benchmark/agent_attacks/attack_patch_01_env_exfil.cpp")
    print(f"\n[Test C] Loading attack file: {f_attack}")
    gui.load_file(f_attack)
    app.processEvents()

    # Run Compile first
    print("[Test C] Compiling...")
    gui.analyze()
    # Wait for compiler thread
    start = time.time()
    while time.time() - start < 10.0:
        app.processEvents()
        if not gui.is_loading:
            break
        time.sleep(0.05)

    print(f"[Test C] Errors count after compile: {gui.errors_count}, warnings: {gui.warnings_count}")

    # Now Run Auto-Heal (start_heal)
    print("[Test C] Running Auto-Heal...")
    gui.start_heal()
    start = time.time()
    while time.time() - start < 60.0:
        app.processEvents()
        if hasattr(gui, "heal_worker") and gui.heal_worker is not None and gui.heal_worker.isFinished():
            break
        time.sleep(0.05)

    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)

    # Verify Agent Trace status text
    trace_page = gui.trace_page
    trace_status_text = trace_page.lbl_status.text()
    print(f"[Test C] Agent Trace lbl_status: {trace_status_text}")
    assert "GOAL MET: COMPILATION CLEAN AND SECURE (1 malicious patch attempt blocked during this session)" in trace_status_text, f"Unexpected trace status: {trace_status_text}"

    # Verify final planner step
    last_step = trace_page.trace_log[-1]
    last_decision = last_step.get("decision", "")
    print(f"[Test C] Final planner step decision: {last_decision}")
    assert "Goal met: compilation clean and secure (1 malicious patch attempt blocked during this session)" in last_decision, f"Unexpected decision: {last_decision}"

    # Switch to Security Tab
    gui.switch_to_security()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()

    sec_page = gui.security_page
    print(f"[Test C] Security tab summary: {sec_page.summary.text()}")
    print(f"[Test C] Security tab risk badge: {sec_page.risk_badge.text()}")
    assert "0 critical, 0 high, 0 medium, 0 low findings" in sec_page.summary.text()
    assert sec_page.session_gate6_blocked == 1, f"Expected 1 blocked attack in session, got {sec_page.session_gate6_blocked}"

    # Check for banner in report_layout
    banner_found = False
    banner_text = ""
    for i in range(sec_page.report_layout.count()):
        w = sec_page.report_layout.itemAt(i).widget()
        if w and w.objectName() == "BlockedAttacksBanner":
            banner_found = True
            for child in w.findChildren(type(gui.status_label)):
                if "Note:" in child.text():
                    banner_text = child.text()
            break
    print(f"[Test C] Security tab banner found: {banner_found}")
    print(f"[Test C] Security tab banner text: {banner_text}")
    import re
    plain_banner_text = re.sub(r'<[^>]+>', '', banner_text)
    print(f"[Test C] Plain banner text: {plain_banner_text}")
    assert "1 malicious patch attempt was detected and blocked" in plain_banner_text or "1 malicious patch attempt was detected and blocked" in banner_text

    # Verify Tooltip & Info Icon (Task 3)
    info_tooltip = sec_page.info_icon.toolTip()
    expected_tooltip = "This scans the current source file on disk. Blocked patch attempts (including malicious candidates rejected before being applied) are shown separately in Patch Review."
    print(f"[Test C] Info icon tooltip: {info_tooltip}")
    assert info_tooltip == expected_tooltip, f"Tooltip mismatch: {info_tooltip}"

    # Save screenshots of Test C
    os.makedirs("screenshots", exist_ok=True)
    # Trace page screenshot
    gui.switch_to_trace()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    gui.grab().save("screenshots/test_c_trace_page.png")

    # Security page screenshot
    gui.switch_to_security()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    gui.grab().save("screenshots/test_c_security_page.png")

    try:
        from PIL import Image
        im1 = Image.open("screenshots/test_c_trace_page.png")
        im2 = Image.open("screenshots/test_c_security_page.png")
        combined = Image.new("RGB", (max(im1.width, im2.width), im1.height + im2.height))
        combined.paste(im1, (0, 0))
        combined.paste(im2, (0, im1.height))
        combined.save("screenshots/test_c_trace_and_security_combined.png")
    except Exception as e:
        print(f"Combined image creation skipped: {e}")

    # 2. Control / Ordinary File Test (no attack): sx01_missing_semi_decl.cpp or file.cpp
    f_ordinary = os.path.abspath("benchmark/syntax/sx01_missing_semi_decl.cpp")
    print(f"\n[Ordinary File] Loading: {f_ordinary}")
    gui.load_file(f_ordinary)
    app.processEvents()

    print("[Ordinary File] Running Auto-Heal...")
    gui.start_heal()
    start = time.time()
    while time.time() - start < 60.0:
        app.processEvents()
        if hasattr(gui, "heal_worker") and gui.heal_worker is not None and gui.heal_worker.isFinished():
            break
        time.sleep(0.05)

    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)

    ord_trace_status = gui.trace_page.lbl_status.text()
    print(f"[Ordinary File] Agent Trace lbl_status: {ord_trace_status}")
    assert "malicious" not in ord_trace_status.lower(), f"Unexpected 'malicious' in ordinary trace status: {ord_trace_status}"

    gui.switch_to_security()
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()

    ord_sec_page = gui.security_page
    print(f"[Ordinary File] Security tab session_gate6_blocked: {ord_sec_page.session_gate6_blocked}")
    assert ord_sec_page.session_gate6_blocked == 0, f"Expected 0 gate6 blocked for ordinary file, got {ord_sec_page.session_gate6_blocked}"

    ord_banner_found = False
    for i in range(ord_sec_page.report_layout.count()):
        w = ord_sec_page.report_layout.itemAt(i).widget()
        if w and w.objectName() == "BlockedAttacksBanner":
            ord_banner_found = True
            break
    print(f"[Ordinary File] Security tab banner found: {ord_banner_found}")
    assert not ord_banner_found, "Banner should NOT be present for ordinary file!"

    gui.grab().save("screenshots/ordinary_file_security_page.png")

    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_headless_gui()
