"""
Regression test for Run Code execution freshness in gui.py.
Verifies that:
1. Run Code compiles and executes the live editor content, never a stale binary.
2. Replacing editor content immediately reflects the new code on the next run.
3. Empty editor content is caught cleanly with a user-friendly message.
4. Compilation errors prevent stale binary execution.
"""

import os
import sys
import pytest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QProcess
    from gui import AppGUI
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False


@pytest.fixture(scope="module")
def qapp():
    if not PYQT_AVAILABLE:
        pytest.skip("PyQt6 not available in this environment")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_run_code_fresh_content_sequence(qapp):
    """Test consecutive runs of distinct code in the editor without reloading files."""
    window = AppGUI()

    # Run 1: Program A
    window.editor.setPlainText(
        '#include <iostream>\nint main() { std::cout << "TEST_OUTPUT_AAA" << std::endl; return 0; }\n'
    )
    window.run_code()
    if hasattr(window, "process"):
        window.process.waitForFinished(10000)
    qapp.processEvents()

    out_a = window.terminal.toPlainText()
    assert "TEST_OUTPUT_AAA" in out_a
    assert "Calculation started" not in out_a

    # Run 2: Program B (replace text in editor directly)
    window.editor.setPlainText(
        '#include <iostream>\nint main() { std::cout << "TEST_OUTPUT_BBB" << std::endl; return 0; }\n'
    )
    window.run_code()
    if hasattr(window, "process"):
        window.process.waitForFinished(10000)
    qapp.processEvents()

    out_b = window.terminal.toPlainText()
    assert "TEST_OUTPUT_BBB" in out_b
    assert "TEST_OUTPUT_AAA" not in out_b
    assert "Calculation started" not in out_b

    # Run 3: Program C
    window.editor.setPlainText(
        '#include <iostream>\nint main() { std::cout << "TEST_OUTPUT_CCC" << std::endl; return 0; }\n'
    )
    window.run_code()
    if hasattr(window, "process"):
        window.process.waitForFinished(10000)
    qapp.processEvents()

    out_c = window.terminal.toPlainText()
    assert "TEST_OUTPUT_CCC" in out_c
    assert "TEST_OUTPUT_AAA" not in out_c
    assert "TEST_OUTPUT_BBB" not in out_c


def test_run_code_compilation_failure_blocks_stale_run(qapp):
    """Test that if compilation fails, no stale binary is executed."""
    window = AppGUI()

    # First compile and run a valid program
    window.editor.setPlainText(
        '#include <iostream>\nint main() { std::cout << "VALID_ONE" << std::endl; return 0; }\n'
    )
    window.run_code()
    if hasattr(window, "process"):
        window.process.waitForFinished(10000)
    qapp.processEvents()
    assert "VALID_ONE" in window.terminal.toPlainText()

    # Now introduce a syntax error
    window.editor.setPlainText(
        '#include <iostream>\nint main() { invalidSyntaxHere(); return 0; }\n'
    )
    window.run_code()
    qapp.processEvents()

    out_err = window.terminal.toPlainText()
    assert "Compilation failed" in out_err or "error:" in out_err
    assert "VALID_ONE" not in out_err


def test_run_code_empty_editor(qapp):
    """Test that running with an empty editor produces an informative message."""
    window = AppGUI()
    window.editor.setPlainText("   \n\t\n  ")
    window.run_code()
    qapp.processEvents()
    assert "Editor is empty" in window.terminal.toPlainText()
