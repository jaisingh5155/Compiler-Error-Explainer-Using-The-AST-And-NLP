#!/usr/bin/env python3
"""
Regression Test: Bug 2.1 / 2.2 - Compiler dialect bias in classifier.
Ensures that Clang diagnostic phrasings are normalized to canonical GCC wording
and correctly classified by the model, while genuine GCC messages continue to pass.
"""
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, "src"))

from error_classifier import ErrorClassifier, _normalize_clang_dialect

def test_clang_dialect_normalization():
    clf = ErrorClassifier()

    # Novel Clang message 1: undeclared identifier with custom variable name
    clang_msg1 = "use of undeclared identifier 'velocity_vector_z'"
    norm1 = _normalize_clang_dialect(clang_msg1)
    assert norm1 == "'velocity_vector_z' was not declared in this scope", f"Unexpected normalization: {norm1}"
    cat1, conf1 = clf.predict(clang_msg1)
    print(f"[Bug 2.1 Test] Clang Undeclared: '{clang_msg1}' -> '{norm1}' => {cat1} ({conf1:.3f})")
    assert cat1 == "name_resolution", f"Expected 'name_resolution', got {cat1}"
    assert conf1 > 0.9, f"Expected high confidence, got {conf1}"

    # Novel Clang message 2: initialization mismatch
    clang_msg2 = "cannot initialize a variable of type 'char *' with an rvalue of type 'double'"
    norm2 = _normalize_clang_dialect(clang_msg2)
    assert norm2 == "invalid conversion from 'double' to 'char *'", f"Unexpected normalization: {norm2}"
    cat2, conf2 = clf.predict(clang_msg2)
    print(f"[Bug 2.1 Test] Clang Init Mismatch: '{clang_msg2}' -> '{norm2}' => {cat2} ({conf2:.3f})")
    assert cat2 == "type_error", f"Expected 'type_error', got {cat2}"
    assert conf2 > 0.85, f"Expected high confidence, got {conf2}"

    # Novel Clang message 3: invalid dereference
    clang_msg3 = "indirection requires pointer operand ('float' invalid)"
    norm3 = _normalize_clang_dialect(clang_msg3)
    assert norm3 == "invalid type argument of unary '*' (have 'float')", f"Unexpected normalization: {norm3}"
    cat3, conf3 = clf.predict(clang_msg3)
    print(f"[Bug 2.1 Test] Clang Deref: '{clang_msg3}' -> '{norm3}' => {cat3} ({conf3:.3f})")
    assert cat3 == "type_error", f"Expected 'type_error', got {cat3}"

    # Genuine GCC message: verify no regression
    gcc_msg = "'temperature_sensor' was not declared in this scope"
    norm_gcc = _normalize_clang_dialect(gcc_msg)
    assert norm_gcc == gcc_msg, "GCC message should remain untouched"
    cat_gcc, conf_gcc = clf.predict(gcc_msg)
    print(f"[Bug 2.1 Test] GCC Native: '{gcc_msg}' => {cat_gcc} ({conf_gcc:.3f})")
    assert cat_gcc == "name_resolution", f"Expected 'name_resolution', got {cat_gcc}"
    assert conf_gcc > 0.9, f"Expected high confidence, got {conf_gcc}"

    print("✓ Bug 2.1 & 2.2 Regression Test PASSED.")

if __name__ == "__main__":
    test_clang_dialect_normalization()
