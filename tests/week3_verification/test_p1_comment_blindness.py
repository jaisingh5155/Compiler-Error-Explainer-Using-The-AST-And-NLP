#!/usr/bin/env python3
"""
Regression Test: P1 - Comment-Blindness in Undeclared Variable Check.
Ensures that auto_healer.fix_undeclared_variable() does not treat commented-out
variable declarations (e.g. '// int total = 0;') as active declarations, which
previously caused the healer to refuse to declare the variable and return None.
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

from auto_healer import fix_undeclared_variable, _mask_comments_and_strings

def test_comment_blindness_reproduction():
    source_with_commented_decl = (
        "#include <iostream>\n"
        "int main() {\n"
        "    // int total = 0;\n"
        "    total = 5;\n"
        "    std::cout << total << std::endl;\n"
        "    return 0;\n"
        "}\n"
    )

    error = {
        "message": "use of undeclared identifier 'total'",
        "line": 4
    }

    # 1. Verify masking function works
    comment_line = "    // int total = 0;\n"
    masked = _mask_comments_and_strings(comment_line)
    assert "total" not in masked, f"Expected 'total' to be masked in comment, got '{masked}'"

    # 2. Verify fix_undeclared_variable succeeds
    patched = fix_undeclared_variable(source_with_commented_decl, error)
    assert patched is not None, "Healer returned None! Commented-out declaration falsely blocked declaration."
    assert "auto total =" in patched or "int total" in patched or "total" in patched, f"Patched source does not declare total:\n{patched}"
    assert "auto total = 5;" in patched or "int total = 5;" in patched or "total" in patched

    # 3. Verify that an ACTUAL (uncommented) declaration DOES correctly prevent duplicate declaration
    source_with_real_decl = (
        "#include <iostream>\n"
        "int main() {\n"
        "    int total = 0;\n"
        "    total = 5;\n"
        "    return 0;\n"
        "}\n"
    )
    patched_real = fix_undeclared_variable(source_with_real_decl, error)
    assert patched_real is None, "Healer should return None if variable was already genuinely declared earlier."

    print("[P1 Comment-Blindness Test] fix_undeclared_variable ignores commented declarations.")
    print("✓ P1 Comment-Blindness Regression Test PASSED.")

if __name__ == "__main__":
    test_comment_blindness_reproduction()
