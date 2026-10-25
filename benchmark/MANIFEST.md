# Benchmark Suite Canonical Manifest

**Version**: 1.1.0  
**Updated**: Week 8 (September 28, 2026)  
**Single Source of Truth**: All metrics and denominators reported in weekly milestone reports and benchmark runs are anchored in this manifest and its companion machine-readable file [`benchmark/manifest.json`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/manifest.json).

---

## 1. Canonical Denominators Summary (Measured Host Environment: Apple Clang / libc++)

| Metric | Measured Denominator (Apple Clang / libc++) | Definition / Eligibility Criteria |
| :--- | :---: | :--- |
| **Status Accuracy** | **97** | All 97 `.cpp` files in `benchmark/**` with companion `.json` metadata. |
| **Classification Accuracy** | **54** | Compiler error files with ground truth diagnostic category. On Apple Clang, 3 targets (`mi02`, `mi03`, `me03`) compile with 0 errors out of the box due to transitive `<vector>`/`<string>` inclusion via `<iostream>`, leaving 54 genuine error targets. |
| **Security Scanner** | **97** | Total files scanned: **17 vulnerable** (CWE ground truth) + **80 clean** (16 explicit decoy/clean + 64 other non-security benchmark files). |
| **Auto-Healer Success** | **53** | Files with starting compiler errors that genuinely require repair. On Apple Clang, `mi02`, `mi03`, and `me03` compile clean from the start, leaving 53 true repair targets. |
| **Repair Correctness** | **24** | Ground truth output-verified healed programs. Evaluates whether clean compilation preserved intended execution semantics against an oracle. On Apple Clang, 24 genuinely healed files are oracle-verified (excluding `mi02` and `mi03` where 0 repair patches were needed, plus 2 runtime exception files `me02` and `me07`). |

---

## 2. Category Breakdown

| Category Directory | File Count | Expected Status | Primary Evaluation Focus |
| :--- | :---: | :---: | :--- |
| `clean/` | 8 | `success` | Status accuracy & decoy security / false positive evaluation |
| `linker_errors/` | 5 | `error` | Linker error classification & explanation |
| `missing_include/` | 7 | `error` (some clang warnings) | Missing header classification & auto-include repair |
| `multi_error/` | 7 | `error` | Cascade grouping, multi-error classification & repair |
| `name_resolution/` | 8 | `error` | Undeclared identifiers, scoping, and typo healing |
| `optimization/` | 4 | `success` | AST dead code, redundancy, and modern idiom optimization |
| `redefinition/` | 4 | `error` | Duplicate definitions / symbol redefinition |
| `return_type/` | 4 | `error` / `success` (warning) | Return type errors & warnings |
| `security/` | 22 | `error` / `success` | CWE detectors: buffer overflow, UAF, double-free, format string, command injection, integer overflow, null deref, uninitialized var |
| `syntax/` | 14 | `error` | Semicolons, braces, brackets, template delimiters, control flow |
| `type_errors/` | 8 | `error` | Type mismatches, stream operators, pointer assignments |
| `warnings_only/` | 6 | `success` | Compiler warnings that compile cleanly (exit code 0) |
| **Total** | **97** | — | — |

---

## 3. Historical Denominator Evolution

| Milestone | Total Files | Status Acc. | Classification Acc. | Security Scanner (Vuln / Decoy) | Auto-Healer (Clean / Attempted) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Week 2** | 78 | 64/78 (82.1%) | 28/48 (58.3%) | — | — |
| **Week 3** | 78 | 73/78 (93.6%) | 42/48 (87.5%) | — | — |
| **Week 4** | 80 | 75/80 (93.8%) | 44/50 (88.0%) | 12/15 (80.0%) | — |
| **Week 5** | 84 | 79/84 (94.0%) | 47/54 (87.0%) | 15/15 (100.0%) | — |
| **Week 6 (Initial)** | 84 | 80/84 (95.2%) | 44/54 (81.5%) | 15/15 (100.0%) | 21/53 (39.6%) |
| **Week 6 (Final)** | 87 | 83/87 (95.4%) | 53/57 (93.0%) | 11/12 (91.7% P / 73.3% R) | 21/56 (37.5%) |
| **Week 7 (Canonical)** | **97** | **93/97 (95.9%)** | **53/57 (93.0%)** | **17/17 (100.0% P / 100.0% R)** | **25/56 (44.6%)** *(21/56 baseline)* |
| *(Week 7 pre-opt subset)* | 93 | 89/93 (95.7%) | 53/57 (93.0%) | 17/17 (100.0% P / 100.0% R) | 21/56 (37.5%) |
| **Week 8 (Canonical)** | **97** | **93/97 (95.9%)** | **53/57 (93.0%)** | **17/17 (100.0% P / 100.0% R)** | **26/55 (47.3%)** *(26/56 on Linux; 28/55 total clean)* |

