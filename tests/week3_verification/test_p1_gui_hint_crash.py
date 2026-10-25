#!/usr/bin/env python3
"""
Regression Test: P1 - GUI Hint Button NameError crash.
Ensures that selecting 'Give Hint & Retry' in the user guidance dialog
properly initializes the classifier and launches the HealWorker without NameError.
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

# Set offscreen Qt platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"
try:
    import PyQt6
    qt_plugins = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins")
    if os.path.exists(qt_plugins):
        os.environ["QT_PLUGIN_PATH"] = qt_plugins
except Exception:
    pass

def test_gui_hint_retry_no_crash():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from gui import AppGUI, UserGuidanceDialog
    from heal_loop import HealWorker

    window = AppGUI()
    window.file_path = "test_dummy.cpp"
    window.error_classifier = None  # Ensure fallback keyword classifier path is exercised

    fake_history = [
        {"attempt": 1, "error": {"line": 10, "message": "expected ';'"}, "patch": None}
    ]

    # Mock UserGuidanceDialog so exec() returns GIVE_HINT with hint_text "add semicolon"
    with patch.object(UserGuidanceDialog, "exec", return_value=UserGuidanceDialog.GIVE_HINT), \
         patch.object(UserGuidanceDialog, "hint_text", return_value="add semicolon to line 10"):

        # Mock HealWorker.start so a background thread isn't actually spawned
        with patch.object(HealWorker, "start") as mock_start:
            # Trigger the handler that previously crashed with: NameError: name 'classifier' is not defined
            try:
                window._on_heal_give_up(fake_history)
            except NameError as ex:
                assert False, f"Regression detected: NameError raised during hint retry: {ex}"
            except Exception as ex:
                assert False, f"Unexpected exception raised: {ex}"

            assert hasattr(window, "heal_worker"), "window.heal_worker was not created"
            assert window.heal_worker is not None, "window.heal_worker is None"
            assert mock_start.called, "heal_worker.start() was not called"
            print("[P1 GUI Hint Test] window.heal_worker successfully created and started with hint without NameError.")
            print("✓ P1 GUI Hint Button Crash Regression Test PASSED.")

if __name__ == "__main__":
    test_gui_hint_retry_no_crash()
