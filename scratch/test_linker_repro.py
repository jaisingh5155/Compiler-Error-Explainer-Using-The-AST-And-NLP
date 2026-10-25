import os
import sys
import time

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from gui import AppGUI

def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv)

    window = AppGUI()
    window.resize(1200, 800)
    window.show()

    repro_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "benchmark", "linker_errors", "lk01_undef_func.cpp"))
    print(f"Loading repro file: {repro_file}")
    window.load_file(repro_file)

    print("Triggering Compile (analyze)...")
    window.analyze()

    # Wait for the background worker thread to finish
    max_wait = 15.0
    start = time.time()
    while window.is_loading and (time.time() - start) < max_wait:
        app.processEvents()
        time.sleep(0.05)

    # Allow AST worker and Qt event loop to settle
    settle_start = time.time()
    while (time.time() - settle_start) < 2.0:
        app.processEvents()
        time.sleep(0.05)

    print(f"Status label: {window.status_label.text()}")
    print(f"Errors count: {window.errors_count}, Warnings count: {window.warnings_count}")
    print(f"Error cards count: {window.error_cards_layout.count()}")

    terminal_text = window.terminal.toPlainText()
    print("--- Message Log Output ---")
    print(terminal_text)
    print("--------------------------")

    # Save screenshot of main editor + message log
    screenshot_dir = os.path.expanduser("~/.gemini/antigravity-ide/brain/455821f3-6953-439e-8cac-451b8f3c8267/screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)
    main_shot = os.path.join(screenshot_dir, "linker_error_repro_editor.png")
    window.grab().save(main_shot)
    print(f"Saved main screenshot to: {main_shot}")

    # Test navigating through all other diagnostic / analysis panels
    print("Testing Security Page...")
    window.switch_to_security()
    app.processEvents()
    window.grab().save(os.path.join(screenshot_dir, "linker_error_repro_security.png"))

    print("Testing Trace Page...")
    window.switch_to_trace()
    app.processEvents()
    window.grab().save(os.path.join(screenshot_dir, "linker_error_repro_trace.png"))

    print("Testing AST Page...")
    window.switch_to_ast()
    app.processEvents()
    window.grab().save(os.path.join(screenshot_dir, "linker_error_repro_ast.png"))

    print("Testing Call Graph Page...")
    window.switch_to_call_graph()
    app.processEvents()
    window.grab().save(os.path.join(screenshot_dir, "linker_error_repro_callgraph.png"))

    print("Testing CFG Page...")
    window.switch_to_cfg()
    app.processEvents()
    window.grab().save(os.path.join(screenshot_dir, "linker_error_repro_cfg.png"))

    print("Testing Review Page...")
    window.switch_to_review()
    app.processEvents()
    window.grab().save(os.path.join(screenshot_dir, "linker_error_repro_review.png"))

    # Switch back to editor
    window.stack.setCurrentIndex(0)
    app.processEvents()

    assert not window.is_loading, "Analysis did not complete in time"
    assert window.errors_count == 1, f"Expected 1 error, got {window.errors_count}"
    assert "undefined reference to 'computeArea(int, int)'" in terminal_text, "Error message missing in terminal"
    assert "linker error" in terminal_text.lower(), "Linker error tag missing in terminal"
    print("\nSUCCESS: All assertions passed, no crash occurred, all panels safe!")

if __name__ == "__main__":
    main()