---

## 4. Verification & Consistency Enforcement

1. **Automated Manifest Check**: `benchmark/run_benchmark.py` verifies at startup that the count of discovered test cases matches `manifest.json`.
2. **Explicit Denominator Printing**: Every benchmark run outputs the 4 canonical denominators directly in the summary header before printing percentages.
3. **No Unrecorded Additions**: Adding new benchmark test files requires committing the corresponding `.json` metadata and re-running the manifest validator.

---

## 5. Patch Counting Basis (Gate 2 vs Week 7 Reconciliations)

When evaluating repair patches across the 56 error targets (`expected_status == "error"`), patch counts differ depending on whether single-pass candidate generation, multi-pass attempts, or successful healing runs are measured:

- **26 Patches (Single-Pass Unique File Candidates)**: Out of 56 benchmark error files, exactly 26 unique files generate a candidate repair patch on the first healing attempt (`attempt=1`). The distribution is **12 S0 (Tier 1)** and **14 S1 (Tier 2)**. This 26-patch set represents the static single-pass patch distribution produced directly by `repair(file, diag)`.
- **29 Patch Operations (Multi-Pass Cumulative Patch Operations)**: When running the iterative multi-pass healer across all 56 error files (up to 10 attempts per target), 29 total patch generation operations are performed across all iterations (**14 S0** operations and **15 S1** operations).
- **Week 7 Comparison (15/28)**: Week 7 reported an auto-healer success rate of 21/56 (37.5%). Across those 21 successfully healed files, exactly **28 patch operations** were applied to reach 0 errors, consisting of **15 Tier 1 (S0)** patches and 13 Tier 2 (S1) patches (often summarized as "15/28 Tier 1 patches"). The 29th multi-pass patch operation occurred on a file that generated a patch during its loop but did not reach clean compilation.

---

## 6. Repair Correctness Oracle (Task 5)

Clean compilation is a necessary but insufficient condition for automated repair: a patch could compile cleanly while altering the runtime semantics of the program. To decouple "compiles clean" from "computes the correct result", ground truth `expected_output` (and `stdin` where input is required) has been added to the companion `.json` metadata of healed benchmark targets.

### Compilation Outcomes Breakdown

Under Apple Clang / macOS `libc++`, exactly 53 diagnostic targets genuinely fail compilation. Total clean compilation is **26 / 53 (49.1%)**, with **24 / 53 (45.3%)** cleanly healed (0 errors, 0 security findings) and **2 / 53 (3.8%)** cleanly healed with security findings (`me02`, `me07`).

> **Toolchain Sensitivity Note (Transitive Includes)**: On macOS with Apple Clang (`libc++`), `#include <iostream>` transitively includes both `<vector>` and `<string>`. As a result, three benchmark targets:
> 1. `benchmark/missing_include/mi02_vector.cpp`
> 2. `benchmark/missing_include/mi03_string.cpp`
> 3. `benchmark/multi_error/me03_missing_include_and_uaf.cpp`
> compile with **0 errors out of the box** before `repair()` is invoked. They represent missing-include scenarios under non-transitive library configurations, but are known no-ops on Apple Clang. On Apple Clang, zero patches are applied to them. Moving them to the already-compiling baseline adjusts the active repair denominator from 56 to 53 (and the classification denominator from 57 to 54).

### Canonical Denominator: Deterministic Targets Evaluated by Oracle

**Apple Clang Baseline**: **24 deterministic targets** (excluding `mi02` and `mi03` where 0 repair patches were needed, plus 2 non-deterministic / crash files `me02` and `me07`).

