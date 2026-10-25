# Week 5 Technical Report: Structural Clang JSON AST, Formal Automata (DFA & PDA), Scoped Symbol Table, and Reconciliation

**Coursework Project:** Compiler Error Explainer & Auto-Healer (Week 5 of 10)  
**Date:** September 26, 2026  
**Status:** All Week 5 Milestones Completed. 43/43 Regression Tests Passing. 0 Regressions across Benchmark.

---

## 1. Executive Summary & Week 5 Deliverables

During Week 5, we transitioned from heuristic/regex-based text parsing to formal structural program analysis and automata-theoretic foundations:

1. **Step 0 Reconciliation:** Definitively resolved the auto-healer denominator discrepancy (0a), verified the root cause of the `sec15` decoy false positive (0b), and eliminated duplication between CLI and GUI heal loops by refactoring `src/heal_loop.py` to directly drive `src/planner.py` (0c).
2. **Structural Clang JSON AST (`src/ast_parser.py`):** Replaced text scraping with `clang++ -Xclang -ast-dump=json -fsyntax-only`, filtering standard library/system header expansion to isolate user AST trees with exact source ranges `[begin_line:begin_col, end_line:end_col]` and innermost node containment mapping.
3. **Scoped Symbol Table (`src/symbol_table.py`):** Implemented a hierarchical symbol table tracking global, function, and block scopes, identifier types, declaration coordinates, and initialization state (`has_initializer`). Wired into `src/tools/detect.py` to enrich `name_resolution` diagnostics with Levenshtein-distance "did you mean" suggestions.
4. **Formal DFA Tokenizer (`src/lexer.py`):** Built a 6-state Deterministic Finite Automaton (`CODE`, `LINE_COMMENT`, `BLOCK_COMMENT`, `STRING`, `CHAR_LITERAL`, `RAW_STRING`). Replaced ad hoc string/comment masking across `src/auto_healer.py` and `src/security_analyzer.py` with this single shared module.
5. **Formal PDA Bracket Checker (`src/bracket_checker.py`):** Built a Pushdown Automaton tracking `{`, `(`, `[` across code streams (ignoring literals/comments via DFA lexer), with precise reporting of unclosed openers and mismatched closing delimiters. Added 4 new syntax benchmark test cases (`sx11`-`sx14`).
6. **Verification & Benchmark Integrity:**
   - 43/43 automated tests passing (`pytest tests/`).
   - 84 total benchmark files evaluated.
   - **Exact ZERO regressions** across all 80 original Week 4 benchmark files.

---

## 2. Step 0: Week 4 Reconciliation Outcomes

### 0a. Auto-Healer Denominator Mismatch Reconciled
- **The Issue:** Week 4 added two multi-error cascade test cases (`me06_cascade_semicolons` and `me07_cascade_class_errors`). Classification evaluated 50 files with expected error categories, but auto-healer reported an attempted count of 49 files.
- **Root Cause:** In Week 4's evaluation loop, `if exp_status == "error": heal_rows.append(...)` was used. Of the 50 files with an expected error category, 49 have `expected_status == "error"`, while 1 file (`rt03_missing_return.cpp`) has `expected_status == "warning"` with expected category `return_type_error`. Therefore, `rt03` was excluded from the 49-file healer denominator. Both `me06` and `me07` were in fact included and cleanly healed.
- **Reconciled Full Breakdown (50 Category Files):**
  - **Cleanly Healed:** 19 files (38.0%)
  - **Gave Up (no fixable target / partial):** 26 files (52.0%)
  - **Unparsed / Linker Errors:** 5 files (`lk01`–`lk05`) (10.0%)
  - **Crashed:** 0 files (0.0%)
  - **Sum:** 19 + 26 + 5 + 0 = 50 files (100.0%).
- If restricted strictly to `expected_status == "error"`: 18 clean / 49 attempted (36.7%). Both accounting methods sum exactly with zero discrepancies.

