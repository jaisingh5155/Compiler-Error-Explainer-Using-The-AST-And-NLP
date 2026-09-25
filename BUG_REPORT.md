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

**Fix direction:** Check `visible_error_count > 0` instead of `bool(visible_errors)`,
or better yet, use the compiler's exit code directly.

---

### Bug 1.2 · P1 · Linker errors produce empty parse result → false "success"

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

**Fix direction:** Add a secondary regex for linker error patterns and/or check g++
return code as a fallback even when no errors are parsed.

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

**Fix direction:** Retrain on a balanced dataset including Clang-style diagnostics;
or add Clang-specific regex fallbacks like the existing GCC-style ones in
`error_explainer.py` lines 181–189.

---

### Bug 2.2 · P1 · Low confidence on Clang-phrased type errors falls through to "other"

**What happens:** When Apple Clang reports type errors with different phrasing than
GCC (e.g., "cannot initialize a variable of type" vs "invalid conversion from"), the
classifier assigns category `other` with low confidence.

**Evidence:**
- `te01_int_to_charptr.cpp`: expected `type_error`, got `other` (conf 0.587)
- `te06_deref_non_pointer.cpp`: expected `type_error`, got `other` (conf 0.619)
- `te07_bool_to_struct.cpp`: expected `type_error`, got `other` (conf 0.570)

**Where it lives:** Same as 2.1 — the ML model hasn't seen enough Clang-style phrasing.

**Fix direction:** Add Clang-specific fallback regex patterns in `error_explainer.py`
for common Clang-style type error messages.

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
> ### 0%-Recall CWE Analysis: "Compile-Gate Bug" vs "No Detection Logic"
> Every 0%-recall CWE (190, 415, 457, 476) was audited to verify whether its instances in `benchmark/security/` (NOT `multi_error/`) also scored 0% independently:
>
> | CWE ID & Class | Instances in `benchmark/security/` (Clean Compile, Exit 0) | Instances in `benchmark/multi_error/` (Compile Error, Exit 1) | Independent Score in `security/` | Root Failure Category |
> |---|---|---|:---:|---|
> | **CWE-476**<br>(Null Dereference) | `sec07` (direct deref: `*p`),<br>`sec08` (struct member: `n->val`),<br>`sec09` (func return: `get_null()->val`)<br>*(All 3 exit 0 — not blocked by compiler)* | *None* | **0/3 (0%)** | **100% Missing Detection Logic** |
> | **CWE-415**<br>(Double Free) | `sec06_double_free.cpp`<br>*(Exits 0 — not blocked by compiler)* | `me02_redef_and_security.cpp`<br>*(Blocked by `error: redefinition of 'x'`)* | **0/1 (0%)** | **Defective Logic (sec06)** +<br>**Compile-Gated (me02)** |
> | **CWE-190**<br>(Integer Overflow) | `sec10_integer_overflow.cpp`<br>*(Exits 0 — not blocked by compiler)* | `me04_name_and_overflow.cpp`<br>*(Blocked by `error: use of undeclared identifier 'y'`)* | **0/1 (0%)** | **Inadequate Single-Line Regex (sec10)** +<br>**Compile-Gated (me04)** |
> | **CWE-457**<br>(Uninitialized Var) | `sec11_uninit_use.cpp`<br>*(Exits 0 — not blocked by compiler)* | *None* | **0/1 (0%)** | **100% Missing Detection Logic** |
>
> **Individual CWE Determinations:**
> - **CWE-476 (Null Dereference):** All 3 dedicated variants in `benchmark/security/` missed detection independently (0/3, 0%) despite clean compilation (exit 0) because **no detection logic exists for this pattern regardless of gating** (the tool has zero source-level AST/regex pointer trackers and relies solely on compiler warning diagnostics that Apple Clang never emits).
> - **CWE-190 (Integer Overflow):** `sec10` in `benchmark/security/` missed detection independently (0/1, 0%) despite clean compilation (exit 0) because **no detection logic exists for multi-line integer overflow patterns regardless of gating** (the line 456 regex requires `INT_MAX` and arithmetic operators on the same line), whereas `me04` in `multi_error/` was **blocked by the compile-gate (Bug 4.1)**.
> - **CWE-457 (Uninitialized Variable Use):** `sec11` in `benchmark/security/` missed detection independently (0/1, 0%) despite clean compilation (exit 0) because **no detection logic exists for this pattern regardless of gating** (the scanner completely lacks a source-level uninitialized read detector).
> - **CWE-415 (Double Free):** `sec06` in `benchmark/security/` missed detection independently (0/1, 0%) despite clean compilation (exit 0) because **no functional detection logic exists for consecutive deletes regardless of gating** (line 476 overwrites `freed_vars[name]` before checking `line_no != freed_line`, preventing double-delete matches, and zero tracking exists for `free()`), whereas `me02` in `multi_error/` was **blocked by the compile-gate (Bug 4.1)**.
> - **CWE-416 (Use-After-Free) Clarification:** CWE-416 scored 100% recall (2/2) because `sec05` compiled cleanly and was detected, while `me03` compiled cleanly due to `<iostream>` transitively including `<vector>` on Apple Clang; however, on true compile failures like legacy `test_cases/tc16.cpp` or `me02`, upstream compile errors halt the pipeline and completely conceal vulnerabilities, confirming that **Bug 4.1 (the compile-gate) is a real and separate architectural cause** from missing detector rules.
>
> **Implications for Week 4 Fix Strategy:**  
> Week 4 requires **both** fixes:
> 1. Fix the compile-gate architectural bug (Bug 4.1) so files with syntax/type errors still undergo AST/source security analysis.
> 2. Implement new and corrected source-level detection rules for CWE-476, CWE-415, CWE-190, and CWE-457.

