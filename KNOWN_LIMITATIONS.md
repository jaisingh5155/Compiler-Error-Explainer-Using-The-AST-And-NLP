# Known Limitations & Honest Technical Disclosures

**Project**: Compiler Error Explainer & Verified Auto-Healer Using AST and NLP  
**Milestone**: Week 9 Comprehensive Audit  
**Purpose**: Complete, consolidated disclosure of technical boundaries, theoretical trade-offs, and toolchain constraints identified across Weeks 1 through 9.

---

## 1. Static Security Analysis Boundaries

### 1.1 Switch-Exhaustiveness Gap in Uninitialized Memory (CWE-457)
- **Constraint**: Static AST traversal tracks variable initialization along declared AST branches (if-else, while, for). In complex `switch` statements with enum values, if a variable is assigned within several `case` blocks but lacks a fallback `default:` block, static AST analysis without full inter-procedural path-sensitive symbolic execution cannot prove whether the switch conditions exhaust the enum domain at runtime.
- **Impact**: Code patterns where initialization occurs in exhaustive cases without an explicit `default` can yield low-confidence warnings or require conservative assumptions by the static scanner.
- **Mitigation**: The scanner flags uninitialized paths unless an unconditional `default:` assignment or pre-switch default initializer is explicitly present.

### 1.2 Lambda-Capture Variable Tracking
- **Constraint**: In modern C++ (C++11/14/17), variables captured by reference (`[&]`, `[&x]`) or value (`[=]`, `[x]`) within closures can decouple variable declaration from mutation. Static AST visitors that analyze lexical scopes independently may misidentify a captured variable as unread or uninitialized if the lambda invocation occurs asynchronously or inside a standard algorithm.
- **Impact**: Edge cases involving multi-threaded lambda invocation require AST parent-pointer resolution to prevent false-positive unused-variable warnings.
- **Mitigation**: The AST extractor resolves `LambdaExpr` capture lists and maps captures directly into the parent function's symbol table.

### 1.3 CWE-369 (Divide By Zero) AST Detection & Scope
- **Status (Week 10)**: **Partially Closed via AST Detection Rule**.
- **Implemented Scope**: `security_analyzer.py` incorporates an AST visitor (`_scan_divide_by_zero`) that evaluates binary arithmetic operators (`/`, `%`, `/=`, `%=`) against Clang AST nodes. The detector reliably identifies:
  1. **Literal Zero Divisors**: Direct integer literals evaluating to `0` (e.g. `x / 0`, `x % 0`).
  2. **Provably Zero Local Variables**: Variables initialized or assigned to `0` within the local lexical function scope with no intervening reassignment or mutation (`++`, `--`, compound assignment, address-of).
- **Honest Technical Boundaries & Unhandled Scope**:
  - **Inter-Procedural Dataflow**: Function parameter values passed from separate call sites or across translation units are not tracked.
  - **Dynamic Runtime Input**: Values derived from runtime external sources (e.g. `std::cin >> divisor; x / divisor;`) cannot be proven zero at compile time without symbolic execution.
  - **Complex Conditional Path Sensitivity**: Variables whose zero status depends on non-trivial branch conditions without direct constant assignment remain outside lexical AST scope.
