import os
import sys
import time

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QProcess
from gui import AppGUI

CODE_A = """#include <iostream>
using namespace std;
int main() {
    cout << "=== OUTPUT FILE A: HELLO FROM FILE A ===" << endl;
    return 0;
}
"""

CODE_B = """#include <iostream>
using namespace std;
int main() {
    cout << "=== OUTPUT FILE B: MATRIX CALCULATION [42] ===" << endl;
    return 0;
}
"""

CODE_C = """#include <iostream>
using namespace std;
int main() {
    cout << "=== OUTPUT FILE C: FINAL VERIFICATION PASSED ===" << endl;
    return 0;
}
"""

def wait_for_process(window, app, timeout=10.0):
    if hasattr(window, 'process'):
        window.process.waitForFinished(int(timeout * 1000))
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()

def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv)

    window = AppGUI()
    window.resize(1300, 850)
    window.show()

    screenshot_dir = os.path.expanduser("~/.gemini/antigravity-ide/brain/455821f3-6953-439e-8cac-451b8f3c8267/screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    print("=== TEST 1: Running File A ===")
    window.editor.setPlainText(CODE_A)
    window.run_code()
    wait_for_process(window, app)

    out_a = window.terminal.toPlainText()
    print(f"File A Output:\n{out_a}")
    assert "=== OUTPUT FILE A: HELLO FROM FILE A ===" in out_a, "File A output mismatch!"
    assert "Calculation started" not in out_a, "Found stale leftover in File A!"
    
    shot_a = os.path.join(screenshot_dir, "run_code_sequence_file_a.png")
    window.grab().save(shot_a)
    print(f"Saved screenshot: {shot_a}")

    print("\n=== TEST 2: Running File B (without reloading file) ===")
    # Replace editor content directly with File B
    window.editor.setPlainText(CODE_B)
    window.run_code()
    wait_for_process(window, app)

    out_b = window.terminal.toPlainText()
    print(f"File B Output:\n{out_b}")
    assert "=== OUTPUT FILE B: MATRIX CALCULATION [42] ===" in out_b, "File B output mismatch!"
    assert "OUTPUT FILE A" not in out_b, "Found stale File A output in File B!"
    assert "Calculation started" not in out_b, "Found stale leftover in File B!"
    
    shot_b = os.path.join(screenshot_dir, "run_code_sequence_file_b.png")
    window.grab().save(shot_b)
    print(f"Saved screenshot: {shot_b}")

    print("\n=== TEST 3: Running File C (without reloading file) ===")
    # Replace editor content directly with File C
    window.editor.setPlainText(CODE_C)
    window.run_code()
    wait_for_process(window, app)

    out_c = window.terminal.toPlainText()
    print(f"File C Output:\n{out_c}")
    assert "=== OUTPUT FILE C: FINAL VERIFICATION PASSED ===" in out_c, "File C output mismatch!"
    assert "OUTPUT FILE A" not in out_c, "Found stale File A output in File C!"
    assert "OUTPUT FILE B" not in out_c, "Found stale File B output in File C!"
    assert "Calculation started" not in out_c, "Found stale leftover in File C!"

    shot_c = os.path.join(screenshot_dir, "run_code_sequence_file_c.png")
    window.grab().save(shot_c)
    print(f"Saved screenshot: {shot_c}")

    print("\n=== TEST 4: Verification of Compile (analyze) ===")
    # Test that Compile also reflects fresh editor content
    code_err = """#include <iostream>
int main() {
    int undeclaredVar = 42
    return 0;
}
"""
    window.editor.setPlainText(code_err)
    window.analyze()
    
    # Wait for compile thread
    start = time.time()
    while window.is_loading and time.time() - start < 10.0:
        app.processEvents()
        time.sleep(0.02)
    
    app.processEvents()
    compile_out = window.terminal.toPlainText()
    print(f"Compile output:\n{compile_out}")
    assert window.errors_count > 0, "Compile should find syntax error!"
    assert "undeclaredVar" in compile_out or "expected ';'" in compile_out or "expected" in compile_out.lower(), "Compile output missing error"
    
    print("\nALL VERIFICATION TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