### 0b. Security Decoy False-Positive Identity (`sec15`)
- **The Issue:** `sec15_decoy_safe_alloc.cpp` was flagged as vulnerable in Week 4.
- **Investigation:** We investigated whether this was the earlier `filesystem()` command injection false positive (which was `sec13_decoy_filesystem.cpp`) or a new regression from Week 4's CWE-190 `overflow_risk_vars` logic.
- **Finding:** In `sec15_decoy_safe_alloc.cpp`, line 8 contains `char* buf = (char*)malloc(sizeof(int) * 10);`. The alert is triggered by rule `RULE_MALLOC_OVERFLOW` in `src/security_analyzer.py` via `_MALLOC_OVERFLOW_RE = re.compile(r"\b(?:malloc|calloc)\s*\([^)]*[\*\+][^)]*\)")`, which flags any arithmetic inside `malloc()`. This rule was present since Week 2.
- **Verdict:** It is neither a renumbered `filesystem()` issue nor caused by CWE-190 `overflow_risk_vars`. It is an existing naive rule matching multiplication by a constant `10`. Deferred to Week 7/8 security rule refinement (since `sizeof(T) * CONST` is safe, whereas `sizeof(T) * variable` is overflow-sensitive).

### 0c. GUI/CLI Heal-Path Duplication Eliminated
- **The Issue:** `gui.py` executed heal cycles via `src/heal_loop.py`, while CLI executed `src/main.py --heal` via `src/planner.py` (`Planner.run()`).
- **Resolution:** Refactored `src/heal_loop.py` to become a thin adapter around `Planner.run()`. `HealLoop` now instantiates `Planner(max_iterations=max_attempts)` and delegates directly to `planner.run()`.
- **Parity Test:** Added `TestPlannerGuiParity::test_planner_gui_identical_behavior` in `tests/week4_verification/test_week4.py`, asserting that running both paths on identical files produces byte-for-byte identical patches, identical stop conditions, and identical step traces.

---

## 3. Step 1: Real Clang JSON AST Extraction & Containment Mapping

### Architectural Design (`src/ast_parser.py`)
Rather than scraping unstructured stdout from `clang -Xclang -ast-dump`, `src/ast_parser.py` executes:
```bash
clang++ -Xclang -ast-dump=json -fsyntax-only <file>
```
Even when syntax errors occur (return code 1), Clang emits valid JSON representing the partial AST on stdout.

#### 1. System Header Filtering
Headers like `<iostream>` and `<string>` expand into 1,000+ template declarations. `_is_user_top_node()` filters top-level nodes in `inner`:
- Rejects any node with `"includedFrom"` in `loc` or `range.begin`.
- Rejects paths starting with `/Applications/`, `/usr/`, `/Library/`, or `<`.
- Rejects implicit compiler declarations (`isImplicit: true`).
- Matches nodes referencing the target file name or relative path.

#### 2. Source Range Propagation
Clang compacts JSON by omitting line numbers when they match `loc` or parent nodes. `_build_ast_node()` recursively propagates `parent_file` and `parent_line`, computing absolute coordinates:
$$\text{Range} = [\text{begin\_line} : \text{begin\_col}, \; \text{end\_line} : \text{end\_col}]$$

#### 3. Innermost Containment Mapping
For each diagnostic $(L_{\text{diag}}, C_{\text{diag}})$, `find_enclosing_ast_node()` traverses the hierarchy to find the deepest node where:
$$(L_{\text{diag}} > L_{\text{begin}} \lor (L_{\text{diag}} = L_{\text{begin}} \land C_{\text{diag}} \ge C_{\text{begin}})) \land (L_{\text{diag}} < L_{\text{end}} \lor (L_{\text{diag}} = L_{\text{end}} \land C_{\text{diag}} \le C_{\text{end}}))$$
If strict containment finds no node (e.g. clang error points to EOF or trailing semicolon), relaxed line containment is evaluated, and `diag.ast_fallback` is set to `True`.

### AST Match Rate Metrics
Evaluated across all 84 benchmark files:
- **Files with Diagnostics:** 57
- **Files with Real AST Match:** 48 / 57 (**84.2%**)
- **Files with Fallback:** 9 / 57 (15.8% — 5 of which are linker errors with no AST)
- **Compiler Diagnostic AST Match Rate:** 60 / 64 (**93.8%** of compiler errors mapped directly to exact AST nodes)

