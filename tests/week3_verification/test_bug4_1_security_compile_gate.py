#!/usr/bin/env python3
"""
Regression Test: Bug 4.1 - Security scanner gated by compile errors.
Ensures that files failing to compile due to syntax or type errors still undergo
full source-level security scanning and report discovered vulnerabilities.
"""
import sys
import os
import json
import tempfile
import subprocess

def test_security_scanner_ungated():
    source_code = """
#include <cstdio>

int main() {
    int syntax_error_line = ; // Obvious syntax/compile error
    char buffer[32];
    gets(buffer);             // Dangerous function (CWE-120 Buffer Overflow)
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
        sec_findings = data.get("security_findings", [])
        
        print(f"[Bug 4.1 Test] status={status}, error_count={len(errors)}, security_findings={len(sec_findings)}")
        for sf in sec_findings:
            print(f"  Finding: {sf.get('vulnerability_type')} at line {sf.get('line')}")
            
        assert status == "error", f"Expected compilation failure ('error'), got '{status}'"
        assert len(errors) > 0, "Expected compilation errors to be present"
        assert len(sec_findings) > 0, "Expected security findings even when compilation fails"
        
        vuln_types = [sf.get("vulnerability_type") for sf in sec_findings]
        assert any("Buffer Overflow" in vt or "gets" in str(sf).lower() for vt, sf in zip(vuln_types, sec_findings)), \
            f"Expected Buffer Overflow / gets finding, got {vuln_types}"
            
        print("✓ Bug 4.1 Regression Test PASSED.")
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)

if __name__ == "__main__":
    test_security_scanner_ungated()
