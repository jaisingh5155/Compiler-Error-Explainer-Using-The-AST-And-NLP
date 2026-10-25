import os
import sys
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop, QTimer

# Ensure offscreen rendering if headless
os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.abspath("src"))
from gui import AppGUI

def run_capture():
    app = QApplication(sys.argv)
    gui = AppGUI()
    gui.resize(1400, 900)
    gui.show()
    app.processEvents()

    os.makedirs("screenshots", exist_ok=True)
    artifact_sc_dir = "/Users/jaisinghsaini/.gemini/antigravity-ide/brain/4aee7862-3232-450c-b47d-64569f18d7a2/screenshots"
    os.makedirs(artifact_sc_dir, exist_ok=True)

    def wait_for_heal_worker(timeout_sec=60):
        start = time.time()
        # Wait for worker to start running
        while time.time() - start < 5.0:
            app.processEvents()
            if hasattr(gui, "heal_worker") and gui.heal_worker is not None and gui.heal_worker.isRunning():
                break
            time.sleep(0.02)
        # Wait for worker to finish
        while time.time() - start < timeout_sec:
            app.processEvents()
            if hasattr(gui, "heal_worker") and gui.heal_worker is not None:
                if gui.heal_worker.isFinished():
                    break
            time.sleep(0.05)
        # Give events time to settle (signal emission, widget layout update)
        for _ in range(15):
            app.processEvents()
            time.sleep(0.05)

    def save_pixmap(widget, name):
        p1 = os.path.join("screenshots", name)
        p2 = os.path.join(artifact_sc_dir, name)
        pix = widget.grab()
        pix.save(p1)
        pix.save(p2)
        print(f"Saved {p1} ({pix.width()}x{pix.height()})")

    # ==========================================
    # SCENARIO 1: Gate 6 Malicious Patch Exfiltration
    # File: benchmark/agent_attacks/attack_patch_01_env_exfil.cpp
    # ==========================================
    f_exfil = os.path.abspath("benchmark/agent_attacks/attack_patch_01_env_exfil.cpp")
    print(f"\n--- Running Scenario 1: Gate 6 with {f_exfil} ---")
    gui.load_file(f_exfil)
    app.processEvents()

    # Trigger Review Mode
    gui.start_review()
    wait_for_heal_worker(60)

    # Make sure we are on review page
    gui.switch_to_review()
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()
    save_pixmap(gui, "test3_gate6_blocked_patch_review.png")

    # Switch to Trace page and capture trace
    gui.switch_to_trace()
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()
    save_pixmap(gui, "test3_gate6_agent_trace.png")

    # ==========================================
    # SCENARIO 2: Instruction Injection Attack
    # File: benchmark/agent_attacks/attack_inj_01_line_comment.cpp
    # ==========================================
    f_inj = os.path.abspath("benchmark/agent_attacks/attack_inj_01_line_comment.cpp")
    print(f"\n--- Running Scenario 2: Instruction Injection with {f_inj} ---")
    gui.load_file(f_inj)
    app.processEvents()

    gui.start_review()
    wait_for_heal_worker(60)

    gui.switch_to_review()
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()
    save_pixmap(gui, "test1_instruction_injection_patch_review.png")

    gui.switch_to_trace()
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()
    save_pixmap(gui, "test1_instruction_injection_agent_trace.png")

    # ==========================================
    # SCENARIO 3: Control / Normal File (file.cpp)
    # Proof that normal files do NOT receive any blocked cards or attack candidates
    # ==========================================
    f_ctrl = os.path.abspath("file.cpp")
    print(f"\n--- Running Scenario 3: Control File with {f_ctrl} ---")
    gui.load_file(f_ctrl)
    app.processEvents()

    gui.start_review()
    wait_for_heal_worker(60)

    gui.switch_to_review()
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()
    save_pixmap(gui, "control_file_patch_review.png")

    print("\nAll verification screenshots captured successfully.")
    app.quit()

if __name__ == "__main__":
    run_capture()
