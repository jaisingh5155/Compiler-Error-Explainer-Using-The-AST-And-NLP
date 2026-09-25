#!/usr/bin/env python3
"""
Regression Test: Bug 1.1 - Status inversion on warning-only compiles.
Ensures that files producing compiler warnings but zero compilation errors
are reported with status 'success' rather than 'error'.
"""
import sys
import os
import json
import tempfile
import subprocess

def test_warning_only_status():
    source_code = """
void print_int(int x);
int main() {
    print_int(3.14159);
    return 0;
}
void print_int(int x) {}
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
        assert proc.returncode == 0, f"Expected process exit 0, got {proc.returncode}"
        data = json.loads(proc.stdout)
        
        status = data.get("status")
        err_count = data.get("error_count")
        warn_count = data.get("warning_count")
        
        print(f"[Bug 1.1 Test] status={status}, error_count={err_count}, warning_count={warn_count}")
        assert status == "success", f"Expected status 'success', got '{status}'"
        assert err_count == 0, f"Expected 0 errors, got {err_count}"
        assert warn_count > 0, f"Expected at least 1 warning, got {warn_count}"
        print("✓ Bug 1.1 Regression Test PASSED.")
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)

if __name__ == "__main__":
    test_warning_only_status()
