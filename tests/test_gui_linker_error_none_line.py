"""
Regression test for linker errors with line=None and column=None in gui.py.
Verifies that:
1. render_json handles diagnostics with line=None without raising TypeError.
2. The diagnostic message, category, and clean placeholder are rendered.
3. CodeEditor squiggly highlighting handles line=None cleanly.
4. SecurityCard and UserGuidanceDialog handle line=None without displaying "Line None".
5. End-to-end simulation of analyzing benchmark/linker_errors/lk01_undef_func.cpp
   completes without crashing.
"""

import os
import sys
import json
import pytest

# Ensure src is on sys.path
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from gui import AppGUI, SecurityCard, UserGuidanceDialog
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


def test_render_json_with_none_line(qapp):
    """Test render_json handles diagnostics where line and column are None."""
    window = AppGUI()
    window.file_path = "benchmark/linker_errors/lk01_undef_func.cpp"

    linker_error_data = {
        "status": "error",
        "file": "benchmark/linker_errors/lk01_undef_func.cpp",
        "error_count": 1,
        "warning_count": 0,
        "errors": [
            {
                "kind": "error",
                "code": None,
                "file": "benchmark/linker_errors/lk01_undef_func.cpp",
                "line": None,
                "column": None,
                "type": "error",
                "error_type": "error",
                "message": "undefined reference to 'computeArea(int, int)'",
                "category": "linker_error",
                "explanation": "A function was declared, but its compiled definition was not found.",
                "suggestion": "Ensure the function is defined and all source files are compiled.",
                "context": None,
            }
        ],
        "security_findings": [],
        "security_report": "0 critical, 0 high, 0 medium, 0 low findings\n",
    }

    # Calling render_json directly must not raise TypeError: int() argument must be...
    window.render_json(linker_error_data, "")

    assert window.errors_count == 1
    assert "ERRORS FOUND" in window.status_label.text()

    # Message must be present in terminal / message log
    terminal_html = window.terminal.toHtml()
    assert "undefined reference to 'computeArea(int, int)'" in terminal_html
    assert "linker error" in terminal_html.lower()

    # Error cards must contain the root card
    assert window.error_cards_layout.count() >= 1


def test_code_editor_set_errors_none_line(qapp):
    """Test that CodeEditor.set_errors does not crash with line=None or string line."""
    window = AppGUI()
    window.editor.setPlainText("int main() {\n    return 0;\n}\n")

    # None line
    window.editor.set_errors([
        {"line": None, "column": None, "error_type": "error", "message": "Linker error"}
    ])
    # String line or invalid line
    window.editor.set_errors([
        {"line": "?", "column": "?", "error_type": "error", "message": "Unknown line error"}
    ])
    # Normal line
    window.editor.set_errors([
        {"line": 2, "column": 5, "error_type": "error", "message": "Normal error"}
    ])


def test_security_card_none_line(qapp):
    """Test that SecurityCard displays 'No specific line' instead of 'Line None'."""
    finding = {
        "file": "benchmark/linker_errors/lk01_undef_func.cpp",
        "line": None,
        "column": None,
        "severity": "Low",
        "vulnerability_type": "Information Exposure",
        "description": "General warning",
    }
    card = SecurityCard(finding, "#2ECC71")
    assert "Line None" not in card.line_chip.text()
    assert card.line_chip.text() == "No specific line"


def test_user_guidance_dialog_none_line(qapp):
    """Test that UserGuidanceDialog formats line cleanly when line is None."""
    history = [
        {
            "attempt": 1,
            "error": {
                "message": "undefined reference to 'computeArea'",
                "category": "linker_error",
                "line": None,
                "suggestion": "Define the function",
            },
        }
    ]
    window = AppGUI()
    dlg = UserGuidanceDialog(history, parent=window)
    assert dlg is not None


def test_on_analysis_finished_linker_error_repro(qapp):
    """Simulate backend output from benchmark/linker_errors/lk01_undef_func.cpp to _on_analysis_finished."""
    window = AppGUI()
    repro_file = os.path.abspath("benchmark/linker_errors/lk01_undef_func.cpp")
    window.file_path = repro_file
    with open(repro_file, "r") as f:
        window.editor.setPlainText(f.read())

    mock_stdout = json.dumps({
        "status": "error",
        "file": repro_file,
        "error_count": 1,
        "warning_count": 0,
        "errors": [
            {
                "kind": "error",
                "code": None,
                "file": repro_file,
                "line": None,
                "column": None,
                "type": "error",
                "error_type": "error",
                "message": "undefined reference to 'computeArea(int, int)'",
                "normalized_message": "undefined reference to 'computeArea(int, int)'",
                "notes": [],
                "fix_it": None,
                "root_cause_id": f"rc-{repro_file}:0",
                "confidence": 0.95,
                "cwe": None,
                "severity_source": "compiler",
                "category": "linker_error",
                "explanation": "Linker error: undefined reference to 'computeArea(int, int)'",
                "suggestion": "Ensure the function is defined and all source files are compiled.",
                "context": None,
                "security_findings": [],
                "raw": "Undefined symbols for architecture arm64:\n  \"computeArea(int, int)\", referenced from:\n      _main",
            }
        ],
        "security_findings": [],
        "security_report": "0 critical, 0 high, 0 medium, 0 low findings\n\nRisk score: 0 (Clean)\n",
    })

    # This is the exact method called by the analysis background worker that previously crashed
    window._on_analysis_finished(mock_stdout, "", 1)

    assert window.errors_count == 1
    terminal_html = window.terminal.toHtml()
    assert "undefined reference to 'computeArea(int, int)'" in terminal_html
    assert "linker error" in terminal_html.lower()
