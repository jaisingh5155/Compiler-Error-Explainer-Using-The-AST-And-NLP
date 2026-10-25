# Week 9 Part 5 — Feedback Store Verification Report

Generated: 2026-09-30  
Baseline: WEEK9_PARTS1-4_VERIFICATION.md (29/54 auto-healer, corrected denominators)

---

## Summary of Deliverables

| Deliverable | Status |
|---|---|
| `data/patch_feedback.jsonl` writer wired to Part 2's Accept/Reject/Undo | ✅ Done (Part 5, prior session) |
| Atomic-write fix for `feedback_store.py` (`save_feedback_atomic`) | ✅ Done |
| GUI category-correction action wired to `record_feedback()` | ✅ Done |
| CLI review helper (`python -m src.feedback_store review`) | ✅ Done |
| `--include-feedback` for `train_classifier_v2.py` (train-only, deduped, reviewed-only) | ✅ Done |
| `tests/week9_verification/test_feedback_store.py` (19 tests, all passing) | ✅ Done |

---

## Task 1 — Patch-Decision Log

File: `data/patch_feedback.jsonl` (append-only JSONL).

Each record contains:
```json
{
  "timestamp": "<ISO 8601 UTC>",
  "file_hash":  "<SHA-256 of file content before patch — not the file itself>",
  "patch_id":   "<int>",
  "diagnostic": {"message": "...", "line": <int>, "category": "..."},
  "safety_tier": <int>,
  "safety_level": "S0|S1|...",
  "tier_name":  "Tier N: ...",
  "decision":   "accepted|rejected|undone",
  "gate_results": [{"gate": "...", "passed": true|false, "reason": "..."}],
  "ref_patch_id": "<id of original accept — only on undone records>",
  "ref_timestamp": "<timestamp of original accept — only on undone records>"
}
```

An **undo** appends a new record with `decision="undone"` referencing the original
via `ref_patch_id` / `ref_timestamp`. The log is append-only; no line is ever
rewritten or deleted.

Integration point: `PatchReviewSession.accept()`, `.reject()`, `.undo()` in
`src/patch_review.py` each call `feedback_store.log_patch_decision()`.

**Patch decisions are STRICTLY SEPARATE from category corrections. They never
flow into classifier training data.**

---

## Task 2 — Atomic Write Fix

### Implementation

`feedback_store.save_feedback_atomic()` in `src/feedback_store.py`:

1. `tempfile.mkstemp(prefix="feedback_", suffix=".tmp", dir=<same dir as target>)`
2. Write JSON to temp fd → `f.flush()` → `os.fsync(f.fileno())`
3. `os.replace(tmp_path, feedback_file)` — atomic on POSIX (same filesystem)
4. On any exception: remove the `.tmp` file then re-raise

`record_feedback()` now calls `save_feedback_atomic()` instead of a plain `json.dump`.

### Crash Simulation Test Result

```
TestAtomicWrite::test_simulated_crash_leaves_original_intact   PASSED
TestAtomicWrite::test_tmp_cleaned_up_on_failure                PASSED
TestAtomicWrite::test_no_orphaned_tmp_files                    PASSED
TestAtomicWrite::test_valid_json_after_appends                 PASSED
```

The test patches `os.replace` to raise `OSError` immediately after the temp file
is written. The original file survives with its prior content intact; no partial
write or truncation occurs.

---

## Task 3 — Retraining with `--include-feedback`

Extended `src/train_classifier_v2.py` with:

```
python src/train_classifier_v2.py --include-feedback [--feedback-file PATH]
```

### What it does

1. Loads `data/confirmed_feedback.json`
2. Filters to `reviewed_for_merge: true` only
3. Deduplicates against existing train-split messages (case-insensitive)
4. Enforces leakage guard (see Task 4 below)
5. Merges survivors into `train_rows` — **validation and test splits are never touched**
6. Logs `feedback_stats` into `error_classifier_v2_metadata.json`

### CLI review helper

```bash
# List unreviewed corrections
python -m src.feedback_store review list

# Approve specific indices
python -m src.feedback_store review approve 0 2 5

# Approve all at once
python -m src.feedback_store review approve --all

# Reject (mark unapproved)
python -m src.feedback_store review reject 1 3
```

Retraining **never triggers automatically** from any GUI or CLI action in Tasks 1–2.
It only runs when a human explicitly invokes the script with `--include-feedback`.

---

## Task 4 — Silent Write-Back Audit

### Grep command and exact output

```bash
$ grep -rn --include="*.py" \
    "open.*training_data\|json\.dump.*training_data" \
    src/
```

**Exact output:**

```
src/error_classifier.py:53:    with open(training_data_file, "r") as f:
```

### Analysis

The single hit is `error_classifier.py:53`, which opens the training data file in
**read-only mode (`"r"`)** to load examples at classifier init time. This is not a
write. There is no write (`"w"` or `"a"` mode) to any `training_data*.json` file
outside the four dedicated scripts:

| Dedicated script (allowed to write) | Role |
|---|---|
| `src/build_dataset_from_tests.py` | Dataset construction from test fixtures |
| `src/prepare_training_data.py` | Dataset construction from CodeNet Arrow files |
| `src/train_classifier_v2.py` | Model training (reads training data, writes model) |
| `src/feedback_store.py` | Writes to `confirmed_feedback.json` only (never training_data) |

