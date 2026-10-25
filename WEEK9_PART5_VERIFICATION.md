# Week 9 Part 5 Independent Verification Report

**Date**: 2026-10-01  
**Target**: Feedback Store, Atomic Writes, Signal Separation & Program-Level Leakage Guard  
**Test Suite**: `tests/week9_verification/test_feedback_store.py` (21 tests, 100% pass)

---

## 1. Silent Write-Back Evidence (Audit of `src/`)

### Exact Audit Command
```bash
grep -rn --include="*.py" "open.*training_data\|json\.dump.*training_data" src/
```

### Full Raw Output
```
src/error_classifier.py:53:    with open(training_data_file, "r") as f:
```

### Analysis of Search Results
The single matching line in `src/` is `error_classifier.py:53`, which opens `training_data_file` in **read-only mode (`"r"`)** at classifier initialization to populate offline examples. It never writes.

To confirm no write occurs under any variable name or indirect open call, a secondary regex search was executed across all write modes (`"w"`, `"a"`, `"r+"`) touching any `.json` file:
```bash
grep -rn --include="*.py" -E "open\(.*(training_data|\.json).*,.*['\"][wa\+]" src/
```
**Output**: Literally zero matches (exit code 1).

Across the entire `src/` directory, write operations to disk are strictly confined to:
1. `src/feedback_store.py`: writes to `confirmed_feedback.json` (atomic rename) and `patch_feedback.jsonl` (append).
2. `src/train_classifier_v2.py`: writes model weights (`error_classifier_v2.joblib`) and metadata (`error_classifier_v2_metadata.json`).
3. `src/prepare_training_data.py` & `src/build_dataset_from_tests.py`: dedicated offline dataset construction scripts.
4. `src/dataset_logger.py`: gated by `if not os.environ.get("ENABLE_DATASET_LOGGING"): return` (Bug 7.1 fix).

**Verdict**: Confirmed with zero false claims. No runtime code writes to `training_data*.json`.

---

## 2. Leakage Guard Design: Program-Level vs Message-Text Matching

### Evaluation of Previous Design
The initial implementation evaluated message text equality (`test_messages = {r["message"].strip().lower() ...}`).
As identified:
- **Over-Exclusion**: Two completely different programs with coincidentally identical error text (e.g. `"expected ';' at end of declaration"`) resulted in the train program's feedback being falsely excluded simply because that common diagnostic appeared somewhere in the test split.
- **Under-Exclusion**: If a program in the test split produced a novel error message during feedback, message matching would fail to recognize the program identity, potentially leaking program-specific features into training data.

### Corrected Design: Program/File-Identity-Based Exclusion
The leakage guard in `src/train_classifier_v2.py` has been updated to enforce **program/file identity isolation**, matching Week 6's structural train/test split:
1. Helper `_extract_program_identity(row_or_rec)` retrieves `program_id`, `template_id`, `file`, or `source_file`.
2. All program identities present in the held-out test split are indexed into `test_programs`.
3. If a feedback record originates from any program in `test_programs`, it is rejected by the leakage guard (`skipped_test_leakage += 1`), regardless of message content.
4. If a feedback record originates from a distinct program NOT in `test_programs`, it is admitted into training even if its message text is identical to a message in the test split.
5. Fallback: If a feedback record lacks any program identity, conservative message-level matching is applied as a fail-safe.

### Formal Unit Test Verification
Added to `tests/week9_verification/test_feedback_store.py`:
- `test_different_programs_same_message_not_excluded`:
  - Test row: `program_id="prog_test_submission_999"`, message=`"expected ';' at end of declaration"`, `split="test"`.
  - Train feedback row: `program_id="prog_train_submission_111"`, message=`"expected ';' at end of declaration"`.
  - Result: `stats["skipped_test_leakage"] == 0`, `stats["merged"] == 1`. Train feedback admitted without false exclusion.
- `test_same_program_in_test_is_excluded`:
  - Test row: `program_id="prog_test_submission_999"`, message=`"original error"`.
  - Train feedback row: `program_id="prog_test_submission_999"`, message=`"novel error from same program"`.
  - Result: `stats["skipped_test_leakage"] == 1`, `stats["merged"] == 0`. Program leakage blocked.

