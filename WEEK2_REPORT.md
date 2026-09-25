# Week 2 Deliverables & Pipeline Evaluation Report
**Project:** Compiler Error Explainer using AST and NLP  
**Milestone:** Week 2 of 10 · Benchmark Construction & Severity-Tiered Pipeline Audit  
**Date:** 2026-09-25  
**Compiler Environment:** Apple Clang version 21.0.0 (`g++` symlink), macOS (ARM64)  
**Rule Adherence:** No modifications made to any `src/*.py` production source code.

---

## 1. Executive Summary

During Week 2, our objectives were twofold:
1. **Construct a ground-truth benchmark suite** spanning all compiler diagnostic classes and common C/C++ security vulnerabilities, complete with paired metadata.
2. **Execute a comprehensive, evidence-backed pipeline audit** spanning all 7 system phases (Compiling, Classifying, Explaining, Security Scanning, Auto-Healing, GUI, and Offline Training) to produce a severity-tiered bug report.

All 4 deliverables have been constructed, validated, and evaluated against the unmodified codebase.

---

## 2. Deliverables Checklist

| Deliverable | Path | Status | Verification Detail |
|---|---|:---:|---|
| **1. Ground-Truth Benchmark** | [`benchmark/`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark) | ✅ Ready | **78 `.cpp` files + 78 companion `.json` metadata files** (156 files across 11 category subdirectories). |
| **2. Benchmark Runner** | [`benchmark/run_benchmark.py`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/run_benchmark.py) | ✅ Ready | Automated test harness that evaluates the entire pipeline, runs safe copy-based auto-healing, and tracks data leakage. |
| **3. Benchmark Results CSV** | [`benchmark/BENCHMARK_RESULTS.csv`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/BENCHMARK_RESULTS.csv) | ✅ Ready | Complete dataset containing row-by-row match verdicts and aggregate performance metrics at the top. |
| **4. Severity-Tiered Bug Report** | [`BUG_REPORT.md`](file:///Users/jaisinghsaini/TOACD/cd1/BUG_REPORT.md) | ✅ Ready | 21 identified bugs (5 P0, 8 P1, 8 P2) across all 7 pipeline phases with evidence, impact, and fix directions. |

---

## 3. Benchmark Suite Composition (78 Tests)

The benchmark is partitioned into 11 specialized directories. Each `.cpp` file is paired with an identical-name `.json` manifest containing expected status, expected category, expected line, expected CWE, expected security verdict, and test notes.

| Category | Count (`.cpp` + `.json`) | Target Scope & Error Types |
|---|:---:|---|
| [`clean`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/clean) | 8 + 8 | Code compiling cleanly without errors or warnings; baseline for false positives. |
| [`linker_errors`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/linker_errors) | 5 + 5 | Missing `main()`, undefined reference, unresolved externals. |
| [`missing_include`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/missing_include) | 4 + 4 | Omitted `#include <iostream>`, `<vector>`, `<string>`, `<map>`. |
| [`multi_error`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/multi_error) | 5 + 5 | Independent cascade errors, syntax + type errors, compile + security issues. |
| [`name_resolution`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/name_resolution) | 8 + 8 | Undeclared variables/functions, typo keywords (`retrun`), missing namespace. |
| [`redefinition`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/redefinition) | 4 + 4 | Duplicate variable declarations, conflicting function definitions. |
| [`return_type`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/return_type) | 4 + 4 | Missing return in non-void function, returning invalid types, void returns. |
| [`security`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security) | 16 + 16 | Vulnerability test cases (CWE-78, 120, 134, 190, 401, 415, 416, 457, 476) + 4 safe decoys. |
| [`syntax`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/syntax) | 10 + 10 | Missing semicolons, unmatched braces/brackets/parentheses across scopes. |
| [`type_errors`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/type_errors) | 8 + 8 | Incompatible assignments, pointer mismatches, invalid operator operands. |
| [`warnings_only`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/warnings_only) | 6 + 6 | Clean compilation (exit code 0) producing `-Wall` warnings (unused vars, sign-compare). |
| **Total** | **78 + 78** | **156 total files** |

---

## 4. Pipeline Evaluation Results

### A. Status & Classification Accuracy
* **Overall Status Accuracy:** **82.1%** (64 / 78 correct)
  * *Primary Defect:* [main.py line 142](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py#L142) evaluates `status = "error" if visible_errors else "success"`. All warning-only files (which compile cleanly with exit 0) are mislabeled as errors.
  * *Secondary Defect:* Linker errors produce empty regex matches from `error_parser.py`, triggering fallback to `status: "success"` despite non-zero compiler exit codes.
* **Classification Accuracy:** **58.3%** (28 / 48 valid error cases)
  * *Root Cause:* The TF-IDF + Logistic Regression classifier exhibits severe compiler dialect bias (trained predominantly on GNU GCC diagnostics, struggling with Apple Clang phrasing).

### B. Security Scanner Performance
Evaluated across vulnerable targets, safe decoy patterns, and clean baseline files:

> **Benchmark Security Reconciliation Note:**  
> - **In `benchmark/security/` directly (16 files):** Exactly **12 vulnerable files** (covering 9 CWEs: CWE-78, CWE-120 [2 files], CWE-134, CWE-190, CWE-401, CWE-415, CWE-416, CWE-457, CWE-476 [3 variants]) and **4 clean decoy files** (`sec13`–`sec16`).  
> - **Full-Benchmark Recall Denominator (15 files):** 12 vulnerable files in `security/` + 3 multi-error files with security flaws in `multi_error/` (`me02` CWE-415, `me03` CWE-416, `me04` CWE-190) = **15 total vulnerable files** across the benchmark.  
> - **False-Positive Denominator (12 clean/decoy files):** Evaluated against the 8 files in `clean/` + the 4 decoys in `security/` = **12 clean/decoy files**.

* **True Positives (TP):** 7
* **False Negatives (FN):** 8
* **False Positives (FP):** 1 (Safe function `filesystem()` flagged as command injection)
* **True Negatives (TN):** 62
* **Overall Precision:** **87.5%** (`7 / 8`)
* **Overall Recall:** **46.7%** (`7 / 15`) — *More than half of valid security flaws remain undetected.*
* **False Positive Rate on Clean & Decoy Files:** **8.3%** (`1 / 12`)

#### Breakdown by CWE (15 Vulnerable Benchmark Cases Total):
| Vulnerability Class | Benchmark Cases | Detected | Recall | Scanner Bottleneck |
|---|:---:|:---:|:---:|---|
| **CWE-78** (Command Injection) | 1 | 1 | **100%** | Regex matches `system()` |
| **CWE-120** (Buffer Overflow) | 2 | 2 | **100%** | Regex matches `strcpy`/`gets` |
| **CWE-134** (Format String) | 1 | 1 | **100%** | Regex matches variable format strings |
| **CWE-190** (Integer Overflow) | 2 | 0 | **0%** | CLI does not invoke `_pre_scan()` |
| **CWE-401** (Memory Leak) | 1 | 1 | **100%** | Detected missing `delete`/`free` |
| **CWE-415** (Double Free) | 2 | 0 | **0%** | AST/Regex lacks tracking for repeated `free()` |
| **CWE-416** (Use-After-Free) | 2 | 2 | **100%** | Regex flags pointer access post `free()` |
| **CWE-457** (Uninitialized Variable) | 1 | 0 | **0%** | Compiler warning not captured by AST analyzer |
| **CWE-476** (Null Dereference) | 3 | 0 | **0%** | Fails on struct dereferences and function return nulls |

### C. Auto-Healer (Full Benchmark Run on Isolated Copies)
* **Attempted:** 48 error files total:
  - **Compiled Clean (Healed):** 17 (**35.4%** success rate)
  - **Gave Up:** 26 (**54.2%**)
  - **No Errors Parsed:** 5 (**10.4%**) — all 5 files in `linker_errors/` (`lk01`–`lk05`) where `error_parser.py` extracted 0 errors due to lack of linker regex support, leaving no errors for the healer to attempt fixing.
  - **Crashed:** 0 (**0%**)
* **Accounted Total:** $17 + 26 + 5 + 0 = 48$ attempted error files.
* *Analysis:* Simple syntax errors (missing semicolons/brackets) heal reliably when correctly classified. When the classifier misidentifies undeclared variables as `missing_include`, the healer attempts invalid `#include` injection and exhausts retry budgets.

### D. Offline Training Pipeline Data Leak Audit
* **Initial `data/training_data.json`:** `14,719,358` bytes (`MD5: 0239658bf3b6c91064e89dba5e954d30`)
* **Post-Run `data/training_data.json`:** `14,731,700` bytes (`MD5: ec0e2de30feb2c83c70bc8fd58f6138a`)
* **Critical Finding:** Running `main.py` invokes [dataset_logger.py](file:///Users/jaisinghsaini/TOACD/cd1/src/dataset_logger.py) on every execution, appending unverified test inputs directly into the training corpus (+12,342 bytes).
* **Backup & Week 6 Baseline Status:**
  - `data/training_data.json` was **not** backed up to `legacy_artifacts/` before the benchmark run, meaning the live file is contaminated and **no longer a clean baseline for Week 6 retraining**.
  - The contaminated state is now backed up at [`legacy_artifacts/training_data_contaminated_week2.json`](file:///Users/jaisinghsaini/TOACD/cd1/legacy_artifacts/training_data_contaminated_week2.json).
  - The pristine pre-benchmark baseline has been retrieved from git history and archived at [`legacy_artifacts/training_data_pristine_week1.json`](file:///Users/jaisinghsaini/TOACD/cd1/legacy_artifacts/training_data_pristine_week1.json) to serve as the clean ground truth for Week 6.

---

## 5. Bug Inventory Summary (`BUG_REPORT.md`)

[BUG_REPORT.md](file:///Users/jaisinghsaini/TOACD/cd1/BUG_REPORT.md) groups all 21 discovered defects into severity tiers and architectural phases:

### Severity Distribution
* **P0 (Critical / Dangerous Behavior):** 5 bugs
* **P1 (Broken / Unreachable Feature):** 8 bugs
* **P2 (Quality / False Positives / UX):** 8 bugs
* **Total Discovered:** **21 bugs**

### Distribution by Pipeline Phase
```
Phase 1: Compiling          [4 bugs]  (1 P0, 2 P1, 1 P2)
Phase 2: Classifying        [3 bugs]  (1 P0, 1 P1, 1 P2)
Phase 3: Explaining         [2 bugs]  (0 P0, 1 P1, 1 P2)
Phase 4: Security Scanning  [5 bugs]  (1 P0, 2 P1, 2 P2)
Phase 5: Auto-Healing       [2 bugs]  (1 P0, 1 P1, 0 P2)
Phase 6: GUI               [3 bugs]  (0 P0, 1 P1, 2 P2)
Phase 7: Offline Training   [2 bugs]  (1 P0, 0 P1, 1 P2)
```

### High-Priority P0 Bugs for Week 3 Remediation:
1. **Bug 1.1 (P0):** `main.py` checks `bool(visible_errors)` instead of compiler returncode, misidentifying warning-only compiles as fatal errors.
2. **Bug 2.1 (P0):** Model fails cross-compiler generalization due to lack of normalization between GCC and Clang diagnostic styles.
3. **Bug 4.1 (P0):** Security analysis is gated on clean compilation, concealing high-severity runtime vulnerabilities in files with syntax/type errors.
4. **Bug 5.1 (P0):** Auto-healer performs blind regex injections without AST boundary checks, risking code corruption inside multiline literals.
5. **Bug 7.1 (P0):** Un-gated auto-logging corrupts the model training set with live runtime evaluation outputs.

---

## 6. Next Steps for Week 3

With the baseline measured and all bugs documented, Phase 1 (Compiler Execution) and Phase 2 (Diagnostic Classification) bug fixes will commence in Week 3:
1. Fix exit-code status determination in `main.py`.
2. Expand `error_parser.py` regexes to capture linker errors and compiler warnings properly.
3. Decouple security scanning from compilation success.
4. Disable runtime data poisoning in `dataset_logger.py`.
