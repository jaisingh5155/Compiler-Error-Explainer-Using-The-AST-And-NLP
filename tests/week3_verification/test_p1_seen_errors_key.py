#!/usr/bin/env python3
"""
Regression Test: P1 - seen_errors key tracking in heal_loop.
Ensures that the convergence check in heal_loop tracks (message, line) tuples
instead of purely message strings, preventing premature aborts on separate lines
sharing the same compiler error message.
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

def test_seen_errors_key_tracking():
    # Simulate errors across iterations
    err_line_10 = {"message": "expected ';' after expression", "line": 10}
    err_line_20 = {"message": "expected ';' after expression", "line": 20}
    err_line_10_repeat = {"message": "expected ';' after expression", "line": 10}

    # Old logic (buggy): error_key was only the message string
    seen_errors_old = set()
    old_key_1 = err_line_10.get("message")
    seen_errors_old.add(old_key_1)

    old_key_2 = err_line_20.get("message")
    # In old logic, line 20 falsely collided with line 10
    assert old_key_2 in seen_errors_old, "Expected old logic to falsely collide"

    # New logic (fixed): error_key is (message, line)
    seen_errors_new = set()
    new_key_1 = (err_line_10.get("message"), err_line_10.get("line"))
    seen_errors_new.add(new_key_1)

    new_key_2 = (err_line_20.get("message"), err_line_20.get("line"))
    # New logic correctly recognizes line 20 as a distinct error
    assert new_key_2 not in seen_errors_new, "New logic must not abort on different line with same message!"
    seen_errors_new.add(new_key_2)

    # Identical error on same line DOES trigger convergence abort
    new_key_repeat = (err_line_10_repeat.get("message"), err_line_10_repeat.get("line"))
    assert new_key_repeat in seen_errors_new, "New logic must correctly detect duplicate error on same line!"

    # Also inspect actual heal_loop.py code to ensure the fix is in place
    heal_loop_path = os.path.join(project_root, "src", "heal_loop.py")
    with open(heal_loop_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert 'error_key = (target.get("message"), target.get("line"))' in content, \
        "heal_loop.py does not contain the tuple key tracking fix!"

    print("[P1 seen_errors Key Test] heal_loop correctly uses (message, line) tuples for convergence.")
    print("✓ P1 seen_errors Key Tracking Regression Test PASSED.")

if __name__ == "__main__":
    test_seen_errors_key_tracking()