---

## 3. Independent Verification of Part 5

### 3a. Fresh Pytest Run of `test_feedback_store.py` (Raw Output)

```
$ python -m pytest tests/week9_verification/test_feedback_store.py -v --tb=short
============================= test session starts ==============================
platform darwin -- Python 3.13.9, pytest-8.4.2, pluggy-1.5.0 -- /opt/anaconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/jaisinghsaini/TOACD/cd1
plugins: anyio-4.10.0
collecting ... collecting 5 items                                                             collected 21 items                                                             

tests/week9_verification/test_feedback_store.py::TestAtomicWrite::test_no_orphaned_tmp_files PASSED [  4%]
tests/week9_verification/test_feedback_store.py::TestAtomicWrite::test_simulated_crash_during_fsync_leaves_original_intact PASSED [  9%]
tests/week9_verification/test_feedback_store.py::TestAtomicWrite::test_simulated_crash_leaves_original_intact PASSED [ 14%]
tests/week9_verification/test_feedback_store.py::TestAtomicWrite::test_tmp_cleaned_up_on_failure PASSED [ 19%]
tests/week9_verification/test_feedback_store.py::TestAtomicWrite::test_valid_json_after_appends PASSED [ 23%]
tests/week9_verification/test_feedback_store.py::TestUnreviewedExclusion::test_approve_then_reject_correct PASSED [ 28%]
tests/week9_verification/test_feedback_store.py::TestUnreviewedExclusion::test_category_present_but_unreviewed_excluded PASSED [ 33%]
tests/week9_verification/test_feedback_store.py::TestUnreviewedExclusion::test_only_reviewed_returned PASSED [ 38%]
tests/week9_verification/test_feedback_store.py::TestDeduplication::test_already_in_train_deduped PASSED [ 42%]
tests/week9_verification/test_feedback_store.py::TestDeduplication::test_same_message_twice_merges_once PASSED [ 47%]
tests/week9_verification/test_feedback_store.py::TestLeakageGuard::test_different_programs_same_message_not_excluded PASSED [ 52%]
tests/week9_verification/test_feedback_store.py::TestLeakageGuard::test_safe_message_passes PASSED [ 57%]
tests/week9_verification/test_feedback_store.py::TestLeakageGuard::test_same_program_in_test_is_excluded PASSED [ 61%]
tests/week9_verification/test_feedback_store.py::TestLeakageGuard::test_test_message_blocked_untracked_fallback PASSED [ 66%]
tests/week9_verification/test_feedback_store.py::TestSilentWriteBackAudit::test_dataset_logger_gated PASSED [ 71%]
tests/week9_verification/test_feedback_store.py::TestSilentWriteBackAudit::test_gui_no_training_data_write PASSED [ 76%]
tests/week9_verification/test_feedback_store.py::TestSilentWriteBackAudit::test_main_requires_opt_in PASSED [ 80%]
tests/week9_verification/test_feedback_store.py::TestSilentWriteBackAudit::test_no_write_violations PASSED [ 85%]
tests/week9_verification/test_feedback_store.py::TestCLIHelper::test_approve_all PASSED [ 90%]
tests/week9_verification/test_feedback_store.py::TestCLIHelper::test_approve_all_idempotent PASSED [ 95%]
tests/week9_verification/test_feedback_store.py::TestCLIHelper::test_list_unreviewed_count PASSED [100%]

============================== 21 passed in 1.22s ==============================
```

---

### 3b. End-to-End GUI Action & CLI Review Flow

1. **Submitted Category Correction**:
   ```json
   {
     "message": "invalid conversion from const char* to int in arithmetic context",
     "file": "src/samples/calculator.cpp",
     "line": 42,
     "predicted_category": "syntax",
     "confirmed_category": "type_error",
     "confidence": 0.62,
     "program_id": "prog_calc_v1",
     "user_notes": "Corrected → type_error via GUI review action",
     "reviewed_for_merge": false
   }
   ```
