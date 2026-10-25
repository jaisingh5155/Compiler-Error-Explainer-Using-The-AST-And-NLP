# Dataset Quality Audit & Pre-Retraining Analysis Report

**Milestone:** Week 6 — Classifier Dataset Rebuild & Model Retraining  
**Target Dataset:** [`legacy_artifacts/training_data_pristine_week1.json`](file:///Users/jaisinghsaini/TOACD/cd1/legacy_artifacts/training_data_pristine_week1.json)  
**File Size:** 14,719,358 bytes (14 MB)  
**MD5 Hash:** `0239658bf3b6c91064e89dba5e954d30`  
**Date:** September 26, 2026  

---

## 1. Executive Summary

Prior to rebuilding the training dataset and retraining the error classification model in Week 6, we conducted an empirical data quality audit of the clean, pre-contamination baseline dataset (`training_data_pristine_week1.json`). 

This audit reveals four major architectural weaknesses in the legacy training data:
1. **Severe Near-Duplicate Redundancy:** Out of 67,210 examples, there are only 4,264 distinct structural message templates (**93.66% near-duplicate redundancy** differing only in identifier names or numeric literals).
2. **Extreme Class Imbalance:** Class counts range from 24,997 (`other`) down to 44 (`return_type_error`), representing a **568.1x imbalance ratio** that heavily biases predictions toward generic fallbacks.
3. **Severe Dialect Asymmetry (GCC vs Clang):** Over **52.26%** of messages are explicitly GCC-phrased, while Clang-phrased diagnostics constitute **less than 0.1% (63 rows)**. This proves why the baseline model had poor accuracy on Apple Clang (~57%) and required the Week 3 regex normalization patch (`_normalize_clang_dialect`).
4. **Benchmark Tail Contamination:** Forensic provenance analysis identified that rows 67,137 to 67,209 (73 rows) were appended during initial repo setup by [`src/build_dataset_from_tests.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/build_dataset_from_tests.py). These rows overlap with the benchmark suite. Removing this 73-row tail is required to guarantee zero test leakage.

---

## 2. Dataset Structure & Duplicate Analysis

| Metric | Measured Value | Percentage of Dataset | Notes / Implications |
|---|---|---|---|
| **Total Rows** | **67,210** | 100.0% | Starting baseline dataset |
| **Unique Exact Messages** | 67,206 | 99.99% | 4 exact duplicate strings |
| **Exact Duplicate Rows** | 0 | 0.00% | No identical (message, category) pairs |
| **Conflicting Label Messages** | 4 | 0.01% | Same message assigned to conflicting categories |
| **Unique Normalized Templates** | **4,264** | **6.34%** | Canonicalized by replacing tokens & literals |
| **Near-Duplicate Rows** | **62,946** | **93.66%** | Structural templates repeated with varied variable names |
| **AST Node Field Populated** | **41** | **0.061%** | 99.94% of rows have `ast_node == ""` |

### Normalization Method:
The structural template canonicalization replaces quoted identifier tokens (`'...'`, `` `...` ``) with `<TOKEN>`, string literals with `<STR>`, numeric digits with `<NUM>`, and collapses whitespace. 

The fact that 67,210 examples collapse into just 4,264 structural templates indicates that the legacy dataset was heavily synthesized via regex generation rules, causing the model to overfit to template syntactic noise rather than semantic error structure.

---

## 3. Class Distribution & Imbalance Audit

| Category | Row Count | Percentage | Imbalance Relative to Max | Deterministic in Week 5+ Pipeline? |
|---|:---:|:---:|:---:|:---:|
| `other` | 24,997 | 37.19% | 1.0x (Baseline) | ML fallback category |
| `name_resolution` | 19,122 | 28.45% | 1.3x | Genuine ML category (enriched with Symbol Table) |
| `type_error` | 12,184 | 18.13% | 2.1x | Genuine ML category |
| `redefinition` | 4,641 | 6.91% | 5.4x | Genuine ML category |
| `syntax_error` | 4,114 | 6.12% | 6.1x | Partially overlapping with PDA bracket checker |
| `missing_include` | 1,595 | 2.37% | 15.7x | Genuine ML category |
| `access_error` | 512 | 0.76% | 48.8x | Genuine ML category (const assignment / visibility) |
| `return_type_error` | **44** | **0.07%** | **568.1x** | **Severely underrepresented (Critical Deficit)** |
| `Other` (typo capitalization) | 1 | 0.00% | 24,997.0x | Data formatting defect (single uppercase row) |
| `linker_error` | 0 | 0.00% | N/A | **Assigned deterministically via exit code / regex** |
| **Total** | **67,210** | **100.0%** | **Max Imbalance: 568.1x** | — |

### Key Observations:
1. **The `return_type_error` Starvation:** With only 44 examples out of 67,210, `return_type_error` represents less than 0.07% of the dataset. This severe starvation makes the logistic regression decision boundary for return type errors fragile.
2. **The `other` Oversaturation:** At 37.19%, `other` acts as an attractor category for ambiguous diagnostics, suppressing precision on low-frequency classes.
3. **Data Formatting Artifact:** Row index 67,163 contains `"category": "Other"` with a capitalized 'O', an unhandled class label anomaly.

---

## 4. Compiler Dialect Phrasing Split (GCC vs Clang)

We evaluated the diagnostic phrasing of all 67,210 messages using dialect-detection heuristics:
* **GCC Heuristics:** Match GCC signature phrasing (e.g. `was not declared in this scope`, `does not name a type`, `expected .* before .* token`, `cannot convert .* to .*`, `invalid conversion from`, `incompatible types in assignment`, `invalid type argument of unary`, `has no member named`, `no match for operator`, `expected primary-expression before`).
* **Clang Heuristics:** Match Clang signature phrasing (e.g. `use of undeclared identifier`, `cannot initialize (a variable of )?type`, `no viable conversion from`, `assigning to .* from incompatible type`, `indirection requires pointer operand`, `invalid operands to binary expression`, `no member named`, `expected ';' after`, `non-const lvalue reference`).

### Dialect Distribution:
```text
GCC-phrased diagnostics:     35,123  (52.26%)
Clang-phrased diagnostics:        63  ( 0.09%)   <-- SEVERE DEFICIT (< 0.1%)
Ambiguous / Shared phrases:    2,091  ( 3.11%)
Neutral / Generic syntax:     29,933  (44.54%)
```

### Forensic Finding:
The legacy dataset is overwhelmingly GCC-skewed. Only 63 rows (less than one in a thousand) feature native Clang diagnostic phrasing. This explains why the baseline model in Week 1 achieved only ~57% accuracy on macOS Apple Clang and required Week 3's `_normalize_clang_dialect()` regex translation layer as a temporary runtime bridge.

---

## 5. Identification of Deterministic Categories

Certain categories in the Compiler Error Explainer pipeline are now handled by deterministic rules rather than statistical NLP:

1. **Linker Errors (`linker_error`):**
   - Handled 100% deterministically by [`src/compiler_runner.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/compiler_runner.py) inspecting process exit codes and regex matching macOS `ld64` / GNU `ld` output (`Undefined symbols for architecture ...`).
   - The pristine training dataset contains **0 rows** of `linker_error`.
   - **Recommendation:** Do not add `linker_error` examples to the classifier; the classifier is bypassed for linker errors.

2. **Bracket & Delimiter Mismatches (`bracket_checker.py` PDA):**
   - In Week 5, we integrated a Pushdown Automaton ([`src/bracket_checker.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/bracket_checker.py)) tracking nested delimiters (`{`, `(`, `[`).
   - In the pristine training set, **779 rows** under `syntax_error` match delimiter patterns (`expected '}'`, `expected ')'`, `expected ']'`).
   - **Recommendation:** Retain general syntax error examples in the training set (e.g. missing semicolons, malformed statements), but do not waste model capacity attempting to disambiguate nested bracket depth that the PDA already proves mathematically.

3. **Security Findings (`security_analyzer.py`):**
   - Handled by the AST/regex security engine. Never classified by the NLP classifier.

---

## 6. Training vs. Benchmark Suite Non-Overlap Verification

To defend against data leakage and validate test independence, we executed an automated non-overlap audit between the 67,210 training messages and the benchmark suite (84 `.cpp` files, 84 `.json` metadata files).

### Audit Methodology:
1. **Benchmark Metadata Audit:** Scanned all 321 string fields across all 84 benchmark JSON metadata files against the training message set (`train_exact_set` and `train_norm_set`).
2. **Benchmark Compiler Output Audit:** Compiled all 84 benchmark C++ test cases with `clang++ -std=c++17 -fsyntax-only`, extracting 65 distinct diagnostic messages.

### Results:

#### 1. Benchmark JSON Metadata:
* **Exact string matches:** **0 (0.0%)**
* **Near-duplicate matches:** **0 (0.0%)**
* *Conclusion:* Zero leakage between benchmark ground-truth metadata and the training set.

#### 2. Compiled C++ Diagnostics:
* **Matches against CodeNet Core (Rows 0 to 67,136):**
  Only 6 generic language diagnostics matched ubiquitous C++ syntax patterns (e.g. `"expected ';' after expression"`, `"expression result unused [-Wunused-value]"`).
* **Matches against Appended Tail (Rows 67,137 to 67,209):**
  **32 exact diagnostic overlaps** were located exclusively in the 73 rows at the very end of `training_data_pristine_week1.json`.

### Contamination Provenance Uncovered:
During initial repository scaffolding prior to Week 1, [`src/build_dataset_from_tests.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/build_dataset_from_tests.py) compiled early test cases in `test_cases/` and `mini/` and appended 73 rows to `training_data.json`. When the benchmark suite was formalized in Week 2, those same test cases were adapted into `benchmark/` files (`nr01`, `rd01`, `te01`, etc.).

### Action Plan for Week 6 Rebuild:
1. **Purge the 73 Contaminated Tail Rows:** Truncate rows 67,137 to 67,209 to eliminate test case contamination and ensure 100% clean test independence.
2. **Augment with Native Clang Diagnostics:** Introduce balanced, high-quality Clang-phrased and GCC-phrased examples for underrepresented classes (`return_type_error`, `access_error`, `missing_include`).
3. **Populate Real AST Node Features:** Leverage Week 5's structural Clang AST parser to extract real AST context (`BinaryOperator`, `CXXRecordDecl`, `VarDecl`, `CallExpr`, etc.) for every training example, replacing the 99.94% blank `ast_node` fields.
4. **Class Rebalancing:** Downsample `other` and upsample minor classes to reduce the 568x imbalance ratio to under 10x.
