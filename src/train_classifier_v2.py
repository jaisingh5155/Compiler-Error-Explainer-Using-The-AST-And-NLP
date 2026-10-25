"""
src/train_classifier_v2.py
──────────────────────────
Trains candidate models for Week 6 error classification:
1. Logistic Regression (matching baseline architecture)
2. Linear SVM with Platt scaling (CalibratedClassifierCV sigmoid)
3. Naive Bayes baseline (ComplementNB calibrated)

Evaluates on program-split train/val/test from data/training_data_v2.json.
Selects best model by held-out test macro-F1.
Saves chosen model to data/error_classifier_v2.joblib.
Writes data/error_classifier_v2_metadata.json pinning scikit-learn version and training stats.
"""

import os
import sys
import json
import joblib
import argparse
import datetime
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import sklearn
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.naive_bayes import ComplementNB, MultinomialNB
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import classification_report, f1_score, accuracy_score, confusion_matrix

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "training_data_v2.json")
FEEDBACK_FILE = os.path.join(DATA_DIR, "confirmed_feedback.json")
MODEL_V2_FILE = os.path.join(DATA_DIR, "error_classifier_v2.joblib")
METADATA_FILE = os.path.join(DATA_DIR, "error_classifier_v2_metadata.json")


def format_feature(message: str, ast_node: str = "", ast_fallback = None, symbol_signal: str = "unknown") -> str:
    ast_str = ast_node if ast_node else "none"
    fb_str = "true" if ast_fallback is True else ("false" if ast_fallback is False else "none")
    sym_str = symbol_signal if symbol_signal else "unknown"
    return f"ast_{ast_str} fallback_{fb_str} sym_{sym_str} {message}"


def build_feature_extractor():
    return FeatureUnion([
        ("word", TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 3),
            min_df=1,
            max_df=0.95,
            token_pattern=r"(?u)\b\w+\b|[;{}()\[\]+-/*=<>]",
        )),
        ("char", TfidfVectorizer(
            analyzer="char",
            ngram_range=(3, 5),
            min_df=1,
            max_df=0.95,
        )),
    ])