Additional gates confirmed intact:
- `dataset_logger.py`: gated by `ENABLE_DATASET_LOGGING` env var (Bug 7.1 fix)
- `main.py`: requires `--log-training` opt-in flag (no silent write on default run)
- `gui.py`: category correction calls `record_feedback()` → `confirmed_feedback.json`
  only; never writes to `training_data*.json`

All four checks are codified as formal tests in `TestSilentWriteBackAudit`.

---

## Leakage Guard — Policy Decision and Rationale

**Policy chosen: message-level exclusion, case-insensitive.**

A feedback record is blocked from the train split if its `message` field
(stripped, lowercased) matches any `message` field of any record in the held-out
test split.

### Why message-level (not program-level)?

The alternative is **program-level exclusion**: if any diagnostic from program `P`
appears in the test split, all feedback from program `P` is blocked.

Program-level is safer in theory (no leakage of program-level features) but it
requires reliable program identity across feedback records and the training dataset.
Feedback records currently have no `program_id` field — adding one would require
changes to the GUI action and the CLI review flow.

Message-level exclusion is:
1. **Implementable now** without schema changes
2. **Strictly conservative** for our threat model: the classifier's features
   (`format_feature(message, ast_node, ast_fallback, symbol_signal)`) are primarily
   message-text features, so message-level dedup is the exact right granularity
3. **Documented** — the risk of over-exclusion (very common compiler messages that
   appear in both train and test splits) is noted and acceptable

If program-level tracking is added later (e.g., a `source_file_hash` field in
feedback records), the guard in `merge_feedback_into_train()` can be upgraded
without changing any other interface.

---

## Verification Results

### V1 — Atomic write resilience

| Test | Result |
|---|---|
| 10 appends → valid JSON | ✅ PASS |
| No orphaned .tmp files | ✅ PASS |
| Simulated crash: original intact | ✅ PASS |
| Temp file cleaned on failure | ✅ PASS |

### V2 — Unreviewed feedback exclusion

| Test | Result |
|---|---|
| Only reviewed_for_merge=True returned | ✅ PASS |
| confirmed_category alone insufficient | ✅ PASS |
| Approve-then-reject respects flag | ✅ PASS |

### V3 — Deduplication

| Test | Result |
|---|---|
| Same message twice → 1 merged | ✅ PASS |
| Already-in-train message → skipped | ✅ PASS |

### V4 — Leakage guard

| Test | Result |
|---|---|
| Test-split message blocked | ✅ PASS |
| Case-insensitive match blocked | ✅ PASS |
| Safe message passes | ✅ PASS |

### V5 — Silent write-back audit

| Test | Result |
|---|---|
| No write violations in non-dedicated scripts | ✅ PASS |
| dataset_logger.py has ENABLE_DATASET_LOGGING gate | ✅ PASS |
| main.py requires --log-training | ✅ PASS |
| gui.py no training_data write | ✅ PASS |

**Overall: 19/19 tests PASS.**

---

## Zero-Regression Confirmation

This part adds:
- A new append-only log file (`data/patch_feedback.jsonl`) — no existing output changes
- A new JSON file (`data/confirmed_feedback.json`) — no existing output changes
- GUI elements (category dropdown on error cards) — no behaviour change to existing flow
- `--include-feedback` flag on trainer — off by default, zero impact without the flag

The full Week 9 verification suite across all five parts is 100% green (43/43 tests pass):

| Test Suite | File | Tests | Result |
|---|---|---|---|
| Part 1: Agent Trace View | `tests/week9_verification/test_part1_trace_view.py` | 6 | ✅ 6/6 PASS |
| Part 2: Patch Review Panel | `tests/week9_verification/test_part2_patch_review.py` | 6 | ✅ 6/6 PASS |
| Part 3: Grouped Errors & Security | `tests/week9_verification/test_part3_grouped_errors_and_security.py` | 6 | ✅ 6/6 PASS |
| Part 4: Batch Evaluator & Report | `tests/week9_verification/test_part4_batch_and_reporting.py` | 6 | ✅ 6/6 PASS |
| Part 5: Feedback Store & Training Guard | `tests/week9_verification/test_feedback_store.py` | 19 | ✅ 19/19 PASS |
| **Total** | | **43** | **✅ 43/43 PASS (100%)** |

*(Note on Part 3 test: `test_gui_offscreen_grouped_errors_and_security_smoke` was adjusted to search for the specific collapsible toggle button containing `"follow-on"` text rather than matching the first `QPushButton` in the error card layout, since error cards now include the category confirmation button).*

**No benchmark file, model file, or existing pipeline output is modified by any
code in Part 5.**

---

## Files Changed in Part 5

| File | Change |
|---|---|
| `src/feedback_store.py` | Atomic write, patch log, CLI review helper |
| `src/patch_review.py` | Accept/reject/undo wire to patch_feedback.jsonl |
| `src/gui.py` | Category correction dropdown + confirm button on every error card |
| `src/train_classifier_v2.py` | `--include-feedback`, `merge_feedback_into_train()`, leakage guard |
| `tests/week9_verification/test_feedback_store.py` | 19 new tests (all green) |
| `WEEK9_PART5_REPORT.md` | This file |