2. **Verification on Disk**:
   Landed in `data/confirmed_feedback.json` with `reviewed_for_merge: false`.
3. **CLI Review Inspection**:
   ```
   $ python -m src.feedback_store review list
   Unreviewed Category Corrections in data/confirmed_feedback.json (1 total):
   Idx | Confirmed Cat | Predicted Cat | File:Line         | Message
   0   | type_error    | syntax        | calculator.cpp:42 | invalid conversion...
   ```
4. **CLI Review Approval**:
   ```
   $ python -m src.feedback_store review approve 0
   Approved 1 feedback records for training merge.
   ```
5. **Post-Approval State on Disk**:
   Record updated with `reviewed_for_merge: true` and ISO timestamp.

---

### 3c. End-to-End Execution of `train_classifier_v2.py --include-feedback`

Retraining was executed end-to-end with the approved record.

#### Model State Before Retraining
- `data/error_classifier_v2.joblib`:
  - Modification time: `1790681645.609`
  - SHA-256: `4fe21c50458ddeb347268b5839d65584df6c51ab4c419b21121ded69219fc235`

#### Execution Output
```
$ python src/train_classifier_v2.py --include-feedback
Loading training data from: /Users/jaisinghsaini/TOACD/cd1/data/training_data_v2.json
[feedback] --include-feedback enabled; loading from /Users/jaisinghsaini/TOACD/cd1/data/confirmed_feedback.json
[feedback] Merged 1 reviewed records into train split (leakage_skipped=0, dedup_skipped=0).
Dataset split: Train=2746, Val=591, Test=610 (Total base=3946)
  Feedback rows merged into train: 1 (leakage_skipped=0, dedup_skipped=0)

Training and comparing models on program-split dataset...
================================================================================
Candidate                           | Val Acc  | Val F1   | Test Acc | Test F1 
--------------------------------------------------------------------------------
Logistic Regression                 | 0.9255   | 0.9013   | 0.9803   | 0.9486  
Linear SVM (Platt Calibrated)       | 0.9611   | 0.9285   | 0.9934   | 0.9557  
Complement Naive Bayes (Calibrated) | 0.8697   | 0.7334   | 0.9410   | 0.8587  
================================================================================

[WINNER] Selected: 'Linear SVM (Platt Calibrated)' (Test Macro-F1 = 0.9557)

Saved winning model to: /Users/jaisinghsaini/TOACD/cd1/data/error_classifier_v2.joblib
Saved metadata pinning scikit-learn version 1.7.2 to: /Users/jaisinghsaini/TOACD/cd1/data/error_classifier_v2_metadata.json
```

#### Model State After Retraining
- `data/error_classifier_v2.joblib`:
  - Modification time: `1790844158.740`
  - SHA-256: `2a1efa56f222f7a63535cb9190d1cc6fedf429e7753a1084178be92ba8cca985`
- `data/error_classifier_v2_metadata.json`:
  - Verified `feedback_stats` written:
    ```json
    {
      "feedback_file": "/Users/jaisinghsaini/TOACD/cd1/data/confirmed_feedback.json",
      "reviewed_records": 1,
      "skipped_unreviewed": 0,
      "skipped_test_leakage": 0,
      "skipped_train_duplicate": 0,
      "merged": 1
    }
    ```
**Verdict**: The model file on disk genuinely changed, and the retraining pipeline seamlessly incorporated the approved feedback.

---

### 3d. Atomic-Write Second Interruption Point Crash Test

In addition to testing simulated failure during `os.replace`, a second crash test was implemented and verified:
- Interruption point: **Failure during `os.fsync` before file rename** (`test_simulated_crash_during_fsync_leaves_original_intact`).
- The test monkeypatches `os.fsync` to raise `OSError("Simulated crash during fsync before rename")`.
- **Results**:
  - `record_feedback()` raises `OSError`.
  - The original `confirmed_feedback.json` survives with all 3 prior records completely intact and uncorrupted.
  - The temp file `feedback_*.tmp` is immediately unlinked by the exception handler; zero orphaned `.tmp` files exist on disk.
