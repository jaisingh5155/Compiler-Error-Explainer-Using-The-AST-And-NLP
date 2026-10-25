"""
tests/week6_verification/test_week6.py
──────────────────────────────────────
Verification suite for Week 6 requirements:
1. Dataset deduplication, structural template partitioning, and split correctness.
2. AST feature extraction and coarse symbol-table signal extraction.
3. Model comparison harness runs and records Macro-F1 across all 3 candidates.
4. GCC vs Clang held-out dialect generalization gap is evaluated and bounded.
5. Explanation engine produces dynamic content with actual identifiers, AST context,
   and symbol-table 'did you mean' suggestions in both Beginner and Detailed modes.
6. Feedback storage foundation (src/feedback_store.py) writes and reads back records.
"""

import os
import sys
import json
import tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
BENCHMARK_DIR = os.path.join(PROJECT_ROOT, "benchmark")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from error_classifier import ErrorClassifier
from error_explainer import explain_error, extract_entities, format_ast_context
from diagnostic import Diagnostic
from feedback_store import record_feedback, load_feedback


# ── Test 1: Dataset Dedup, Split Correctness, and Zero Leakage ────────────────

def test_dataset_dedup_and_split():
    dataset_path = os.path.join(DATA_DIR, "training_data_v2.json")
    assert os.path.exists(dataset_path), f"Missing {dataset_path}"

    with open(dataset_path, "r") as f:
        data = json.load(f)

    assert len(data) > 0, "Dataset is empty"

    # Check for exact duplicate pairs
    seen = set()
    duplicates = []
    for r in data:
        key = (r["message"].strip().lower(), r["category"].strip().lower())
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    assert len(duplicates) == 0, f"Found {len(duplicates)} duplicate rows in training_data_v2.json"

    # Check split partitioning
    splits = set(r.get("split") for r in data)
    assert splits == {"train", "validation", "test"}, f"Unexpected splits: {splits}"

    train_templates = {r["template_id"] for r in data if r["split"] == "train"}
    val_templates = {r["template_id"] for r in data if r["split"] == "validation"}
    test_templates = {r["template_id"] for r in data if r["split"] == "test"}

    # Verify strict disjointness across structural template IDs
    assert len(train_templates & val_templates) == 0, "Template leakage between train and validation"
    assert len(train_templates & test_templates) == 0, "Template leakage between train and test"
    assert len(val_templates & test_templates) == 0, "Template leakage between validation and test"

    # Verify zero leakage with benchmark files
    bench_messages = set()
    for root, _, files in os.walk(BENCHMARK_DIR):
        for f in files:
            if f.endswith(".json"):
                with open(os.path.join(root, f), "r") as jf:
                    meta = json.load(jf)
                    if "diagnostic_message" in meta:
                        bench_messages.add(meta["diagnostic_message"].strip().lower())

    dataset_messages = {r["message"].strip().lower() for r in data}
    overlap = dataset_messages & bench_messages
    assert len(overlap) == 0, f"Data leakage detected! Overlapping messages: {overlap}"


# ── Test 2: AST Feature Extraction and Symbol Signal ──────────────────────────

def test_ast_feature_extraction():
    dataset_path = os.path.join(DATA_DIR, "training_data_v2.json")
    with open(dataset_path, "r") as f:
        data = json.load(f)

    clang_rows = [r for r in data if r.get("provenance") == "clang_compiled"]
    assert len(clang_rows) > 0, "No clang_compiled rows found in training set"

    # Check that real AST node types were assigned
    ast_nodes = {r.get("ast_node") for r in clang_rows}
    assert any(n in ast_nodes for n in ("VarDecl", "BinaryOperator", "DeclRefExpr", "RecoveryExpr", "MemberExpr")), \
        f"Missing expected AST node types in compiled rows: {ast_nodes}"

    # Check ast_fallback is boolean False for parsed clang rows
    fallbacks = {r.get("ast_fallback") for r in clang_rows}
    assert False in fallbacks, "Expected ast_fallback to be False for successful AST extractions"

    # Check symbol signals exist
    sym_signals = {r.get("symbol_signal") for r in data}
    assert "typo_near_miss" in sym_signals or "completely_undeclared" in sym_signals


# ── Test 3: Model Comparison Harness & scikit-learn Version Pinning ───────────

def test_model_comparison_metadata():
    metadata_path = os.path.join(DATA_DIR, "error_classifier_v2_metadata.json")
    assert os.path.exists(metadata_path), f"Missing metadata file: {metadata_path}"

    with open(metadata_path, "r") as f:
        meta = json.load(f)

    # Check pinned version
    import sklearn
    assert "scikit_learn_version" in meta
    assert meta["scikit_learn_version"] == sklearn.__version__

    # Check candidates evaluated
    candidates = meta.get("candidate_comparison", {})
    assert "Logistic Regression" in candidates
    assert any("SVM" in k for k in candidates)
    assert any("Bayes" in k for k in candidates)

    for cand_name, metrics in candidates.items():
        assert "val_macro_f1" in metrics
        assert "test_macro_f1" in metrics
        assert 0.0 <= metrics["test_macro_f1"] <= 1.0

    # Winning model selected
    assert meta.get("selected_architecture") is not None
    assert meta.get("winning_test_metrics", {}).get("macro_f1", 0) >= 0.90