### Bug 4.1 · P0 · Null pointer dereference completely undetected

**What happens:** The static scanner has a `_DIAGNOSTIC_RULES` entry for
"null pointer dereference" that matches *compiler warnings*, but the scanner's
`_scan_source_findings()` function has no source-level pattern to detect
`int* p = nullptr; *p = 10;`. Apple Clang doesn't emit a "null pointer dereference"
warning at compile time, so the diagnostic rule never fires either.

**Evidence:**
- `sec07_null_deref_direct.cpp` — expected `vulnerable`, got `clean`
- `sec08_null_deref_struct.cpp` — expected `vulnerable`, got `clean`
- `sec09_null_deref_return.cpp` — expected `vulnerable`, got `clean`
- CWE-476 recall: **0/3 (0%)**

**Where it lives:** [`src/security_analyzer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py) —
`_scan_source_findings()` has no `nullptr` → dereference dataflow tracking.

**Why it matters:** Null pointer dereference (CWE-476) is one of the most common
vulnerability classes. Missing all 3 test cases is a critical blind spot.

**Fix direction:** Add a source-level tracking system similar to `freed_vars` that
tracks pointers assigned `nullptr`/`NULL`/`0` and flags dereferences before a
non-null assignment.

---

### Bug 4.2 · P1 · Double-free not detected in isolated cases

**What happens:** The scanner uses `freed_vars` tracking via `_DELETE_RE` to detect
double-free. The regex `delete\s*(?:\[\])?\s*([A-Za-z_]\w*)\s*;` captures the
variable name and checks if it's deleted again on a later line. But in the simple case
`delete p; delete p;` on consecutive lines, the second delete matches as a new
"first delete" rather than being flagged.

**Evidence:**
- `sec06_double_free.cpp` — expected `vulnerable`, got `clean`
- `me02_redef_and_security.cpp` — expected `vulnerable`, got `clean` (double-free hidden behind redefinition error)
- CWE-415 recall: **0/2 (0%)**

**Where it lives:** [`src/security_analyzer.py` lines 474-486](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py#L474-L486) —
the `freed_vars[delete_match.group(1)] = line_no` overwrites on the second delete
before the double-free check runs.

**Fix direction:** Check for the double-free *before* updating `freed_vars`, or
restructure to check `if freed_name in freed_vars and line_no != freed_line` before
recording the new delete.

---

### Bug 4.3 · P1 · Integer overflow not detected without compiler-emitted keywords

**What happens:** The scanner's source-level integer overflow check
(lines 456-465) only fires when the code contains `INT_MAX`, `SIZE_MAX`, `sizeof`,
or words like `alloc`, `size`, `len`. A simple `int x = INT_MAX; x = x + 1;` should
trigger but doesn't because the pattern requires *both* an arithmetic expression
*and* one of those keywords on the same line.

**Evidence:**
- `sec10_integer_overflow.cpp` — expected `vulnerable`, got `clean`
- `me04_name_and_overflow.cpp` — expected `vulnerable`, got `clean`
- CWE-190 recall: **0/2 (0%)**

**Where it lives:** [`src/security_analyzer.py` lines 456-465](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py#L456-L465)

**Fix direction:** Track variables assigned `INT_MAX` or similar sentinel values and
flag arithmetic on them, even across separate lines.

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

### Bug 4.5 · P2 · Uninitialized variable use (CWE-457) not detected by source scan

**What happens:** The scanner has no source-level check for uninitialized variable
use. It only detects this via compiler warnings (`may be used uninitialized`), which
Apple Clang doesn't always emit for simple cases.

**Evidence:**
- `sec11_uninit_use.cpp` — expected `vulnerable`, got `clean`
- CWE-457 recall: **0/1 (0%)**

**Where it lives:** [`src/security_analyzer.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/security_analyzer.py) —
no dataflow tracking for uninitialized reads.