### Spot-Check Validation (5 Representative Files)
| File | Diagnostic Message | Innermost AST Node | Node Summary | Fallback? |
|---|---|---|---|---|
| [`te01_int_to_charptr.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/type_errors/te01_int_to_charptr.cpp) | cannot initialize a variable of type 'char *' with 'int' | `VarDecl` | `VarDecl p :char *` | `False` |
| [`te02_int_plus_string.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/type_errors/te02_int_plus_string.cpp) | invalid operands to binary expression ('int' and 'string') | `RecoveryExpr` | `RecoveryExpr :<dependent type>` | `False` |
| [`te03_void_to_int.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/type_errors/te03_void_to_int.cpp) | cannot initialize a variable of type 'int' with 'void' | `VarDecl` | `VarDecl x :int` | `False` |
| [`sx01_missing_semi_decl.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/syntax/sx01_missing_semi_decl.cpp) | expected ';' at end of declaration | `DeclStmt` | `DeclStmt` | `False` |
| [`nr06_misspelled_ident.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/name_resolution/nr06_misspelled_ident.cpp) | use of undeclared identifier 'countr' | `CompoundStmt` | `CompoundStmt` | `False` |

---

## 4. Step 2: Scoped Symbol Table & "Did You Mean" Suggestions

### Symbol Table Architecture (`src/symbol_table.py`)
A hierarchical tree of `Scope` objects:
- **Global Scope:** Module top-level declarations, classes, and global variables.
- **Function Scope:** Functions and methods (`FunctionDecl`), registering parameters (`ParmVarDecl`).
- **Block Scope:** Compound statements (`CompoundStmt`), loops, and conditionals.

#### Symbol Metadata:
```python
@dataclass
class Symbol:
    name: str
    type_name: str
    line: int
    col: int
    kind: str            # 'variable', 'parameter', 'function'
    has_initializer: bool # True if initialized at declaration
    scope_name: str
```

### Levenshtein Distance "Did You Mean" Enrichment
In `src/tools/detect.py`, when a diagnostic exhibits `category == "name_resolution"` or references an undeclared symbol:
1. The undeclared identifier is extracted via regex.
2. The active scope at $(L_{\text{diag}}, C_{\text{diag}})$ is queried.
3. Candidate symbols in visible scope are evaluated using dynamic programming Levenshtein distance:
$$d(s_1, s_2) \le 2$$
4. The closest match is attached to `diag.did_you_mean`, and `diag.suggestion` is enriched.

### Examples Produced on Benchmark:
- `nr06_misspelled_ident.cpp`: Undeclared `countr` $\rightarrow$ `did_you_mean = "counter"`  
  *Suggestion:* `Did you mean 'counter'? (Declare the identifier before use or add the missing #include.)`
- `nr08_wrong_scope.cpp`: Variable `temp` declared inside `for` loop body at line 5 is queried outside at line 7:
  `sym_tab.is_declared("temp", line=5, col=10)` $\rightarrow$ `True`  
  `sym_tab.is_declared("temp", line=7, col=5)` $\rightarrow$ `False` (correctly detects scope exit).

---

## 5. Step 3: Formal DFA Tokenizer (`src/lexer.py`)

### DFA State Transition Specification

Let the DFA be $M = (Q, \Sigma, \delta, q_0, F)$:
- **States:** $Q = \{\text{CODE}, \text{LINE\_COMMENT}, \text{BLOCK\_COMMENT}, \text{STRING}, \text{CHAR\_LITERAL}, \text{RAW\_STRING}\}$
- **Initial State:** $q_0 = \text{CODE}$
- **Accepting States:** $F = Q$ (every completed token emission yields an accepting boundary; at EOF, $q_0$ is the valid terminal state).

### Transition Table

| Current State | Input / Event | Next State | Action / Output |
|---|---|---|---|
| **CODE** | `//` | `LINE_COMMENT` | Emit buffered code token; start line comment buffer |
| **CODE** | `/*` | `BLOCK_COMMENT` | Emit buffered code token; start block comment buffer |
| **CODE** | `R"delim(` | `RAW_STRING` | Emit buffered code token; record `delim`; enter raw string |
| **CODE** | `"` | `STRING` | Emit buffered code token; start string buffer |
| **CODE** | `'` | `CHAR_LITERAL` | Emit buffered code token; start char buffer |
| **CODE** | Other character / `\n` | `CODE` | Accumulate in code buffer; update line/col coordinates |
| **LINE_COMMENT** | `\n` | `CODE` | Emit `LINE_COMMENT` token; increment line, reset col |
| **LINE_COMMENT** | EOF | `CODE` | Emit `LINE_COMMENT` token |
| **LINE_COMMENT** | Other character | `LINE_COMMENT` | Accumulate in comment buffer |
| **BLOCK_COMMENT** | `*/` | `CODE` | Emit `BLOCK_COMMENT` token |
| **BLOCK_COMMENT** | Other character / `\n` | `BLOCK_COMMENT` | Accumulate in comment buffer; track line/col |
| **STRING** | `\"` (escaped) | `STRING` | Keep escape flag active; remain in string |
| **STRING** | `"` (unescaped) | `CODE` | Emit `STRING` token; return to code |
| **STRING** | Other character / `\n` | `STRING` | Accumulate in string buffer; track line/col |
| **CHAR_LITERAL** | `\'` (escaped) | `CHAR_LITERAL` | Keep escape flag active; remain in char literal |
| **CHAR_LITERAL** | `'` (unescaped) | `CODE` | Emit `CHAR_LITERAL` token; return to code |
| **CHAR_LITERAL** | Other character | `CHAR_LITERAL` | Accumulate in char buffer |
| **RAW_STRING** | `)delim"` | `CODE` | Emit `RAW_STRING` token; clear `delim` |
| **RAW_STRING** | Other character / `\n` | `RAW_STRING` | Accumulate in raw string buffer; track line/col |

### Codebase Unification
- `src/auto_healer.py`: `_mask_comments_and_strings()` delegates to `lexer.mask_comments_and_strings()`. Length and character positions are preserved 100% identically with spaces.
- `src/security_analyzer.py`: `_strip_code()` delegates to `lexer.strip_code()`.
- `TestSharedTokenizerUnification` in `test_week5.py` asserts both modules invoke the same tokenizer.

---

## 6. Step 4: Formal PDA Bracket Checker (`src/bracket_checker.py`)

### PDA Formal Model

Let the PDA be $P = (Q, \Sigma, \Gamma, \delta, q_0, Z_0, F)$:
- **Input Alphabet $\Sigma$:** Characters emitted by `src/lexer.py` in `State.CODE` (strings and comments are discarded before parsing).
- **Stack Alphabet $\Gamma$:** Bracket tuples $(b, \text{line}, \text{col})$ where $b \in \{'(', '\{', '['\}$ plus stack base marker $Z_0$.
- **State:** $Q = \{q_{\text{scan}}, q_{\text{accept}}, q_{\text{error}}\}$.

### Stack Transition Rules ($\delta$)

1. **Push Rules (Opening Delimiters):**
   $$\delta(q_{\text{scan}}, '(', \gamma) = (q_{\text{scan}}, ('(', L, C) \cdot \gamma)$$
   $$\delta(q_{\text{scan}}, '\{', \gamma) = (q_{\text{scan}}, ('\{', L, C) \cdot \gamma)$$
   $$\delta(q_{\text{scan}}, '[', \gamma) = (q_{\text{scan}}, ('[', L, C) \cdot \gamma)$$

2. **Pop Rules (Matching Closing Delimiters):**
   $$\delta(q_{\text{scan}}, ')', ('(', L_{\text{open}}, C_{\text{open}}) \cdot \gamma) = (q_{\text{scan}}, \gamma)$$
   $$\delta(q_{\text{scan}}, '\}', ('\{', L_{\text{open}}, C_{\text{open}}) \cdot \gamma) = (q_{\text{scan}}, \gamma)$$
   $$\delta(q_{\text{scan}}, ']', ('[', L_{\text{open}}, C_{\text{open}}) \cdot \gamma) = (q_{\text{scan}}, \gamma)$$

3. **Mismatched Bracket Pair Transition:**
   $$\delta(q_{\text{scan}}, c_{\text{close}}, (b_{\text{open}}, L_{\text{open}}, C_{\text{open}}) \cdot \gamma) = (q_{\text{scan}}, \gamma) \quad \text{where } \text{match}(c_{\text{close}}) \ne b_{\text{open}}$$
   *Action:* Record `BracketMismatch(kind='mismatched', bracket=c_close, expected=expected_close(b_open), open_pos=(L_open, C_open), close_pos=(L_curr, C_curr))`.

4. **Unexpected Closing Bracket Transition (Empty Stack):**
   $$\delta(q_{\text{scan}}, c_{\text{close}}, Z_0) = (q_{\text{scan}}, Z_0)$$
   *Action:* Record `BracketMismatch(kind='unexpected_closing', bracket=c_close, pos=(L_curr, C_curr))`.

5. **End-of-Input / Acceptance Condition:**
   - Stack contains only $Z_0 \implies$ Accept ($q_{\text{accept}}$).
   - Stack contains unpopped elements $(b_i, L_i, C_i) \implies$ Emit `BracketMismatch(kind='unclosed', bracket=b_i, open_pos=(L_i, C_i))`.

### New Benchmark Test Files Added:
1. `sx11_nested_bracket_mismatch.cpp`: Nested lambda within an unclosed `if` block inside a function.
2. `sx12_brackets_in_string.cpp`: Contains `"{ braces } and [ brackets ]"` inside string and comments, followed by an unclosed `(` on an expression. Ignores string brackets and accurately flags the paren.
3. `sx13_deeply_nested_unclosed.cpp`: 3 levels of nesting (`for` $\rightarrow$ `if` $\rightarrow$ `while`) with unclosed `if` brace.
4. `sx14_mismatched_paren_bracket.cpp`: Array indexing `arr[2)` mixing `[` with `)`.

---

## 7. Benchmark Verification & Metrics Comparison

Full benchmark execution on `benchmark/run_benchmark.py`:

| Metric | Week 4 Baseline (80 Files) | Week 5 Verified (84 Files) | Status |
|---|---|---|---|
| **Total Benchmark Files** | 80 | **84** | +4 syntax tests |
| **Status Accuracy** | 75/80 (93.8%) | **79/84 (94.0%)** | +0.2% |
| **Classification Accuracy** | 44/50 (88.0%) | **47/54 (87.0%)** | Stable |
| **Security Precision** | 11/12 (91.7%) | **11/12 (91.7%)** | Exact match |
| **Security Recall** | 11/15 (73.3%) | **11/15 (73.3%)** | Exact match |
| **Security Decoy FP Rate** | 1/12 (8.3%) | **1/12 (8.3%)** | Exact match (`sec15`) |
| **Auto-Healer Clean Heals** | 18 (or 19/50) | **21 / 53 (39.6%)** | +2 cleanly healed |
| **Auto-Healer Crashes** | 0 | **0** | Zero crashes |
| **Regression Rate on Prior 80 Files** | 0.0% | **0.0% (Zero regressions)** | Verified |
| **Regression Test Suite** | 24/24 passing | **43/43 passing** | 100% pass rate |

---

## 8. Summary of Scope Boundaries & Deferred Items

As instructed, the following items remain strictly deferred for future weeks:
- **Classifier Retraining & Dataset Modifications:** Deferred to **Week 6**.
- **CWE-476 / CWE-457 Detection Logic:** Deferred to **Week 7** (the scoped symbol table built this week is ready as the foundational prerequisite).
- **Optimize / Verify Engine Implementations:** Deferred to **Weeks 7–8**.
- **Process Sandboxing:** Deferred to **Week 8**.
- **Agent Trace / GUI Enhancements:** Deferred to **Week 9**.