# ── Test 4: GCC vs Clang Dialect Generalization Gap ───────────────────────────

def test_gcc_vs_clang_generalization_gap():
    metadata_path = os.path.join(DATA_DIR, "error_classifier_v2_metadata.json")
    with open(metadata_path, "r") as f:
        meta = json.load(f)

    metrics = meta.get("winning_test_metrics", {})
    assert "gcc_macro_f1" in metrics
    assert "clang_macro_f1" in metrics

    gcc_f1 = metrics["gcc_macro_f1"]
    clang_f1 = metrics["clang_macro_f1"]
    gap = abs(gcc_f1 - clang_f1)

    # Macro-F1 gap between dialects must be reasonably small (< 0.10)
    assert gap < 0.10, f"Excessive dialect gap: GCC F1={gcc_f1:.4f}, Clang F1={clang_f1:.4f}, Gap={gap:.4f}"
    assert metrics["clang_accuracy"] >= 0.90, f"Clang accuracy too low: {metrics['clang_accuracy']:.4f}"


# ── Test 5: Dynamic Explanations and Verbosity Toggle ─────────────────────────

def test_explanation_engine_dynamic_and_verbosity():
    # Category 1: name_resolution with Levenshtein did_you_mean
    diag1 = Diagnostic(
        kind="error",
        message="use of undeclared identifier 'maxLmit'",
        file="src/test.cpp",
        line=42,
        column=15,
        ast_node_type="DeclRefExpr",
        did_you_mean="maxLimit",
    )
    res_beg = explain_error(diag1, mode="beginner")
    res_det = explain_error(diag1, mode="detailed")

    # Beginner checks
    assert "What happened:" in res_beg["explanation"]
    assert "Why it happened:" in res_beg["explanation"]
    assert "How to fix it:" in res_beg["explanation"]
    assert "maxLmit" in res_beg["explanation"]
    assert "maxLimit" in res_beg["explanation"]
    assert "Did you mean `maxLimit`" in res_beg["explanation"] or "maxLimit" in res_beg["explanation"]
    assert "DeclRefExpr" not in res_beg["explanation"], "Beginner explanation should not expose raw AST node type"

    # Detailed checks
    assert "--- Detailed Diagnostic Context ---" in res_det["explanation"]
    assert "DeclRefExpr" in res_det["explanation"]
    assert "src/test.cpp:line 42, col 15" in res_det["explanation"]
    assert "Category: name_resolution" in res_det["explanation"]

    # Category 2: type_error with entity and AST context
    diag2 = Diagnostic(
        kind="error",
        message="cannot initialize a variable of type 'char *' with an lvalue of type 'double'",
        file="src/app.cpp",
        line=10,
        column=5,
        ast_node_type="VarDecl",
    )
    res2_beg = explain_error(diag2, mode="beginner")
    res2_det = explain_error(diag2, mode="detailed")

    assert "char *" in res2_beg["explanation"]
    assert "double" in res2_beg["explanation"]
    assert "declaring" in res2_beg["explanation"].lower() or "variable" in res2_beg["explanation"].lower()
    assert "VarDecl" in res2_det["explanation"]

    # Category 3: missing_include with header name
    diag3 = Diagnostic(
        kind="error",
        message="'vector' file not found",
        file="src/main.cpp",
        line=1,
        column=10,
    )
    res3 = explain_error(diag3, mode="beginner")
    assert "<vector>" in res3["explanation"]
    assert "#include <vector>" in res3["explanation"] or "<vector>" in res3["suggestion"]


# ── Test 6: Feedback Storage Foundation ───────────────────────────────────────

def test_feedback_store_functionality():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_store = tf.name

    try:
        diag = Diagnostic(
            kind="error",
            message="unknown type name 'custom_uint128_t'",
            file="include/types.hpp",
            line=12,
            category="other",
            confidence=0.45,
            ast_node_type="VarDecl",
        )

        record = record_feedback(
            diagnostic=diag,
            confirmed_category="name_resolution",
            user_notes="Missing typedef header",
            feedback_file=temp_store,
        )

        assert record["confirmed_category"] == "name_resolution"
        assert record["user_notes"] == "Missing typedef header"
        assert record["reviewed_for_merge"] is False

        loaded = load_feedback(temp_store)
        assert len(loaded) == 1
        assert loaded[0]["confirmed_category"] == "name_resolution"
        assert loaded[0]["file"] == "include/types.hpp"
        assert loaded[0]["line"] == 12

        # Record a second correction
        record_feedback(
            diagnostic=diag,
            confirmed_category="missing_include",
            user_notes="Second note",
            feedback_file=temp_store,
        )
        loaded2 = load_feedback(temp_store)
        assert len(loaded2) == 2
        assert loaded2[1]["confirmed_category"] == "missing_include"
    finally:
        if os.path.exists(temp_store):
            os.remove(temp_store)
