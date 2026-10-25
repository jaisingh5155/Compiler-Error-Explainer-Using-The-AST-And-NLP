# Diagnostic Selection Analysis & Regression Verification Report

**Date:** 2026-09-26  
**Project:** Compiler Error Explainer Using AST & NLP (Week 6 Audit)  
**Author:** Pair Programming Assistant (Antigravity)  
**Reference Artifacts:** [src/main.py](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py), [src/tools/detect.py](file:///Users/jaisinghsaini/TOACD/cd1/src/tools/detect.py), [src/root_cause_grouper.py](file:///Users/jaisinghsaini/TOACD/cd1/src/root_cause_grouper.py), [data/error_classifier_v2.joblib](file:///Users/jaisinghsaini/TOACD/cd1/data/error_classifier_v2.joblib)

---

## 1. Executive Summary

This report evaluates whether the three benchmark regressions observed in Week 6 (`mi01_iostream.cpp`, `rt03_missing_return.cpp`, and `sx10_break_outside_loop.cpp`) share a common pipeline root cause in [src/main.py](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py): specifically, evaluating only the **first diagnostic line** when line 1 is a non-meaningful warning/generic message rather than the true underlying error.

We conducted an empirical evaluation without retraining or modifying [data/error_classifier_v2.joblib](file:///Users/jaisinghsaini/TOACD/cd1/data/error_classifier_v2.joblib), comparing the raw compiler line order against individual diagnostic lines, severity-preference selection, and [src/tools/detect.py](file:///Users/jaisinghsaini/TOACD/cd1/src/tools/detect.py)'s severity/confidence ranking.

### Key Conclusions:
1. **The three files do NOT share a single unified pipeline cause:**
   - **`rt03` is a genuine pipeline selection bug:** Clang emitted a line 5 warning (`expression result unused`) before the line 6 warning (`non-void function does not return a value`). Feeding line 6 directly to the classifier **fully recovers 100% ground-truth accuracy (`return_type_error`, conf 0.950)** without touching the model.
   - **`mi01` exposed a historical classification mirage:** Clang emitted a line 1 warning (`using directive refers to implicitly-defined namespace 'std'`) before line 4 errors (`use of undeclared identifier 'cout'`). Feeding the line 4 error flips the prediction to `name_resolution` (conf 0.963), **not** `missing_include`. In Weeks 2–5, `mi01` only appeared to pass because legacy model v1 misclassified the line 1 *warning* as `missing_include` (conf 0.843) via keyword leakage on `std`.
   - **`sx10` is NOT a pipeline selection issue:** The compiler generates **exactly one diagnostic** (`'break' statement not in loop or switch statement`). The model predicts `other` (conf 0.937) because CodeNet labeled `break statement not within loop or switch` as `other` in [data/training_data_v2.json](file:///Users/jaisinghsaini/TOACD/cd1/data/training_data_v2.json), whereas the benchmark expects `syntax_error`.
2. **Week 4's root-cause grouping fails this case:** [src/root_cause_grouper.py](file:///Users/jaisinghsaini/TOACD/cd1/src/root_cause_grouper.py) sorts by `(file, line)` and designates the lowest line number in the 5-line window as the root cause, anchoring to the line 1 and line 5 warnings.
3. **Severity-only ranking is insufficient for warnings:** In Clang, `rt03`'s missing return diagnostic is a `warning`, not an `error`. An error-over-warning filter does not distinguish between line 5 and line 6.
4. **[detect()](file:///Users/jaisinghsaini/TOACD/cd1/src/tools/detect.py) ranking recovers `rt03`, `sx03`, and `sx11`:** Using [src/tools/detect.py](file:///Users/jaisinghsaini/TOACD/cd1/src/tools/detect.py)'s `(severity_rank, -confidence)` ranking in [src/main.py](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py) recovers `rt03`, `sx03`, and `sx11` without touching model weights.

---

## 2. Empirical Test Results

The table below shows the results of feeding the frozen `error_classifier_v2` model each individual diagnostic line vs the raw first diagnostic line emitted by the pipeline:

| Benchmark File | Total Diagnostics | Diag Selected by main.py (Raw Line 1) | Raw Prediction (Model v2) | Meaningful / Target Diagnostic Line | Prediction on Meaningful Line | Expected Benchmark Category | Ground Truth Match? |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- | :---: |
| **`rt03_missing_return.cpp`** | **2** | Line 5 (warning):<br>`expression result unused [-Wunused-value]` | `other`<br>(conf: 0.861) | Line 6 (warning):<br>`non-void function does not return a value [-Wreturn-type]` | **`return_type_error`**<br>(conf: 0.950) | `return_type_error` | **YES (RECOVERED)** |
| **`mi01_iostream.cpp`** | **3** | Line 1 (warning):<br>`using directive refers to implicitly-defined namespace 'std'` | `other`<br>(conf: 0.950) | Line 4 (error):<br>`use of undeclared identifier 'cout'` | **`name_resolution`**<br>(conf: 0.963) | `missing_include` | **NO** (Predicts `name_resolution`) |
| **`sx10_break_outside_loop.cpp`** | **1** | Line 4 (error):<br>`'break' statement not in loop or switch statement` | `other`<br>(conf: 0.937) | Line 4 (error):<br>`'break' statement not in loop or switch statement` *(Sole diagnostic)* | **`other`**<br>(conf: 0.937) | `syntax_error` | **NO** (Dataset label divergence) |

---

## 3. In-Depth Per-File Root Cause Breakdown

### 3.1 `benchmark/return_type/rt03_missing_return.cpp`

* **Source Code:**
  ```cpp
  int add(int a, int b) {
      a + b;
  }

  int main() {
      return 0;
  }
  ```
* **Compiler Output:**
  ```text
  benchmark/return_type/rt03_missing_return.cpp:5:7: warning: expression result unused [-Wunused-value]
      a + b;
      ~~^~~
  benchmark/return_type/rt03_missing_return.cpp:6:1: warning: non-void function does not return a value [-Wreturn-type]
  }
  ^
  ```
* **Analysis:**
  - In [src/main.py](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py#L132), `errors = model.diagnostics` leaves diagnostics ordered by compiler line order.
  - Line 5 (`expression result unused`) is classified as `other` (confidence 0.861).
  - Line 6 (`non-void function does not return a value`) is classified as `return_type_error` (confidence 0.950).
  - Feeding line 6 directly flips the result to **`return_type_error`**, exactly matching the benchmark expectation.
* **Finding:** Confirmed pipeline diagnostic ordering bug.

---

### 3.2 `benchmark/missing_include/mi01_iostream.cpp`

* **Source Code:**
  ```cpp
  using namespace std;

  int main() {
      cout << "Hello" << endl;
      return 0;
  }
  ```
* **Compiler Output:**
  ```text
  benchmark/missing_include/mi01_iostream.cpp:1:17: warning: using directive refers to implicitly-defined namespace 'std'
  using namespace std;
                  ^
  benchmark/missing_include/mi01_iostream.cpp:4:5: error: use of undeclared identifier 'cout'
      cout << "Hello" << endl;
      ^
  benchmark/missing_include/mi01_iostream.cpp:4:24: error: use of undeclared identifier 'endl'
      cout << "Hello" << endl;
                         ^
  ```
* **Analysis:**
  - Line 1 is a warning about `using namespace std;` before `<iostream>` has been loaded.
  - Line 4 has two errors for undeclared identifiers `cout` and `endl`.
  - Testing both models on these messages reveals the historical anomaly:
    - **Model v1 (Legacy):**
      - Line 1 (`using directive refers to implicitly-defined namespace 'std'`): $\rightarrow$ `missing_include` (conf: 0.843)
      - Line 4 (`use of undeclared identifier 'cout'`): $\rightarrow$ `name_resolution` (conf: 0.9998)
    - **Model v2 (Current):**
      - Line 1 (`using directive refers to implicitly-defined namespace 'std'`): $\rightarrow$ `other` (conf: 0.950)
      - Line 4 (`use of undeclared identifier 'cout'`): $\rightarrow$ `name_resolution` (conf: 0.963)
  - In Weeks 2–5, `mi01` only passed as `missing_include` because the legacy classifier suffered from severe keyword bias: the presence of tokens like `namespace` and `std` in the warning triggered a spurious `missing_include` prediction.
  - When evaluated on the actual error on line 4, both the legacy and new models correctly identify that `use of undeclared identifier` is a `name_resolution` issue.
* **Finding:** Selecting the meaningful error on line 4 changes the prediction to `name_resolution`, but does **not** produce `missing_include`.

---

### 3.3 `benchmark/syntax/sx10_break_outside_loop.cpp`

* **Source Code:**
  ```cpp
  #include <iostream>
  using namespace std;
  int main() {
      break;
      return 0;
  }
  ```
* **Compiler Output:**
  ```text
  benchmark/syntax/sx10_break_outside_loop.cpp:4:5: error: 'break' statement not in loop or switch statement
      break;
      ^
  ```
* **Analysis:**
  - The compiler emits **exactly one diagnostic**.
  - There is no preceding warning or generic line. Line 4 is the first, last, and only diagnostic produced.
  - Inspection of [data/training_data_v2.json](file:///Users/jaisinghsaini/TOACD/cd1/data/training_data_v2.json) (line 3865) shows:
    ```json
    {
      "message": "break statement not within loop or switch",
      "category": "other",
      "ast_node": "",
      "confidence": 1.0,
      "provenance": "codenet_dedup"
    }
    ```
  - In CodeNet's taxonomy, semantic control-flow constraint violations like `break` outside loops were categorized as `other`, whereas the benchmark ground truth labeled it `syntax_error`.
* **Finding:** This is an ontological taxonomy difference in the dataset, not a pipeline diagnostic selection issue.

---

## 4. Evaluation of Diagnostic Selection Strategies

We compared three potential pipeline mechanisms for selecting the diagnostic line sent to the classifier:

```
+---------------------------------------------------------------------------------------+
| Strategy 1: Prefer first ERROR over WARNING                                           |
|   - mi01: Picks line 4 (error) over line 1 (warning) -> name_resolution               |
|   - rt03: FAILS. Both line 5 and line 6 are WARNINGS in Clang; line 5 is still picked. |
+---------------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------------+
| Strategy 2: Week 4's Root-Cause Grouping (group_by_root_cause)                        |
|   - mi01: FAILS. Lines 1 and 4 are <= 5 lines apart; groups under line 1 (warning).   |
|   - rt03: FAILS. Lines 5 and 6 are <= 5 lines apart; groups under line 5 (warning).   |
+---------------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------------+
| Strategy 3: detect() Severity Rank + Confidence Rank (RECOMMENDED)                    |
|   - Sort key: (_severity_rank(d), -d.confidence)                                      |
|   - mi01: Line 4 error (Rank 0) outranks line 1 warning (Rank 2) -> name_resolution   |
|   - rt03: Line 6 (0.950 conf) outranks line 5 (0.861 conf) -> RECOVERS return_type   |
|   - sx03 & sx11: expected '}' (0.944 conf) outranks unparsed body -> RECOVERS syntax  |
+---------------------------------------------------------------------------------------+
```

### 4.1 Strategy 1: Prefer `error` over `warning`
* In `mi01`, the warning is line 1 and the error is line 4. Prioritizing errors selects line 4.
* In `rt03`, **both** diagnostics are emitted as `warning` by Clang (standard C++ allows non-void functions without returns unless `-Werror` is specified). A severity filter does not break ties between warnings, leaving line 5 in place.

### 4.2 Strategy 2: Week 4's Root-Cause Grouping ([src/root_cause_grouper.py](file:///Users/jaisinghsaini/TOACD/cd1/src/root_cause_grouper.py))
* `group_by_root_cause()` sorts diagnostics by `(file, line)` and assigns `root_cause_id` to the first diagnostic within a 5-line window:
  - `mi01`: Line 1 and line 4 are within 5 lines $\rightarrow$ Group ID is `rc-mi01:1` (the warning).
  - `rt03`: Line 5 and line 6 are within 5 lines $\rightarrow$ Group ID is `rc-rt03:5` (the unused expression warning).
* Consequently, relying on Week 4's root-cause grouping systematically selects the earlier non-meaningful warning.

### 4.3 Strategy 3: [detect()](file:///Users/jaisinghsaini/TOACD/cd1/src/tools/detect.py) Severity Rank + Confidence Sort
* In [src/tools/detect.py](file:///Users/jaisinghsaini/TOACD/cd1/src/tools/detect.py#L147):
  ```python
  merged.sort(key=lambda d: (_severity_rank(d), -d.confidence))
  ```
* In [src/main.py](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py#L120-L132), `detect(model)` is executed, but [main.py](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py#L132) discards the ranked list:
  ```python
  model = understand(...)
  all_findings = detect(model)
  ...
  errors = model.diagnostics  # Discards detect() ranking!
  ```
* If [src/main.py](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py) uses `all_findings` (filtered to compiler diagnostics `[d for d in all_findings if d.kind in ("error", "warning", "linker_error")]`):
  - **`rt03` recovers 100%:** Line 6 (`return_type_error`, conf 0.950) outranks Line 5 (`other`, conf 0.861).
  - **`sx03` & `sx11` recover 100%:** Line 20/16 `expected '}'` (`syntax_error`, conf 0.944) outranks `function definition is not allowed here` (`other`, conf 0.779).
  - **Trade-off:** In cascade errors like `me07_cascade_class_errors.cpp`, a high-confidence cascade diagnostic (e.g. `use of undeclared identifier 'y'`, conf 0.961) can outrank an earlier root syntax error (`expected ';'`, conf 0.949).

---

## 5. Architectural Recommendations

1. **Keep Model Frozen:** Do not retrain or alter [data/error_classifier_v2.joblib](file:///Users/jaisinghsaini/TOACD/cd1/data/error_classifier_v2.joblib).
2. **Harmonize `main.py` with `detect()`:** Update [src/main.py](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py) so that `visible_errors` derives from [detect()](file:///Users/jaisinghsaini/TOACD/cd1/src/tools/detect.py)'s ranked compiler findings rather than raw `model.diagnostics`.
3. **Refine Intra-Group Ranking in `root_cause_grouper.py`:** Update the root-cause grouper so that within a cascade window, it does not default blindly to the lowest line number if an earlier diagnostic is a low-confidence generic warning and a later diagnostic is an error or specific warning.
4. **Update Historical Documentation:** Acknowledge in project reports that `mi01` passing in Weeks 2–5 was a false-positive correlation on a compiler warning, and that its true Clang representation without headers is `name_resolution`.
