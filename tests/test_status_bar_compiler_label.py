import os
import sys
import subprocess
import pytest
from unittest.mock import patch, MagicMock

# Ensure repo root and src/ are in sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import gui
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_compiler_version_mocked_success():
    """With version command mocked to return a known string, returns that parsed string."""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "Apple clang version 21.0.0 (clang-2100.3.34.2)\nTarget: arm64-apple-darwin27.0.0"

    with patch("subprocess.run", return_value=mock_res):
        label = gui.get_status_bar_compiler_label("test_cmd", force_refresh=True)
        assert label == "Apple clang 21.0.0"

    # Test GCC format
    mock_res.stdout = "gcc (GCC) 16.2.0\nCopyright (C) 2026 Free Software Foundation, Inc."
    with patch("subprocess.run", return_value=mock_res):
        label = gui.get_status_bar_compiler_label("test_cmd", force_refresh=True)
        assert label == "GCC 16.2.0"

    # Test Clang format
    mock_res.stdout = "clang version 18.1.0 (https://github.com/llvm/llvm-project.git ...)"
    with patch("subprocess.run", return_value=mock_res):
        label = gui.get_status_bar_compiler_label("test_cmd", force_refresh=True)
        assert label == "clang 18.1.0"


def test_compiler_version_mocked_failure_fallback_unknown():
    """With the version command failing or timing out, returns 'unknown'."""
    # Failure via non-zero returncode
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stdout = ""
    with patch("subprocess.run", return_value=mock_res):
        label = gui.get_status_bar_compiler_label("failing_cmd", force_refresh=True)
        assert label == "unknown"

    # Failure via TimeoutExpired
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=2.0)):
        label = gui.get_status_bar_compiler_label("timeout_cmd", force_refresh=True)
        assert label == "unknown"

    # Failure via FileNotFoundError / command not found
    with patch("subprocess.run", side_effect=FileNotFoundError("compiler not found")):
        label = gui.get_status_bar_compiler_label("missing_cmd", force_refresh=True)
        assert label == "unknown"


def test_language_standard_resolution():
    """Language standard correctly reads config and falls back to 'default' if absent."""
    with patch("config_loader.get", return_value=None):
        assert gui._resolve_language_standard() == "default"

    with patch("config_loader.get", side_effect=lambda sec, key, default=None: "c++17" if key == "standard" else default):
        assert gui._resolve_language_standard() == "C++17"

    with patch("config_loader.get", side_effect=lambda sec, key, default=None: "-std=c++20" if key == "standard" else default):
        assert gui._resolve_language_standard() == "C++20"


def test_status_bar_footer_lifecycle(qapp, monkeypatch):
    """Verify status bar shows real compiler label, '-' before compile, real counts on compile, and resets on edit/load."""
    monkeypatch.delenv("CXX_OVERRIDE", raising=False)
    win = gui.AppGUI()
    status_text = win.status_bar_left.text()

    # Must NOT have hardcoded GCC 11.4
    assert "Compiler: GCC 11.4" not in status_text
    # Must show detected real compiler (e.g. Apple clang 21.0.0)
    assert f"Compiler: {win.compiler_version}" in status_text
    # Before any compile has run, errors and warnings must be '-'
    assert "Errors: - | Warnings: -" in status_text

    # Simulate compile finished with 3 errors and 1 warning
    win.render_json({"status": "error", "error_count": 3, "warning_count": 1, "errors": []}, "")
    updated_text = win.status_bar_left.text()
    assert "Errors: 3 | Warnings: 1" in updated_text

    # Modify code in editor -> resets errors/warnings to '-'
    win.on_code_changed()
    after_edit_text = win.status_bar_left.text()
    assert "Errors: - | Warnings: -" in after_edit_text

    # Change compiler dynamically -> updates compiler label
    orig_env = os.environ.get("CXX_OVERRIDE")
    try:
        win.set_compiler("nonexistent_compiler_binary_xyz")
        unknown_text = win.status_bar_left.text()
        assert "Compiler: unknown" in unknown_text
    finally:
        if orig_env is not None:
            os.environ["CXX_OVERRIDE"] = orig_env
        else:
            os.environ.pop("CXX_OVERRIDE", None)

