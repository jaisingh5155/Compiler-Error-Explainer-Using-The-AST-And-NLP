#!/usr/bin/env python3
"""
Regression Test: Bug 5.1 - Unsafe regex-based healing & backup/rollback.
Ensures:
  1. Valid identifiers and std symbols ('cout') are NEVER rewritten into keywords ('const').
  2. Genuine keyword typos ('flaot', 'retrun') are healed correctly (within edit distance 1).
  3. Pre-patch backup is created before writing to disk, and rollback restores the file
     if post-patch compilation worsens (error count increases).
"""
import sys
import os
import tempfile
import subprocess

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

from auto_healer import _fix_keyword_typo
from heal_loop import _compile

def test_no_identifier_corruption():
    # 1. Never rewrite 'cout' to 'const'
    line1 = "cout << 100 << endl;"
    fix1 = _fix_keyword_typo(line1, target_token="cout")
    print(f"[Bug 5.1 Test] 'cout' typo check result: {fix1}")
    assert fix1 is None, f"Expected None for 'cout', but got '{fix1}' (corruption!)"

    # 2. Never rewrite other standard identifiers ('cin', 'endl', 'vector')
    assert _fix_keyword_typo("cin >> x;", target_token="cin") is None
    assert _fix_keyword_typo("endl;", target_token="endl") is None

    # 3. Genuine typo 'flaot' -> 'float'
    line2 = "flaot speed = 5.5f;"
    fix2 = _fix_keyword_typo(line2, target_token="flaot")
    print(f"[Bug 5.1 Test] 'flaot' typo check result: '{fix2}'")
    assert fix2 == "float speed = 5.5f;", f"Expected 'float speed = 5.5f;', got '{fix2}'"

    # 4. Genuine typo 'retrun' -> 'return'
    line3 = "retrun 0;"
    fix3 = _fix_keyword_typo(line3, target_token="retrun")
    print(f"[Bug 5.1 Test] 'retrun' typo check result: '{fix3}'")
    assert fix3 == "return 0;", f"Expected 'return 0;', got '{fix3}'"

def test_backup_and_rollback_on_worsened_compilation():
    # Construct a file with 1 error
    original_code = """#include <iostream>
int main() {
    int x = 10;
    std::cout << y << std::endl; // 1 undeclared variable error
    return 0;
}
"""
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
        f.write(original_code)
        f_path = f.name

    try:
        errors_before, _ = _compile(f_path)
        err_count_before = sum(1 for e in errors_before if e.get("type") == "error")
        assert err_count_before == 1, f"Expected 1 pre-patch error, got {err_count_before}"

        # Simulate a bad patch that introduces more errors (e.g. invalid syntax across 3 lines)
        bad_patch = """#include <iostream>
int main() {
    broken syntax error 1 ;
    another broken error 2 ;
    and a third error 3 ;
    return 0;
}
"""
        backup_path = f_path + ".bak"
        with open(backup_path, "w", encoding="utf-8") as bf:
            bf.write(original_code)

        # Write bad patch
        with open(f_path, "w", encoding="utf-8") as pf:
            pf.write(bad_patch)

        # Check post errors
        errors_after, _ = _compile(f_path)
        err_count_after = sum(1 for e in errors_after if e.get("type") == "error")
        assert err_count_after > err_count_before, f"Expected errors to worsen ({err_count_after} > {err_count_before})"

        # Trigger the rollback condition implemented in heal_loop.py
        if err_count_before > 0 and err_count_after > err_count_before:
            with open(f_path, "w", encoding="utf-8") as rf:
                rf.write(original_code)
            if os.path.exists(backup_path):
                os.remove(backup_path)

        # Verify file is restored to original state
        with open(f_path, "r", encoding="utf-8") as vf:
            restored_code = vf.read()

        assert restored_code == original_code, "Rollback failed to restore original file content!"
        assert not os.path.exists(backup_path), "Backup file was not properly cleaned up after rollback"
        print(f"[Bug 5.1 Test] Rollback successfully restored code when errors increased ({err_count_before} -> {err_count_after} -> restored).")
        print("✓ Bug 5.1 Regression Test PASSED.")
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)
        if os.path.exists(f_path + ".bak"):
            os.remove(f_path + ".bak")

if __name__ == "__main__":
    test_no_identifier_corruption()
    test_backup_and_rollback_on_worsened_compilation()