- **Repair Behavior**: Findings trigger `fix_division_by_zero` / `inject_division_guard` in `auto_healer.py`, tagged as Safety Level **S2** (meaning-changing runtime control flow alteration) and enforced as **suggestion-only** (never auto-applied). Verified on [`sec23_divide_by_zero_literal.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security/sec23_divide_by_zero_literal.cpp), [`sec24_divide_by_zero_variable.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security/sec24_divide_by_zero_variable.cpp), and safe decoy [`sec25_decoy_safe_division.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security/sec25_decoy_safe_division.cpp).

---

## 2. Verification Gate Constraints

### 2.1 Gate 5 (Semantic Equivalence) Inapplicability to "Broken-Until-Fixed" Programs
- **Constraint**: Gate 5 is designed to prove that automated patches preserve program semantics by comparing pre-patch and post-patch execution outputs. However, for benchmark files with pre-existing compiler errors, **no pre-patch binary exists** because the code could not compile.
- **Impact**: Pure differential execution testing cannot be performed between pre-patch and post-patch binaries on syntax-broken files.
- **Mitigation**: We decoupled clean compilation from semantic correctness by introducing an independent **Ground-Truth Runtime Oracle** (`expected_output` and `stdin` metadata). Gate 5 evaluates the post-repair binary against this non-circular oracle, achieving 100% (24/24) runtime pass rate.

---

## 3. Toolchain & Platform Sensitivities

### 3.1 Transitive Header Includes under Apple Clang / LLVM `libc++`
- **Constraint**: Standard C++ libraries differ in internal header decomposition. On macOS with Apple Clang (`libc++`), `#include <iostream>` transitively pulls in stream buffer definitions that define `std::string` and `std::vector`. Under GNU `libstdc++` (Linux), this transitive chain does not exist.
- **Impact**: Files written to test missing `<vector>` or `<string>` headers (`mi02_vector.cpp`, `mi03_string.cpp`, `me03_missing_include_and_uaf.cpp`) compile with **0 errors out of the box** on macOS when `#include <iostream>` is present.
- **Mitigation**: Rather than mutating historical benchmarks (Option a), we adopted **Option (b)**: documenting platform reality, updating the benchmark metadata to match empirical toolchain outcomes, and verifying vector injection on Apple Clang using `mi05_vector_standalone.cpp` (which deliberately omits `<iostream>`).

### 3.2 Pre-Compilation Safety Sandbox vs Security Benchmarks (`sec01`)
- **Constraint**: To prevent untrusted C++ code from executing arbitrary shell commands during automated repair, `compiler_runner.py` enforces a proactive regex sandbox blocking `system()`, `exec()`, `popen()`, and `fork()`.
- **Impact**: `benchmark/security/sec01_cmd_inject.cpp` tests CWE-78 command injection using `system(cmd)`. Under default permissions, the security sandbox intercepts compilation before invoking Clang, reporting a synthetic security error (`status: "error"`) against an `expected_status: "success"` target.
- **Mitigation**: The environment flag `ALLOW_SYSTEM_CALLS=1` is provided to allow controlled compilation when evaluating security test cases.

### 3.3 GNU GCC Empirical Transferability & Dialect Gap (Empirical Verification)
- **Constraint**: The pipeline was historically tuned and measured on Apple Clang 21.0.0 (`clang-2100.3.34.2`). Full 97-file benchmark verification against GNU GCC 16.2.0 (`arm64-apple-darwin20.0.0-g++`) reveals exact boundaries between compiler-independent and compiler-sensitive components:
  - **100% Transferable (Compiler-Independent)**:
    - **Security Scanner**: 100% parity across all 97 benchmark files. Precision: 1.000, Recall: 1.000, False-Positive Rate: 0.0% (0/16 clean/decoy), 100% recall across all 9 CWE categories (CWE-78, 120, 134, 190, 401, 415, 416, 457, 476).
    - **Verification Gates 3 & 4**: AST invariants and structural diffs operate entirely on Python libclang ASTs and are invariant to compiler toolchains.
    - **Auto-Healer Stability**: 0 crashes across all 53 repair attempts on GNU GCC.
  - **Toolchain & Dialect Sensitive (Does NOT Transfer Fully)**:
    - **Status Accuracy**: 94/97 (96.9%) on GCC vs 96/97 (99.0%) on Apple Clang. The 2-file degradation is due to GNU `libstdc++` lacking Apple `libc++` transitive header inclusion for `<vector>` (`mi02_vector.cpp`, `me03_missing_include_and_uaf.cpp`).
    - **Classification Accuracy**: 42/54 (77.8%) on GCC vs 53/54 (98.1%) on Apple Clang (-20.3%). Dialect normalization patterns developed in Weeks 3/6 hold up on 75.0% of dialect cases (12/16) but fail on specific GNU GCC phrasing: `redeclaration of 'int x'` (`rd03`), `multiple definition of 'enum Color'` (`rd04`), `invalid conversion from 'const char*' to 'int'` (`rt01`), `return-statement with no value` (`rt04`), and `did you mean 'std::__1::cout'?` confusing the include classifier (`nr07`).
    - **Auto-Healer Success Rate**: 22/53 (41.5%) on GCC vs 26/53 (49.1%) on Apple Clang (-7.6%), directly resulting from downstream repair engines receiving misclassified category labels (`rd03`, `me02`) and GCC-specific semicolon cascade diagnostics (`me06`).

---

## 4. Unfixable Categories by Design

### 4.1 Linker Errors Across Compilation Units (`lk01`–`lk05`)
- **Constraint**: Linker errors (e.g. `undefined reference to symbol`, missing `main`, unresolved externals) occur when a symbol declaration lacks a corresponding definition in any linked object file.
- **Impact**: Because our auto-healer operates safely on single translation units, it cannot fabricate missing external library implementations or modify multi-file project link graphs.
- **Design Decision**: Linker errors are classified as **unfixable by design** in `auto_healer.py` (`UNFIXABLE_CATEGORIES`). The planner immediately halts repair attempts and surfaces actionable human advice rather than generating non-compiling speculative stubs.

### 4.2 Multi-Error Cascade Grouping vs Independent Syntax Errors
- **Constraint**: When a program contains both a severe syntax error (e.g. missing struct closing brace) and a downstream type error, compiler diagnostics often emit cascading errors that are artifacts of parser desynchronization.
- **Impact**: If an ML classifier evaluates each diagnostic in isolation, it risks classifying downstream phantom errors rather than the true root cause.
- **Mitigation**: The `root_cause_grouper` clusters diagnostics by AST line proximity and selects the highest-severity upstream representative, prioritizing syntax and declaration fixes over downstream type mismatches.
