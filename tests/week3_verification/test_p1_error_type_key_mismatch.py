#!/usr/bin/env python3
"""
Regression Test: P1 - Error Dict Key Mismatch ('error_type' vs 'type').
Ensures that CompilerError.to_dict() provides both 'type' and 'error_type' keys,
and that GUI / logging consumers can safely read the error type from either key.
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

from models import CompilerError

def test_compiler_error_dict_keys():
    err = CompilerError(
        file="example.cpp",
        line=15,
        column=4,
        error_type="error",
        message="use of undeclared identifier 'foo'",
        raw="example.cpp:15:4: error: use of undeclared identifier 'foo'"
    )
    d = err.to_dict()

    # 1. Verify both keys are present in dictionary output
    assert "type" in d, "Expected 'type' key in CompilerError.to_dict()"
    assert "error_type" in d, "Expected 'error_type' key in CompilerError.to_dict()"
    assert d["type"] == "error", f"Expected d['type'] == 'error', got {d['type']}"
    assert d["error_type"] == "error", f"Expected d['error_type'] == 'error', got {d['error_type']}"

    # 2. Reproduction of previous bug:
    # Older code relied on d['error_type'] only or d['type'] only.
    # Now simulate GUI consumer pattern:
    gui_extracted_type = (d.get('error_type') or d.get('type') or 'error').upper()
    assert gui_extracted_type == "ERROR", f"Failed to extract error type in GUI pattern: {gui_extracted_type}"

    # Test with legacy dict having ONLY 'type'
    legacy_dict_type_only = {"type": "warning", "message": "unused variable"}
    extracted = (legacy_dict_type_only.get('error_type') or legacy_dict_type_only.get('type') or 'error').upper()
    assert extracted == "WARNING", f"Failed backward-compatible fallback on 'type': {extracted}"

    # Test with legacy dict having ONLY 'error_type'
    legacy_dict_error_type_only = {"error_type": "fatal error", "message": "file not found"}
    extracted = (legacy_dict_error_type_only.get('error_type') or legacy_dict_error_type_only.get('type') or 'error').upper()
    assert extracted == "FATAL ERROR", f"Failed backward-compatible fallback on 'error_type': {extracted}"

    print("[P1 Key Mismatch Test] CompilerError.to_dict() provides both 'type' and 'error_type'.")
    print("✓ P1 Error Dict Key Mismatch Regression Test PASSED.")

if __name__ == "__main__":
    test_compiler_error_dict_keys()