| Target File | Injected Fault | Repair Applied | Ground Truth `expected_output` |
| :--- | :--- | :--- | :--- |
| `mi01_iostream.cpp` | Missing `#include <iostream>` | Injected header | `"Hello\n"` |
| `mi04_map.cpp` | Missing `#include <map>` | Injected header | `"30\n"` |
| `mi05_vector_standalone.cpp` | Missing `#include <vector>` | Injected header | `""` (silent exit 0) |
| `mi06_algorithm_sort.cpp` | Missing `#include <algorithm>` | Injected header | `""` (silent exit 0) |
| `mi07_utility_pair.cpp` | Missing `#include <utility>` | Injected header | `""` (silent exit 0) |
| `me06_cascade_semicolons.cpp` | 2 missing semicolons | Appended `;` on lines 5 & 7 | `"30\n"` |
| `nr02_undeclared_result.cpp` | Undeclared `result` | Inferred `int result = a + b;` | `"Result: 8\n"` |
| `nr03_keyword_retrun.cpp` | Typo `retrun` | Keyword corrected to `return` | `"3 + 4 = 7\n"` |
| `nr04_keyword_cosnt.cpp` | Typo `cosnt` | Keyword corrected to `const` (via fallback) | `"5\n"` |
| `nr06_misspelled_ident.cpp` | Identifier typo `countr` | Corrected to `counter` | `"0\n"` |
| `nr07_missing_std_prefix.cpp` | Missing `std::` / namespace | Scoped std resolution | `"hello\n"` |
| `rd03_local_redef.cpp` | Redeclared `int x = 10;` | Replaced duplicate decl with assignment | `"10\n"` |
| `rt02_void_main.cpp` | Non-standard `void main()` | Declared return type fix `int main()` | `"Wrong main signature"` |
| `sx01_missing_semi_decl.cpp` | Missing semicolon on decl | Appended `;` | `"10\n"` |
| `sx02_missing_semi_multi.cpp` | Missing semicolon | Appended `;` | `"Sum = 30\n"` |
| `sx03_missing_brace.cpp` | Missing closing brace | Stack-guided brace insertion | `"Hello, Alice!\nHello, Stranger!\n"` |
| `sx04_missing_semi_string.cpp` | Missing semicolon | Appended `;` | `"Hello"` |
| `sx06_extra_semi_struct.cpp` | Missing semicolon after struct | Appended `;` | `""` (silent exit 0) |
| `sx07_unmatched_paren.cpp` | Unmatched paren | Balanced paren | `"7\n"` |
| `sx08_double_semi_func_scope.cpp` | Missing semicolon in function | Appended `;` | `"3\n"` |
| `sx11_nested_bracket_mismatch.cpp` | Missing brace in nested lambda | Inserted closing brace | `"inside block\n"` |
| `sx12_brackets_in_string.cpp` | Semicolon after string | Appended `;` | `"59"` |
| `sx13_deeply_nested_unclosed.cpp` | Missing brace in nested block | Inserted closing brace | `"deeply nested\n"` |
| `te05_wrong_stream_op.cpp` | Inverted `cin << age` | Inverted operator to `cin >> age` (stdin: `"25\n"`) | `"Enter your age: You are 25 years old.\n"` |

*(Note: `mi02_vector.cpp` and `mi03_string.cpp` are retained in `benchmark/missing_include/` for toolchains without transitive includes, but compile clean with 0 errors on Apple Clang and require 0 patches).*

### Excluded Targets with Security Findings (2 Healed Targets + 1 Already-Compiling Target)

Two healed targets compile clean but retain security findings that surfaced or persisted after healing:
1. `benchmark/multi_error/me02_redef_and_security.cpp`: Contains duplicate declaration (`int x = 10;`) and deliberate double-free vulnerability (`delete p; delete p;`). Redefinition heals cleanly via Tier 3 regex rule, but binary aborts at runtime (`returncode: -5` / SIGTRAP) due to memory safety enforcement in sandbox (CWE-415).
2. `benchmark/multi_error/me07_cascade_class_errors.cpp`: Struct semicolon heals cleanly via Tier 1 compiler fix-it, resolving downstream undeclared identifier, but uninitialized member reads (`Point pt; pt.x ...`) produce undefined/non-deterministic runtime values (CWE-457).

*Re-labeled Baseline Vulnerability (`me03`)*:
- `benchmark/multi_error/me03_missing_include_and_uaf.cpp`: Contains deliberate use-after-free (`delete p; std::cout << *p;` CWE-416). Because it compiles with 0 errors out of the box under Apple Clang (transitive include), no healing occurred. Its CWE-416 finding is re-labeled as **detected on an already-compiling file with a real vulnerability** rather than "surfaced after healing".

### Oracle Result Summary

| Metric | Measured Value (Apple Clang / libc++) |
| :--- | :---: |
| **Total Clean Compilation** | 26 / 53 (49.1%) |
| **Clean Security Healing** | 24 / 53 (45.3%) |
| **Clean with Security Findings** | 2 / 53 (3.8%) (`me02`, `me07`) |
| **Eligible for Correctness Oracle** | 24 / 24 |
| **Repair Correctness** | **24 / 24 (100.0%)** |


