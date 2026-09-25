#!/usr/bin/env python3
"""
Regression Test: Bug 1.2 - Linker errors invisible due to missing line:col.
Ensures that files failing at the link stage (undefined references, missing main)
are reported with status 'error' and category 'linker_error', rather than 'success'.
"""
import sys
import os
import json
import tempfile
import subprocess

def test_linker_error_detected():
    source_code = """
void missing_external_service_symbol();

int main() {
    missing_external_service_symbol();
    return 0;
}
"""
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
        f.write(source_code)
        f_path = f.name

    try:
        proc = subprocess.run(
            [sys.executable, "src/main.py", f_path, "-j"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        data = json.loads(proc.stdout)
        
        status = data.get("status")
        errors = data.get("errors", [])
        
        print(f"[Bug 1.2 Test] status={status}, error_count={len(errors)}")
        assert status == "error", f"Expected status 'error', got '{status}'"
        assert len(errors) > 0, "Expected at least 1 parsed error"
        assert errors[0].get("category") == "linker_error", f"Expected category 'linker_error', got {errors[0].get('category')}"
        assert "undefined reference" in errors[0].get("message", "").lower() or "missing_external_service_symbol" in errors[0].get("message", "")
        print("✓ Bug 1.2 Regression Test PASSED.")
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)

if __name__ == "__main__":
    test_linker_error_detected()