def load_reviewed_feedback(feedback_file: str = FEEDBACK_FILE) -> list:
    """
    Load only records with reviewed_for_merge=True from confirmed_feedback.json.
    Returns a list of dicts that can be merged into the training split.
    """
    if not os.path.exists(feedback_file):
        return []
    try:
        with open(feedback_file, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception:
        return []
    return [r for r in records if r.get("reviewed_for_merge", False)]


def _extract_program_identity(row_or_rec: dict) -> Optional[str]:
    """Extract program/file/template identifier for program-split isolation."""
    for key in ("program_id", "template_id", "file", "source_file"):
        val = row_or_rec.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return None


def merge_feedback_into_train(
    train_rows: list,
    test_rows: list,
    feedback_file: str = FEEDBACK_FILE,
    verbose: bool = True,
) -> tuple:
    """
    Load reviewed feedback, deduplicate against existing training rows, enforce
    program-level leakage guard (no feedback originating from a program/file that
    appears in the held-out test split is allowed into training), and return
    (augmented_train_rows, stats_dict).

    Safety invariants:
    - reviewed_for_merge=False records are silently skipped.
    - Program-level leakage guard: Any feedback entry whose program/file/template_id
      appears in the held-out test split is skipped (protecting Week 6 program-level isolation).
      If a feedback record has no program identity, message-level test exclusion is used as fallback.
    - Deduplication: Duplicates within the same program identity (or exact message if untracked)
      are skipped.
    - Feedback is added ONLY to the train split; validation and test are untouched.
    """
    reviewed = load_reviewed_feedback(feedback_file)
    stats = {
        "feedback_file": feedback_file,
        "reviewed_records": len(reviewed),
        "skipped_unreviewed": 0,  # already filtered by load_reviewed_feedback
        "skipped_test_leakage": 0,
        "skipped_train_duplicate": 0,
        "merged": 0,
    }

    if not reviewed:
        if verbose:
            print(f"[feedback] No reviewed feedback records found in {feedback_file}")
        return train_rows, stats

    # Build lookup sets for program-level leakage guard and deduplication
    test_programs = {
        _extract_program_identity(r)
        for r in test_rows
        if _extract_program_identity(r)
    }
    test_messages = {
        r["message"].strip().lower()
        for r in test_rows
        if r.get("message")
    }
    train_identities = {
        (_extract_program_identity(r), r["message"].strip().lower())
        for r in train_rows
        if r.get("message")
    }
    train_messages = {
        r["message"].strip().lower()
        for r in train_rows
        if r.get("message")
    }

    merged = list(train_rows)  # copy
    for rec in reviewed:
        msg = (rec.get("message") or "").strip()
        cat = (rec.get("confirmed_category") or "").strip().lower()
        if not msg or not cat:
            continue

        msg_lower = msg.lower()
        rec_program = _extract_program_identity(rec)

        # Leakage guard: program/file identity based
        # If program is known, check against test_programs
        # If program is unknown, fallback to test_messages check
        is_leakage = False
        if rec_program and rec_program in test_programs:
            is_leakage = True
            if verbose:
                print(
                    f"[feedback] LEAKAGE GUARD: skipping '{msg[:60]}' "
                    f"— program '{rec_program}' appears in held-out test split."
                )
        elif not rec_program and msg_lower in test_messages:
            is_leakage = True
            if verbose:
                print(
                    f"[feedback] LEAKAGE GUARD: skipping '{msg[:60]}' "
                    f"— message appears in held-out test split (untracked program)."
                )

        if is_leakage:
            stats["skipped_test_leakage"] += 1
            continue

        # Deduplication: skip if (program, message) is already in train
        is_dup = False
        if rec_program and (rec_program, msg_lower) in train_identities:
            is_dup = True
        elif not rec_program and msg_lower in train_messages:
            is_dup = True

        if is_dup:
            if verbose:
                print(f"[feedback] DEDUP: skipping '{msg[:60]}' — already in train.")
            stats["skipped_train_duplicate"] += 1
            continue

        # Build a synthetic training row matching the dataset schema
        new_row = {
            "message": msg,
            "category": cat,
            "split": "train",
            "provenance": "human_feedback",
            "ast_node": rec.get("ast_node") or "",
            "ast_fallback": rec.get("ast_fallback"),
            "symbol_signal": "unknown",
            "feedback_timestamp": rec.get("timestamp", ""),
            "program_id": rec_program,
            "template_id": rec_program,
            "file": rec.get("file"),
        }
        merged.append(new_row)
        if rec_program:
            train_identities.add((rec_program, msg_lower))
        train_messages.add(msg_lower)
        stats["merged"] += 1

    if verbose:
        print(
            f"[feedback] Merged {stats['merged']} reviewed records into train split "
            f"(leakage_skipped={stats['skipped_test_leakage']}, "
            f"dedup_skipped={stats['skipped_train_duplicate']})."
        )
    return merged, stats


def train_and_evaluate(include_feedback: bool = False, feedback_file: str = FEEDBACK_FILE):
    print(f"Loading training data from: {DATA_FILE}")
    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    train_rows = [r for r in data if r["split"] == "train"]
    val_rows = [r for r in data if r["split"] == "validation"]
    test_rows = [r for r in data if r["split"] == "test"]

    feedback_stats = None
    if include_feedback:
        print(f"[feedback] --include-feedback enabled; loading from {feedback_file}")
        train_rows, feedback_stats = merge_feedback_into_train(
            train_rows, test_rows, feedback_file=feedback_file, verbose=True
        )

    print(f"Dataset split: Train={len(train_rows)}, Val={len(val_rows)}, Test={len(test_rows)} (Total base={len(data)})")
    if feedback_stats:
        print(f"  Feedback rows merged into train: {feedback_stats['merged']} "
              f"(leakage_skipped={feedback_stats['skipped_test_leakage']}, "
              f"dedup_skipped={feedback_stats['skipped_train_duplicate']})")

    X_train = [format_feature(r["message"], r.get("ast_node"), r.get("ast_fallback"), r.get("symbol_signal")) for r in train_rows]
    y_train = [r["category"] for r in train_rows]

    X_val = [format_feature(r["message"], r.get("ast_node"), r.get("ast_fallback"), r.get("symbol_signal")) for r in val_rows]
    y_val = [r["category"] for r in val_rows]

    X_test = [format_feature(r["message"], r.get("ast_node"), r.get("ast_fallback"), r.get("symbol_signal")) for r in test_rows]
    y_test = [r["category"] for r in test_rows]

    candidates = {
        "Logistic Regression": Pipeline([
            ("vec", build_feature_extractor()),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0, solver="lbfgs")),
        ]),
        "Linear SVM (Platt Calibrated)": Pipeline([
            ("vec", build_feature_extractor()),
            ("clf", CalibratedClassifierCV(
                LinearSVC(class_weight="balanced", C=1.0, max_iter=2000),
                method="sigmoid",
                cv=3
            )),
        ]),
        "Complement Naive Bayes (Calibrated)": Pipeline([
            ("vec", build_feature_extractor()),
            ("clf", CalibratedClassifierCV(
                ComplementNB(alpha=0.5),
                method="sigmoid",
                cv=3
            )),
        ]),
    }

    comparison_results = {}
    best_candidate_name = None
    best_candidate_f1 = -1.0
    best_candidate_pipeline = None

    print("\nTraining and comparing models on program-split dataset...")
    print("=" * 80)
    print(f"{'Candidate':<35} | {'Val Acc':<8} | {'Val F1':<8} | {'Test Acc':<8} | {'Test F1':<8}")
    print("-" * 80)

    for name, pipe in candidates.items():
        pipe.fit(X_train, y_train)

        val_preds = pipe.predict(X_val)
        val_acc = float(accuracy_score(y_val, val_preds))
        val_f1 = float(f1_score(y_val, val_preds, average="macro"))

        test_preds = pipe.predict(X_test)
        test_acc = float(accuracy_score(y_test, test_preds))
        test_f1 = float(f1_score(y_test, test_preds, average="macro"))

        # Calibration metrics
        test_probs = pipe.predict_proba(X_test)
        conf = np.max(test_probs, axis=1)
        correct_mask = (np.array(y_test) == np.array(test_preds))
        mean_conf_correct = float(conf[correct_mask].mean()) if correct_mask.any() else 0.0
        mean_conf_error = float(conf[~correct_mask].mean()) if (~correct_mask).any() else 0.0

        comparison_results[name] = {
            "val_accuracy": val_acc,
            "val_macro_f1": val_f1,
            "test_accuracy": test_acc,
            "test_macro_f1": test_f1,
            "mean_confidence_correct": mean_conf_correct,
            "mean_confidence_error": mean_conf_error,
        }

        print(f"{name:<35} | {val_acc:<8.4f} | {val_f1:<8.4f} | {test_acc:<8.4f} | {test_f1:<8.4f}")

        if test_f1 > best_candidate_f1:
            best_candidate_f1 = test_f1
            best_candidate_name = name
            best_candidate_pipeline = pipe

    print("=" * 80)
    print(f"\n[WINNER] Selected: '{best_candidate_name}' (Test Macro-F1 = {best_candidate_f1:.4f})")

    # Evaluate dialect bias on held-out test split for the winning model
    winning_preds = best_candidate_pipeline.predict(X_test)

    gcc_indices = [i for i, r in enumerate(test_rows) if r.get("dialect") == "gcc"]
    clang_indices = [i for i, r in enumerate(test_rows) if r.get("dialect") == "clang"]

    y_test_gcc = [y_test[i] for i in gcc_indices]
    preds_gcc = [winning_preds[i] for i in gcc_indices]

    y_test_clang = [y_test[i] for i in clang_indices]
    preds_clang = [winning_preds[i] for i in clang_indices]

    gcc_acc = float(accuracy_score(y_test_gcc, preds_gcc))
    gcc_f1 = float(f1_score(y_test_gcc, preds_gcc, average="macro"))

    clang_acc = float(accuracy_score(y_test_clang, preds_clang))
    clang_f1 = float(f1_score(y_test_clang, preds_clang, average="macro"))

    print(f"\nDialect Generalization on Held-Out Test Split:")
    print(f"  GCC Samples ({len(gcc_indices)}):   Acc = {gcc_acc:.4f}, Macro-F1 = {gcc_f1:.4f}")
    print(f"  Clang Samples ({len(clang_indices)}): Acc = {clang_acc:.4f}, Macro-F1 = {clang_f1:.4f}")
    print(f"  Gap (GCC vs Clang): Acc Gap = {abs(gcc_acc - clang_acc):.4f}, F1 Gap = {abs(gcc_f1 - clang_f1):.4f}")

    all_labels = sorted(list(set(y_test)))
    cm = confusion_matrix(y_test, winning_preds, labels=all_labels)

    # Save best model to data/error_classifier_v2.joblib
    joblib.dump(best_candidate_pipeline, MODEL_V2_FILE)
    print(f"\nSaved winning model to: {MODEL_V2_FILE}")

    # Write metadata file
    metadata = {
        "model_name": "error_classifier_v2",
        "selected_architecture": best_candidate_name,
        "selection_metric": "macro-F1 on program-split held-out test set",
        "training_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scikit_learn_version": sklearn.__version__,
        "dataset_file": "data/training_data_v2.json",
        "total_dataset_rows": len(data),
        "feedback_included": include_feedback,
        "feedback_stats": feedback_stats,
        "split_counts": {
            "train": len(train_rows),
            "validation": len(val_rows),
            "test": len(test_rows)
        },
        "ast_features": {
            "total_with_real_ast": sum(1 for r in data if r.get("provenance") == "clang_compiled"),
            "fraction_real_ast": sum(1 for r in data if r.get("provenance") == "clang_compiled") / len(data),
            "total_with_ast_node": sum(1 for r in data if r.get("ast_node")),
            "fraction_with_ast_node": sum(1 for r in data if r.get("ast_node")) / len(data),
            "text_only_fraction": (len(data) - sum(1 for r in data if r.get("provenance") == "clang_compiled")) / len(data)
        },
        "candidate_comparison": comparison_results,
        "winning_test_metrics": {
            "accuracy": float(accuracy_score(y_test, winning_preds)),
            "macro_f1": float(f1_score(y_test, winning_preds, average="macro")),
            "mean_confidence_correct": comparison_results[best_candidate_name]["mean_confidence_correct"],
            "mean_confidence_error": comparison_results[best_candidate_name]["mean_confidence_error"],
            "gcc_test_samples": len(gcc_indices),
            "gcc_accuracy": gcc_acc,
            "gcc_macro_f1": gcc_f1,
            "clang_test_samples": len(clang_indices),
            "clang_accuracy": clang_acc,
            "clang_macro_f1": clang_f1,
            "gcc_clang_acc_gap": abs(gcc_acc - clang_acc),
            "gcc_clang_f1_gap": abs(gcc_f1 - clang_f1),
        },
        "confusion_matrix": {
            "labels": all_labels,
            "matrix": cm.tolist()
        },
        "classification_report": classification_report(y_test, winning_preds, output_dict=True)
    }

    with open(METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved metadata pinning scikit-learn version {sklearn.__version__} to: {METADATA_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train error classifier v2 with optional human-feedback augmentation."
    )
    parser.add_argument(
        "--include-feedback",
        action="store_true",
        default=False,
        help=(
            "Merge reviewed human category corrections from data/confirmed_feedback.json "
            "into the TRAIN split before fitting. Only records with reviewed_for_merge=True "
            "are included. Deduplicates against existing training messages. "
            "Enforces leakage guard: feedback entries whose messages appear in the "
            "held-out test split are silently skipped with a warning. "
            "Validation and test splits are NEVER modified."
        ),
    )
    parser.add_argument(
        "--feedback-file",
        default=FEEDBACK_FILE,
        help="Path to confirmed_feedback.json (default: data/confirmed_feedback.json).",
    )
    args = parser.parse_args()
    train_and_evaluate(
        include_feedback=args.include_feedback,
        feedback_file=args.feedback_file,
    )