**Fix direction:** Add source-level tracking: when a variable is declared without
initialization, flag any use before an assignment.

---

## Phase 5 — Auto-Healing (`auto_healer.py`, `heal_loop.py`)

### Bug 5.1 · P0 · `heal_loop.py` requires PyQt6 — CLI-only healing impossible

**What happens:** `heal_loop.py` imports `from PyQt6.QtCore import QThread, pyqtSignal`
at module level and its `HealWorker` class inherits from `QThread`. This means the
auto-healer can only be used inside the GUI. `main.py` never calls the healing
pipeline, so CLI users have no access to auto-healing at all.

**Evidence:** `src/heal_loop.py` line 29: `from PyQt6.QtCore import QThread, pyqtSignal`

**Where it lives:** [`src/heal_loop.py` line 29](file:///Users/jaisinghsaini/TOACD/cd1/src/heal_loop.py#L29)

**Why it matters:** The auto-healer is a headline feature of the project. Making it
GUI-only eliminates it from batch processing, CI pipelines, and headless environments.

**Fix direction:** Decouple the healing logic from QThread. Create a pure-Python
`heal()` function callable from CLI, and have `HealWorker` call it internally.

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

### Bug 7.1 · P0 · `dataset_logger.py` silently mutates `training_data.json` on every run

**What happens:** Every time `main.py` runs and processes an error, `log_example()`
in `dataset_logger.py` appends the classified error to `data/training_data.json`.
This means simply *running the tool for analysis* permanently modifies the training
dataset. Running the full benchmark added 12,342 bytes (12 KB) of new entries.

**Evidence:**
- Before benchmark: 14,719,358 bytes, MD5 `0239658b...`
- After benchmark: 14,731,700 bytes, MD5 `ec0e2de3...`
- **Modified by benchmark run: YES** (+12,342 bytes appended during evaluation)

> **Important Baseline & Backup Notice for Week 6:**  
> `data/training_data.json` was **not** backed up to `legacy_artifacts/` prior to running the Week 2 benchmark. Consequently, the live file `data/training_data.json` is contaminated with benchmark run outputs and **is no longer a clean baseline for Week 6's retraining work**.  
> To preserve references:
> - The contaminated file has been backed up to [`legacy_artifacts/training_data_contaminated_week2.json`](file:///Users/jaisinghsaini/TOACD/cd1/legacy_artifacts/training_data_contaminated_week2.json).
> - The untouched, pristine pre-benchmark baseline has been retrieved from git commit history (`HEAD~1:data/training_data.json`, 14,719,358 bytes) and archived at [`legacy_artifacts/training_data_pristine_week1.json`](file:///Users/jaisinghsaini/TOACD/cd1/legacy_artifacts/training_data_pristine_week1.json) so clean retraining data is guaranteed available for Week 6.

**Where it lives:** [`src/dataset_logger.py` line 40-43](file:///Users/jaisinghsaini/TOACD/cd1/src/dataset_logger.py#L40-L43) —
unconditionally appends and writes back to `DATA_FILE`.

**Why it matters:** This creates a feedback loop: the tool's own (potentially wrong)
classifications become training data for future model versions. If the classifier
gets a category wrong, that wrong label gets logged and reinforces the mistake on
retrain. The data also grows unboundedly with every use.

**Fix direction:** Make logging opt-in via a flag (`--log-training`), or write to a
separate staging file that must be manually reviewed before merging into the training set.

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
