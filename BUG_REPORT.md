# BUG REPORT — Compiler Error Explainer
## Week 2 · Full-Pipeline Severity-Tiered Analysis

> **Date:** 2026-09-25  
> **Scope:** 78 benchmark files across 11 categories  
> **Rule:** No bug fixes this week — document only. Fixes start Week 3.

---

## Summary

| Severity | Count | Description |
|----------|-------|-------------|
| **P0** (Wrong/dangerous behavior) | 5 | Produces incorrect results, loses data, or creates security blind spots |
| **P1** (Feature doesn't work) | 8 | A declared feature is broken, unreachable, or produces no useful output |
| **P2** (Quality / false-positive) | 8 | Annoying or misleading but doesn't block core function |
| **Total** | **21** | |

| Phase | P0 | P1 | P2 | Total |
|-------|----|----|----|----|
| 1 — Compiling | 1 | 2 | 1 | 4 |
| 2 — Classifying | 1 | 1 | 1 | 3 |
| 3 — Explaining | 0 | 1 | 1 | 2 |
| 4 — Security Scanning | 1 | 2 | 2 | 5 |
| 5 — Auto-Healing | 1 | 1 | 0 | 2 |
| 6 — GUI | 0 | 1 | 2 | 3 |
| 7 — Offline Training | 1 | 0 | 1 | 2 |

---

## Phase 1 — Compiling (`compiler_runner.py`, `main.py`)

### Bug 1.1 · P0 · Warnings-only files reported as "error" status
**STATUS: RESOLVED** (Commit: [`684feae`](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py#L142))

**What happens:** When a file compiles successfully (exit code 0) but produces any
compiler output (warnings), `main.py` line 142 reports `"status": "error"` because
it checks `if visible_errors:` rather than checking for actual errors vs warnings.

**Evidence:**
- `benchmark/warnings_only/wo05_implicit_conversion.cpp` — compiles cleanly (exit 0),
  tool reports `status: "error"` with category "other"
- `benchmark/warnings_only/wo06_missing_return_warning.cpp` — same behavior
- `benchmark/security/sec01_cmd_inject.cpp`, `sec02_gets_overflow.cpp`,
  `sec04_format_string.cpp`, `sec13_decoy_filesystem.cpp` — all compile (exit 0) but
  get reported as errors due to compiler warnings or security-related stderr output
- Benchmark-wide: 14 of 78 files have incorrect status (82.1% accuracy)

**Where it lives:** [`src/main.py` line 142](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py#L142):
```python
"status": "error" if visible_errors else "success"
```

**Why it matters:** Any downstream system that trusts the `status` field will
incorrectly flag clean compiles as failures. CI pipelines, grade checks, and the
auto-healer will attempt to "fix" code that already works.

**Fix Applied (Week 3):** Changed condition in `src/main.py` to check `visible_error_count > 0` specifically for errors with severity `"error"`. All 6 files in `benchmark/warnings_only/` now report expected_status `success`.

---

### Bug 1.2 · P0 · Linker errors produce empty parse result → false "success"
**STATUS: RESOLVED** (Commit: [`c9bdc9e`](file:///Users/jaisinghsaini/TOACD/cd1/src/compiler_runner.py))

**What happens:** When a file has a linker error (undefined reference, missing main),
`parse_errors()` returns an empty list because the linker error format doesn't match
the regex in `error_parser.py`. With no parsed errors, `main.py` reports
`"status": "success"` — the opposite of reality.

**Evidence:**
- All 5 linker benchmark files (`lk01`–`lk05`) report `status: success` when they
  should report `status: error`
- Healer returns `no_errors_parsed` for all 5

**Where it lives:** [`src/error_parser.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/error_parser.py) —
linker errors have a different format (`ld: … undefined symbol: …`) that doesn't
match the `file:line:col: error:` regex pattern.

**Why it matters:** Linker errors are real errors — reporting them as success is
dangerous for any automated workflow. 5/78 (6.4%) of benchmark files are affected.

**Fix Applied (Week 3):** Compiler exit code is now checked in `compiler_runner.py`. When return code != 0 and no line:col error is parsed, linker diagnostics (macOS and GCC styles) are captured, symbolized, assigned category `linker_error` and `error_type: "error"`, properly propagated through `error_parser.py` and `error_explainer.py`. All 5 `benchmark/linker_errors/` files now report expected status `error` and category `linker_error`.

---

### Bug 1.3 · P1 · `missing_include` not detected for `<vector>`, `<string>` on Apple Clang

**What happens:** Files that use `vector` or `string` without their include compile
successfully on Apple Clang because these headers are transitively included by
`<iostream>`. The tool reports `status: success` — technically correct for Clang, but
the code is non-portable and would fail on GCC.

**Evidence:**
- `benchmark/missing_include/mi02_vector.cpp` — expected `error`, got `success`
- `benchmark/missing_include/mi03_string.cpp` — expected `error`, got `success`

**Where it lives:** Not strictly a code bug — it's a compiler dialect dependency. The
tool blindly trusts whatever compiler is installed.

**Why it matters:** Students using Clang won't discover their missing includes until
they submit to a GCC-based grading server.

**Fix direction:** Add a static `#include` checker that warns about common standard
library types used without their canonical headers, regardless of whether the compiler
accepts the code.

---

### Bug 1.4 · P2 · `compiler_runner.py` invokes `g++` without `-Wall`

**What happens:** `compiler_runner.py` calls `g++` without `-Wall`, while
`heal_loop.py` uses `-Wall`. This means warnings are inconsistent between the
analysis path and the healing path.

**Where it lives:** [`src/compiler_runner.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/compiler_runner.py)

**Fix direction:** Unify compiler flags across all invocation points.

---

## Phase 2 — Classifying (`error_classifier.py`, `error_normalizer.py`)

### Bug 2.1 · P0 · Classifier misclassifies `name_resolution` as `missing_include`
**STATUS: RESOLVED** (Commit: [`d84d2e8`](file:///Users/jaisinghsaini/TOACD/cd1/src/error_classifier.py))

**What happens:** When Clang reports `use of undeclared identifier 'y'`, the ML
classifier labels it `missing_include` instead of `name_resolution`. This is because
the training data is dominated by GCC-style messages like `'y' was not declared in
this scope`.

**Evidence:**
- `nr01_undeclared_var.cpp`: expected `name_resolution`, got `missing_include` (conf 0.457)
- `nr02_undeclared_result.cpp`: expected `name_resolution`, got `missing_include` (conf 0.492)
- `nr06_misspelled_ident.cpp`: expected `name_resolution`, got `missing_include` (conf 0.511)
- `nr08_wrong_scope.cpp`: expected `name_resolution`, got `missing_include` (conf 0.517)
- Overall classification accuracy: **28/48 (58.3%)**

**Where it lives:** [`src/error_classifier.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/error_classifier.py) —
the TF-IDF + LogisticRegression model, trained on GCC-biased data from `data/error_classifier.joblib`.

**Why it matters:** Wrong classification cascades to wrong explanations and wrong
auto-healer dispatch. A student with an undeclared variable gets told to add an
`#include` instead.

**Fix Applied (Week 3):** Added lightweight preprocessing `_normalize_clang_dialect(message)` in `src/error_classifier.py` that maps Apple Clang phrases (`use of undeclared identifier 'x'` → `'x' was not declared in this scope`, etc.) to canonical GCC equivalents prior to model inference. Benchmark classification accuracy jumped from 58.3% (28/48) to **87.5% (42/48)**.

---

### Bug 2.2 · P1 · Low confidence on Clang-phrased type errors falls through to "other"
**STATUS: RESOLVED** (Commit: [`d84d2e8`](file:///Users/jaisinghsaini/TOACD/cd1/src/error_classifier.py))

**What happens:** When Apple Clang reports type errors with different phrasing than
GCC (e.g., "cannot initialize a variable of type" vs "invalid conversion from"), the
classifier assigns category `other` with low confidence.

**Evidence:**
- `te01_int_to_charptr.cpp`: expected `type_error`, got `other` (conf 0.587)
- `te06_deref_non_pointer.cpp`: expected `type_error`, got `other` (conf 0.619)
- `te07_bool_to_struct.cpp`: expected `type_error`, got `other` (conf 0.570)

**Where it lives:** Same as 2.1 — the ML model hasn't seen enough Clang-style phrasing.

**Fix Applied (Week 3):** Resolved as part of Bug 2.1's Clang dialect normalization, which maps Clang's initialization type mismatches, non-pointer dereferences, and conversion failures to GCC canonical forms. All three test files (`te01`, `te06`, `te07`) now classify correctly as `type_error` with high confidence (>0.91).

---

### Bug 2.3 · P2 · Scikit-learn version mismatch warning

**What happens:** The saved model (`data/error_classifier.joblib`) was serialized
with scikit-learn 1.6.1, but the installed version is 1.9.1. This produces an
`InconsistentVersionWarning` on every single classification call.

**Where it lives:** `data/error_classifier.joblib`

**Fix direction:** Retrain and re-save the model with the current scikit-learn version.

---

## Phase 3 — Explaining (`error_explainer.py`, `common_errors.py`)

### Bug 3.1 · P1 · `common_errors.py` glossary only matches GCC-style messages

**What happens:** The `lookup_common_error()` function in `error_explainer.py` does
substring matching against `COMMON_ERRORS` entries. These entries use GCC-specific
phrasing (e.g., `"expected ';' before 'int'"`, `"was not declared in this scope"`).
On Apple Clang, the diagnostic text is different (e.g., `"expected ';' after
expression"`), so the glossary never matches and the system falls through to the
generic ML-based path every time.

**Evidence:**
- On all Clang-compiled benchmark files, explanations come from the generic
  `EXPLANATIONS[category]` templates, never from `COMMON_ERRORS`.
- The `common_errors.py` file contains 20+ entries, all phrased for GCC.

**Where it lives:** [`src/common_errors.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/common_errors.py) —
all 20+ message templates are GCC-only strings.

**Why it matters:** The glossary was built to give students highly specific
explanations (e.g., "Variable 'x' is being used before it has been declared"). On
Clang, they always get generic templates instead ("The compiler encountered an
identifier that has not been declared").

**Fix direction:** Add Clang-equivalent message patterns alongside each GCC entry, or
normalize messages to a canonical form before matching.

---

### Bug 3.2 · P2 · Explanations are never *wrong*, just generic

**What happens:** When a specific `COMMON_ERRORS` match fails, the explanation falls
back to the category-level template from `EXPLANATIONS`. These are accurate but
generic — they describe the *category* of error, not the specific error message.

**Evidence:** Every Clang-compiled benchmark file gets the same generic "what / why /
how" text for its category, regardless of the specific error. Two different
`syntax_error` files (missing semicolon vs. unmatched paren) get identical explanations.

**Where it lives:** [`src/error_explainer.py` line 96](file:///Users/jaisinghsaini/TOACD/cd1/src/error_explainer.py#L96) —
the `explain_category()` function uses `normalize_error(message)` for the "what" part
but the static template for "why" and "how".

**Fix direction:** Make the normalizer output richer, error-specific "how to fix"
suggestions, or expand the common_errors glossary significantly.

---

## Phase 4 — Security Scanning (`security_analyzer.py`)

> **Benchmark Security Reconciliation & Count Audit:**  
> Direct recount of `benchmark/security/` (16 total files):
> - **12 Vulnerable Files** (`expected_security_verdict: "vulnerable"`) covering **9 distinct CWEs**:
>   - **CWE-78** (Command Injection): 1 file (`sec01_cmd_inject.cpp`)
>   - **CWE-120** (Buffer Overflow): 2 variant files (`sec02_gets_overflow.cpp`, `sec03_strcpy_overflow.cpp`)
>   - **CWE-134** (Format String): 1 file (`sec04_format_string.cpp`)
>   - **CWE-190** (Integer Overflow): 1 file (`sec10_integer_overflow.cpp`)
>   - **CWE-401** (Memory Leak): 1 file (`sec12_memory_leak.cpp`)
>   - **CWE-415** (Double Free): 1 file (`sec06_double_free.cpp`)
>   - **CWE-416** (Use-After-Free): 1 file (`sec05_use_after_free.cpp`)
>   - **CWE-457** (Uninitialized Variable): 1 file (`sec11_uninit_use.cpp`)
>   - **CWE-476** (Null Pointer Dereference): 3 variant files (`sec07_null_deref_direct.cpp`, `sec08_null_deref_struct.cpp`, `sec09_null_deref_return.cpp`)
> - **4 Clean Decoy Files** (`expected_security_verdict: "clean"`):
>   - `sec13_decoy_filesystem.cpp` (decoy for CWE-78)
>   - `sec14_decoy_safe_printf.cpp` (decoy for CWE-134)
>   - `sec15_decoy_safe_alloc.cpp` (decoy for CWE-401)
>   - `sec16_decoy_safe_delete.cpp` (decoy for CWE-416)
>
> **Full-Benchmark Denominators Reconciled:**  
> - **Recall Denominator (15 vulnerable files):** The benchmark harness evaluates security across *all* 78 files. 12 files in `benchmark/security/` + 3 multi-error files with security flaws in `benchmark/multi_error/` (`me02` CWE-415, `me03` CWE-416, `me04` CWE-190) = **15 total vulnerable files** (7 TP / 15 = 46.7% recall).
> - **False-Positive Denominator (12 clean/decoy files):** Evaluated against the 8 files in `benchmark/clean/` + the 4 decoys in `benchmark/security/` = **12 clean/decoy files** (1 FP / 12 = 8.3% FP rate).
>
> ### 0%-Recall CWE Reclassification: Broken Detection Logic vs. Missing Detection Logic

Audit of all 0%-recall CWEs (190, 415, 457, 476) establishes a critical architectural distinction between **Broken Detection Logic** (existing detector code with contained defects) and **Missing Detection Logic** (complete absence of source-level analysis):

| CWE ID & Vulnerability Class | Detection State in `security_analyzer.py` | Benchmark Files Affected | Root Cause & Defect Description | Fix Complexity & Target Milestone |
|---|---|---|---|---|
| **CWE-190**<br>(Integer Overflow) | **Broken Detection Logic**<br>(Existing detector) | `sec10` (clean compile)<br>`me04` (ungated in W3) | Line 456 regex defect: wrongly requires `INT_MAX`/keywords and arithmetic operator on the *same line*, failing standard multi-line assignments (`int x = INT_MAX; x = x + 1;`). | **Contained Logic Fix (Week 4 Quick Win)**:<br>Relax regex / track variable assignment across lines. Does NOT require Week 7 dataflow engine. |
| **CWE-415**<br>(Double Free) | **Broken Detection Logic**<br>(Existing detector) | `sec06` (clean compile)<br>`me02` (ungated in W3) | Line 476 sequencing defect: dictionary write `freed_vars[name] = line_no` executes *before* checking `line_no != freed_line`, causing consecutive deletes to overwrite the tracker before double-free check runs. | **Contained Logic Fix (Week 4 Quick Win)**:<br>Reorder check before dictionary assignment. Does NOT require Week 7 dataflow engine. |
| **CWE-476**<br>(Null Pointer Deref) | **Missing Detection Logic**<br>(Zero source detector) | `sec07`, `sec08`, `sec09`<br>(all clean compile) | Scanner has zero source-level patterns or dataflow tracking for `nullptr` / `NULL` dereferences; diagnostic rule matches only compiler warnings that Apple Clang never emits. | **New Dataflow Engine (Week 7 Scope)**:<br>Requires pointer analysis and control-flow / dataflow tracking from scratch. |
| **CWE-457**<br>(Uninitialized Variable) | **Missing Detection Logic**<br>(Zero source detector) | `sec11`<br>(clean compile) | Scanner has zero source-level tracking for uninitialized reads; relies solely on compiler warnings not emitted on Apple Clang. | **New Dataflow Engine (Week 7 Scope)**:<br>Requires def-use chain / dataflow tracking from scratch. |

#### Architectural Takeaway for Planning
- **Week 4 Quick Wins:** Fix the 2 broken detectors (CWE-190, CWE-415). Both are localized logic/sequencing corrections within `security_analyzer.py` and do not require heavy AST/dataflow machinery.
- **Week 7 Scope:** Implement genuine dataflow and pointer-tracking engines for CWE-476 and CWE-457 from scratch.

### Bug 4.1 · P0 · Security scanner gated by compile errors
**STATUS: RESOLVED** (Commit: [`e119e12`](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py))  
*Note: Gating resolved in Week 3. False negatives on CWE-190/415 reclassified as Bug 4.2/4.3 (Week 4 quick wins); CWE-476/457 scheduled for Week 7 dataflow sprint.*

**What happens:** 
1. **Compile Gate Bug (Resolved in Week 3):** In earlier pipeline versions, files with compilation errors did not undergo independent security scanning.
2. **Missing Detector Logic (Week 4 Scope):** The static scanner has a `_DIAGNOSTIC_RULES` entry for
"null pointer dereference" that matches *compiler warnings*, but the scanner's
`_scan_source_findings()` function has no source-level pattern to detect
`int* p = nullptr; *p = 10;`. Apple Clang doesn't emit a "null pointer dereference"
warning at compile time, so the diagnostic rule never fires either.

**Evidence:**
- `sec07_null_deref_direct.cpp` — expected `vulnerable`, got `clean`
- `sec08_null_deref_struct.cpp` — expected `vulnerable`, got `clean`
- `sec09_null_deref_return.cpp` — expected `vulnerable`, got `clean`
- CWE-476 recall: **0/3 (0%)**

**Where it lives:** [`src/main.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py) (compile gate) and [`src/security_analyzer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py) (source detectors).

**Fix Applied (Week 3):** In `src/main.py`, decoupled the security scanner from compilation success/failure so that source code is always analyzed regardless of compiler errors. Explicitly confirmed that dedicated instances in `benchmark/security/` for CWE-190, 415, 457, and 476 miss detection independently due to absence of source-level detection rules, which will be implemented in Week 4.

---

### Bug 4.2 · P1 · Broken Detection Logic: Double-Free (CWE-415) dictionary sequencing defect
**STATUS: RESOLVED** (Week 4)

**What happens:** The scanner has existing detection logic for double-free using `freed_vars` tracking via `_DELETE_RE`. But in line 476, `freed_vars[delete_match.group(1)] = line_no` executes *before* the double-free check runs. On the second delete, this assignment immediately overwrites the tracked line number with the current line number, causing the subsequent check `if freed_name in freed_vars and line_no != freed_line` to evaluate to `line_no != line_no` (False), completely blinding the detector to double-frees.

**Evidence:**
- `sec06_double_free.cpp` — expected `vulnerable`, got `clean`
- `me02_redef_and_security.cpp` — expected `vulnerable`, got `clean` (ungated in Week 3, but fails due to this bug)
- CWE-415 recall: **0/2 (0%)**

**Where it lives:** [`src/security_analyzer.py` lines 474-486](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py#L474-L486)

**Fix Applied (Week 4):** Reordered the double-free check to run **before** updating `freed_vars`, so consecutive `delete p; delete p;` is no longer self-masked. Also added `free()` call tracking alongside `delete` for C-style double-free detection. Verified: sec06 and me02 now correctly report "Double Free" findings.

---

### Bug 4.3 · P1 · Broken Detection Logic: Integer Overflow (CWE-190) single-line regex defect
**STATUS: RESOLVED** (Week 4)

**What happens:** The scanner has existing detection logic for integer overflow (lines 456-465). However, the regex pattern requires both the sentinel keyword (`INT_MAX`, `SIZE_MAX`, `sizeof`, etc.) AND the arithmetic operator (`+`, `*`) on the *exact same line*. Standard real-world code (including `me04_name_and_overflow.cpp`: `int x = INT_MAX; x = x + 1;`) splits the declaration and the arithmetic across separate lines, causing the existing check to fail.

**Evidence:**
- `sec10_integer_overflow.cpp` — expected `vulnerable`, got `clean`
- `me04_name_and_overflow.cpp` — expected `vulnerable`, got `clean` (ungated in Week 3, but fails due to this bug)
- CWE-190 recall: **0/2 (0%)**

**Where it lives:** [`src/security_analyzer.py` lines 456-465](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py#L456-L465)

**Fix Applied (Week 4):** Added cross-line variable tracking via `overflow_risk_vars` dict. Variables assigned `INT_MAX`, `SIZE_MAX`, `UINT_MAX`, `LONG_MAX`, or `LLONG_MAX` are tracked, and arithmetic on those variables on subsequent lines now triggers the "Integer Overflow" finding. Verified: sec10 and me04 now correctly report findings.

---

### Bug 4.4 · P2 · False positive on safe `malloc`/`free` pattern

**What happens:** The scope-based memory leak detector flags `sec15_decoy_safe_alloc.cpp`
as "Potential Memory Leak" even though it contains a matching `free(p)` call. The
scope tracking counts `{` and `}` but the malloc and free happen in the same scope
(inside `main()`).

**Evidence:**
- `sec15_decoy_safe_alloc.cpp` — expected `clean`, got `vulnerable`
- FP rate on clean/decoy files: 1/12 (8.3%)

**Where it lives:** [`src/security_analyzer.py` lines 467-512](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py#L467-L512) —
the scope-stack logic may be miscounting braces around `if (!p) return 1;`.

**Fix direction:** Improve brace-counting to handle early-return guards, or track
free at the variable level rather than scope level.

---

### Bug 4.6 · P1 · CWE-369 (Divide By Zero) has no detector in the current pipeline
**STATUS: RESOLVED (Week 10)**

**What happens:** Genuine divide-by-zero code (such as `int b = 0; cout << a / b;` or `int result = dividend / divisor;` with `divisor = 0`) produces **zero findings** from `detect()`. The tool logs `0 total findings (0 errors, 0 warnings)` and terminates with `Clean compilation`. 

**Root Cause Analysis:**
1. **Senior Project Legacy Stubbed Out:** The original senior project's `heal_loop.py` contained a regex-based `_pre_scan()` function that detected literal division by zero (`/\s*0\b`) and zero-initialized divisor variables (`\bint\s+([A-Za-z_]\w*)\s*=\s*0\s*;` followed by `/\s*var\b`). During the Week 4 refactor to the modular tool architecture (`tools/understand.py`, `tools/detect.py`, `tools/repair.py`), `_pre_scan()` in `heal_loop.py` was replaced with an empty backward-compatibility stub (`def _pre_scan(source): return []`) and was never ported into `tools/detect.py` or `security_analyzer.py`.
2. **Missing Detector Rule in `security_analyzer.py`:** The active static security analyzer covers 9 vulnerability classes (CWE-78, 120, 134, 190, 401, 415, 416, 457, 476). It contains **zero AST visitors, regex rules, or diagnostic patterns for CWE-369 (Divide By Zero)**.
3. **Compiler Default Behavior:** Standard compilers (Apple Clang and GNU GCC) treat division by a zero-valued variable as runtime undefined behavior rather than emitting compile-time diagnostics under default flags. Consequently, `understand()` parses 0 compiler diagnostics and the file compiles cleanly with exit code 0.
4. **Dead Repair Handlers in `auto_healer.py`:** While `auto_healer.py` contains `fix_division_by_zero` and `inject_division_guard`, these handlers are only invoked if a division-by-zero diagnostic is supplied by upstream tools—which never occurs.

**Evidence:**
- `test_cases/mini/tc09_division_by_zero.cpp` — produces 0 diagnostics from compiler, 0 security findings from `security_analyzer.py`, and `Clean compilation` from `Planner`.
- Backend trace verification:
  ```
  [Step 1] Tool: UNDERSTAND -> 0 diagnostics parsed
  [Step 2] Tool: DETECT -> 0 total findings (0 errors, 0 warnings)
  [Step 3] Tool: PLANNER -> Clean compilation
  ```

**Where it lives:**
- [`src/security_analyzer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py): Lacks any CWE-369 detection logic in `analyze()` and `_DIAGNOSTIC_RULES`.
- [`src/heal_loop.py` line 78](file:///Users/jaisinghsaini/TOACD/cd1/src/heal_loop.py#L78): Legacy `_pre_scan()` function is an empty stub returning `[]`.
- [`src/tools/detect.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/tools/detect.py): Relies solely on compiler diagnostics and `security_analyzer.py`.

**Why it matters:** Divide-by-zero is a major software flaw (CWE-369) that causes immediate crashes (`SIGFPE`) at runtime. It represents a complete blind spot in the static analysis and self-healing pipeline.

**Fix Applied (Week 10):**
1. **AST-Based Detector (`_scan_divide_by_zero`):** Implemented structured AST visitor in [`src/security_analyzer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py) that traverses Clang JSON ASTs to inspect all division and remainder operators (`/`, `%`, `/=`, `%=`). Flags expressions where the divisor is either a literal 0 or a local variable provably initialized/assigned to 0 with no subsequent reassignment or mutation (`++`, `--`, etc.) before use.
2. **CWE Mapping & Diagnostic Rules:** Added canonical `"Divide By Zero": "CWE-369"` and `"Division By Zero": "CWE-369"` to `VULNERABILITY_CWE_MAP` and added compiler warning pattern matcher `division by zero|divide by zero|remainder by zero` to `_DIAGNOSTIC_RULES`.
3. **End-to-End Repair Activation:** Connected detection diagnostics to `auto_healer.py`'s `fix_division_by_zero` and `inject_division_guard`, tagging candidate patches with `safety_level="S2"`, `suggestion_only=True`.
4. **Benchmark Verification:** Added benchmark test cases [`benchmark/security/sec23_divide_by_zero_literal.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security/sec23_divide_by_zero_literal.cpp) (literal 0), [`benchmark/security/sec24_divide_by_zero_variable.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security/sec24_divide_by_zero_variable.cpp) (variable 0), and [`benchmark/security/sec25_decoy_safe_division.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security/sec25_decoy_safe_division.cpp) (safe decoy).
5. **Scope Disclosure:** Statically tracks literal zeroes and local variables within lexical function blocks. Path-dependent symbolic constraints, runtime user input (`std::cin >> x`), and complex inter-procedural dataflow across multiple compilation units remain beyond the scope of local AST analysis.

---

### Historical Record Correction · September 26, 2026: Status of the `filesystem()` Word-Boundary Issue

**Historical Context:** Prior to Week 1, initial project analysis identified that a harmless function named `filesystem()` was flagged as a forbidden command injection. In `WEEK2_REPORT.md`, the single decoy false positive was narratively labeled as `filesystem()`.

**Week 5 Benchmark Verification & True Status:**
1. **Security Scanner Result (CLEAN — Decoy Passes):** In `BENCHMARK_RESULTS_WEEK5.csv` (row 65) as well as Weeks 2, 3, and 4, `benchmark/security/sec13_decoy_filesystem.cpp` is recorded as:
   - `expected_security_verdict`: `clean`
   - `actual_security_verdict`: `clean`
   - `security_match`: `True`
   - `security_findings`: `[]` (0 findings)
   The security scanner ([`src/security_analyzer.py` line 355](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py#L355)) uses word boundary regex `r"\bsystem\s*\("`, so it does not flag `filesystem()` as a security vulnerability. The single measured security decoy false positive in Weeks 2–5 has always been `sec15_decoy_safe_alloc.cpp` (due to same-line `sizeof(int) * 10` arithmetic; Bug 4.4).
2. **Compiler Runner Status Mismatch (The Originating Bug):** In `BENCHMARK_RESULTS_WEEK5.csv`, `sec13_decoy_filesystem.cpp` failed its compilation status check:
   - `expected_status`: `success`
   - `actual_status`: `error` (`status_match`: `False`)
   - Compiler message: `"Security Error: Malicious command injection or forbidden system call detected."`
   This confirms where the original bug actually lived: [`src/compiler_runner.py` line 16](file:///Users/jaisinghsaini/TOACD/cd1/src/compiler_runner.py#L16) checks `dangerous_patterns.extend([r'system\s*\(', ...])` without a word boundary (`\b`), which treats `filesystem(...)` as an illegal system call and blocks compilation.
3. **Summary:** The `filesystem()` command-injection bug was never present in the security scanner (`security_analyzer.py`), but did exist in the compiler pre-execution gate (`compiler_runner.py`).
4. **Fix Applied (Pre-Week 6 Quick Win):** Updated `config.yaml` (`security.blocked_patterns`), `src/config_loader.py`, and `src/compiler_runner.py` with word boundary anchors `\b` (`r'\bsystem\s*\('`, `r'\bexec\s*\('`, `r'\bpopen\s*\('`, `r'\bfork\s*\('`, `r'\b__asm__\b'`, `r'\bshellcode\b'`). Verified against `sec13_decoy_filesystem.cpp`: `actual_status` transitioned from `error` to `success` and `status_match` flipped to `True`. Full benchmark re-run confirmed `sec13` was the ONLY file whose result changed, elevating overall benchmark status accuracy from 79/84 (94.0%) to 80/84 (95.2%). Added permanent regression test [`tests/test_sanitizer_word_boundary.py`](file:///Users/jaisinghsaini/TOACD/cd1/tests/test_sanitizer_word_boundary.py).

---

### Bug 4.5 · P2 · Missing Detection Logic: Uninitialized variable use (CWE-457) lacks source-level scanner
**CLASSIFICATION: MISSING DETECTION LOGIC (WEEK 7 SCOPE)**

**What happens:** The scanner has completely zero source-level tracking for uninitialized reads. It relies exclusively on compiler warnings (`may be used uninitialized`), which Apple Clang does not emit under default flags.

**Evidence:**
- `sec11_uninit_use.cpp` — expected `vulnerable`, got `clean`
- CWE-457 recall: **0/1 (0%)**

**Where it lives:** [`src/security_analyzer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py)

**Fix Scope:** Genuinely missing detection logic. Requires def-use chain and control-flow / dataflow analysis written from scratch. Correctly scoped to Week 7 dataflow engine.

---

### Bug 4.6 · P2 · Missing Detection Logic: Null pointer dereference (CWE-476) lacks source-level scanner
**CLASSIFICATION: MISSING DETECTION LOGIC (WEEK 7 SCOPE)**

**What happens:** The scanner has zero source-level patterns or dataflow tracking for `nullptr` / `NULL` dereferences (`*p`, `p->field`, etc.). It relies entirely on compiler warning diagnostics that Apple Clang never emits at compile time.

**Evidence:**
- `sec07_null_deref_direct.cpp` — expected `vulnerable`, got `clean`
- `sec08_null_deref_struct.cpp` — expected `vulnerable`, got `clean`
- `sec09_null_deref_return.cpp` — expected `vulnerable`, got `clean`
- CWE-476 recall: **0/3 (0%)**

**Where it lives:** [`src/security_analyzer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py)

**Fix Scope:** Genuinely missing detection logic. Requires pointer tracking and control-flow analysis written from scratch. Correctly scoped to Week 7 dataflow engine.

---

## Phase 5 — Auto-Healing (`auto_healer.py`, `heal_loop.py`)

### Bug 5.1 · P0 · Unsafe regex-based healing & CLI healing decoupling
**STATUS: RESOLVED** (Commit: [`08203f2`](file:///Users/jaisinghsaini/TOACD/cd1/src/auto_healer.py))

**What happens:** Heuristic keyword-typo healing previously performed blind line/regex substitutions with an edit distance limit of 2 and no boundary or string/comment checks. This caused corruption such as rewriting valid standard library identifier `cout` into keyword `const`. Furthermore, patches were written directly to disk without backups or verification, meaning a broken patch could worsen compilation without recovery.

**Evidence:**
- `cout` rewritten to `const` in undeclared variable scenarios
- Benchmark `name_resolution` files subject to keyword corruption

**Where it lives:** [`src/auto_healer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/auto_healer.py) (`_fix_keyword_typo`, `_CPP_KEYWORDS`) and [`src/heal_loop.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/heal_loop.py).

**Fix Applied (Week 3):**
1. Constrained `_CPP_KEYWORDS` to an explicit, fixed set of genuine C++ keywords.
2. Tightened edit distance bound strictly to distance 1 (distance 2 disallowed).
3. Added `_mask_comments_and_strings()` state machine so tokens inside string literals, char literals, and line/block comments are never matched or corrupted.
4. Excluded all `_VALID_KEYWORDS`, `_STD_SYMBOLS`, and `_SYMBOL_TO_HEADER` identifiers (such as `cout`, `cin`, `endl`, `vector`) from ever being considered keyword typos.
5. In `heal_loop.py`, added automated `.bak` file backup before saving any patch, and automatic undo/rollback to pre-patch state if post-patch compilation error count increases.

---

### Bug 5.2 · P1 · Healer success rate is 35.4% (17/48)

**What happens:** Of 48 error files in the benchmark, the auto-healer's outcomes are:
- **Compiled Clean (`compiled_clean`):** 17 (35.4% success rate)
- **Gave Up (`gave_up`):** 26 (54.2%) — exceeded retry limit or heuristic fix failed
- **No Errors Parsed (`no_errors_parsed`):** 5 (10.4%) — all 5 files in `benchmark/linker_errors/` (`lk01`–`lk05`)
- **Crashed (`crashed`):** 0 (0.0%)
*Total Accounted:* $17 + 26 + 5 + 0 = 48$ attempted error files.

> **Reconciliation Note on the 5 Missing Files:**  
> The 5 files not accounted for in "healed vs gave up" are the 5 linker error cases (`lk01`–`lk05`). Because linker diagnostic output (e.g. `Undefined symbols for architecture arm64: "_foo"`) has no `file:line:col: error:` pattern matching `error_parser.py`, `parse_errors()` returns an empty list (`[]`). With 0 parsed errors to act upon, the healer harness cannot generate AST/regex patch candidates, resulting in an immediate `no_errors_parsed` outcome rather than a retry failure.

**Evidence by category (All 48 files accounted for):**
| Category | Attempted | Compiled Clean | Gave Up | No Errors Parsed | Success Rate |
|---|:---:|:---:|:---:|:---:|:---:|
| syntax | 10 | 7 | 3 | 0 | 70.0% |
| name_resolution | 8 | 3 | 5 | 0 | 37.5% |
| type_errors | 8 | 1 | 7 | 0 | 12.5% |
| return_type | 4 | 1 | 3 | 0 | 25.0% |
| redefinition | 4 | 1 | 3 | 0 | 25.0% |
| missing_include | 4 | 3 | 1 | 0 | 75.0% |
| linker_errors | 5 | 0 | 0 | 5 (`no_errors_parsed`) | 0.0% |
| multi_error | 5 | 3 | 2 | 0 | 60.0% |
| **Total** | **48** | **17** | **26** | **5** | **35.4%** |

**Where it lives:** [`src/auto_healer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/auto_healer.py) —
the `attempt_fix()` dispatcher and individual fix functions.

**Why it matters:** The healer's core competence is syntax errors (70%), but it
struggles with type errors (13%), return type issues (25%), and entirely fails on
linker errors (0%).

**Fix direction:** Expand type_error handlers; add linker error awareness; improve
the redefinition handler to delete the duplicate.

---

### Bug 5.3 · P1 · Regression in `nr04_keyword_cosnt.cpp` healing undetected by verification
**STATUS: RESOLVED** (Item-3 Fallback Engine)

**Regression Note:** In Week 8, `benchmark/name_resolution/nr04_keyword_cosnt.cpp` regressed from `compiled_clean` (which had consistently held across Weeks 2–7) to `gave_up` when Tier 1 Clang Fix-It priority (`count`) preempted Tier 2 keyword typo matching (`const`) without candidate fallback, remaining undetected despite Week 8's "zero regressions" claim because Week 8's verification process validated isolated gate test cases rather than running a full benchmark CSV diff.

---

## Phase 6 — GUI (`gui.py`)

### Bug 6.1 · P1 · Energy dashboard shows fake/placeholder data

**What happens:** When CodeCarbon hasn't produced a usable sample (which is common on
macOS where RAPL is unavailable), the dashboard generates dummy sine-wave data with
random jitter to simulate live telemetry. This is misleading — users see
"professional-looking" power/carbon numbers that are completely fabricated.

**Evidence:** [`src/gui.py` lines 2630-2637](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py#L2630-L2637):
```python
base_mw = 900.0
wave = 120.0 * math.sin(t / 2.5) + 45.0 * math.sin(t / 0.9)
jitter = random.uniform(-18.0, 18.0)
power_mw = max(50.0, base_mw + wave + jitter)
```

**Where it lives:** [`src/gui.py` lines 2630-2637](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py#L2630-L2637)

**Why it matters:** In an academic context, presenting fabricated data as real
telemetry is academically dishonest. On macOS (the only platform we test on), this
fake data is *always* shown because RAPL is Linux-only.

**Fix direction:** Show an honest "Not available on this platform" message instead of
fake data, or actually integrate with macOS powermetrics.

---

### Bug 6.2 · P2 · Footer hardcodes "GCC 11.4" regardless of actual compiler

**What happens:** The status bar always shows `Compiler: GCC 11.4 | Language: C++17`
regardless of what compiler is actually installed. On this machine, the compiler is
Apple Clang 21.0.0.

**Evidence:** [`src/gui.py` line 2668](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py#L2668):
```python
text = f"Compiler: GCC 11.4 | Language: C++17 | ..."
```

**Where it lives:** [`src/gui.py` line 2668](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py#L2668)

**Fix direction:** Detect the actual compiler version via `g++ --version` and display it.

---

### Bug 6.3 · P2 · RAPL energy always shows "Unavailable" on macOS

**What happens:** The `_read_rapl_energy_joules()` function reads from
`/sys/class/powercap`, a Linux-only sysfs path. On macOS this path doesn't exist,
so RAPL always returns `None` and shows "Unavailable".

**Evidence:** [`src/gui.py` lines 56-73](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py#L56-L73) —
Linux-specific path hardcoded.

**Where it lives:** [`src/gui.py` line 57](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py#L57)

**Fix direction:** Use macOS `powermetrics` or Intel Power Gadget as platform
alternatives, or clearly label as "Linux only".

---

## Phase 7 — Offline Training Pipeline (`prepare_training_data.py`, `build_dataset_from_tests.py`, `dataset_logger.py`)

### Bug 7.1 · P1 · `dataset_logger.py` silently mutates `training_data.json` on every run
**STATUS: RESOLVED** (Commit: [`a5b50ae`](file:///Users/jaisinghsaini/TOACD/cd1/src/dataset_logger.py))

**What happens:** Every time `main.py` runs and processes an error, `log_example()`
in `dataset_logger.py` appends the classified error to `data/training_data.json`.
This means simply *running the tool for analysis* permanently modifies the training
dataset. Running the full benchmark added 12,342 bytes (12 KB) of new entries.

**Evidence:**
- Before benchmark: 14,719,358 bytes, MD5 `0239658b...`
- After benchmark: 14,731,700 bytes, MD5 `ec0e2de3...`
- **Modified by benchmark run: YES** (+12,342 bytes appended during evaluation)

> **Important Baseline & Backup Notice for Week 6:**  
> The untouched, pristine pre-benchmark baseline has been restored from [`legacy_artifacts/training_data_pristine_week1.json`](file:///Users/jaisinghsaini/TOACD/cd1/legacy_artifacts/training_data_pristine_week1.json) (14,719,358 bytes, MD5 `0239658bf3b6c91064e89dba5e954d30`).

**Where it lives:** [`src/dataset_logger.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/dataset_logger.py) and [`src/main.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/main.py).

**Fix Applied (Week 3):** Gated write-back in `dataset_logger.py` behind an explicit opt-in parameter `enabled: bool = False` and environment check `ENABLE_DATASET_LOGGING == "1"`. Added CLI flag `--log-training` (defaulting to False) to `src/main.py`. Verified with full benchmark run: `training_data.json` size remains exactly 14,719,358 bytes and MD5 `0239658bf3b6c91064e89dba5e954d30` (Safe, zero mutation).

---

### Bug 7.2 · P2 · `build_dataset_from_tests.py` labels are partially wrong

**What happens:** The `FILE_LABELS` dict in `build_dataset_from_tests.py` has
questionable labels:
- `wrong_main_signature.cpp` → `syntax_error` (should be `return_type_error`)
- `break_outside_loop.cpp` → `syntax_error` (arguable — could be `other`)
- `const_assignment.cpp` → `access_error` (correct)
- `null_dereference.cpp` → `other` (correct for compile-time, but misses the security angle)

**Where it lives:** [`src/build_dataset_from_tests.py` lines 25-49](file:///Users/jaisinghsaini/TOACD/cd1/src/build_dataset_from_tests.py#L25-L49)

**Fix direction:** Audit and correct all labels; use the new benchmark metadata as
ground truth.

---

## Appendix: Benchmark Aggregate Numbers

```
Status Accuracy:           64/78 (82.1%)
Classification Accuracy:   28/48 (58.3%)

Security Scanner Precision: 0.875  (7 TP, 1 FP)
Security Scanner Recall:    0.467  (7 TP, 8 FN)
FP Rate on clean/decoy:     8.3%   (1/12)

Per-CWE Recall:
  CWE-78  (Cmd Injection):    1/1  (100%)
  CWE-120 (Buffer Overflow):  2/2  (100%)
  CWE-134 (Format String):    1/1  (100%)
  CWE-190 (Int Overflow):     0/2  (0%)   ← BLIND
  CWE-401 (Memory Leak):      1/1  (100%)
  CWE-415 (Double Free):      0/2  (0%)   ← BLIND
  CWE-416 (Use After Free):   2/2  (100%)
  CWE-457 (Uninit Variable):  0/1  (0%)   ← BLIND
  CWE-476 (Null Deref):       0/3  (0%)   ← BLIND

Auto-Healer:
  Attempted: 48
  Success:   17 (35.4%)
  Gave Up:   26 (54.2%)
  No Parse:  5  (10.4%)
  Crashed:   0

Training Data Mutation: YES (12 KB added by benchmark run)
```
