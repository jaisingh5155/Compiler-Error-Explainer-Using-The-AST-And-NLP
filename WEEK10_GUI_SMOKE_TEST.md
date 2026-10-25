# Week 10 GUI Manual Smoke Test Verification

**Project**: Compiler Error Explainer & Auto-Healer  
**Date**: October 7, 2026  
**Environment**: macOS ARM64, Python 3.13.9, PyQt6  
**Execution Mode**: Headless offscreen automation (`QT_QPA_PLATFORM=offscreen`)  
**Runner Script**: [`scratch/gui_smoke_test_week10.py`](file:///Users/jaisinghsaini/TOACD/cd1/scratch/gui_smoke_test_week10.py)  

---

## 1. Executive Summary

As part of the final Week 10 close-out deliverables, the graphical user interface ([`src/gui.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py)) underwent rigorous manual/automated smoke testing across six critical interactive paths, focusing on usability, visual hierarchy, stability, safety gate compliance, and stale output prevention.

All **6 out of 6** checks have **PASSED** unconditionally.

| # | Smoke Test Check Description | Target Component | Result | Notes |
|---|---|---|:---:|---|
| **1** | Compile warning-only file | Message Log & Error List | **PASS** | Warnings display in Message Log & create warning cards on clean compile |
| **2** | Agent Trace timeline text visibility | `AgentTracePage` Tree Widget | **PASS** | High-contrast `#1E293B` text against `#FFFFFF` background without hover |
| **3** | Sidebar icon selection indicators | Navigation Sidebar | **PASS** | Distinct 4px accent left bar & background tint on active selection |
| **4** | Run Code fresh output sequence | Run Code / Terminal Panel | **PASS** | Terminal cleared before run; 0 leftover output from prior runs |
| **5** | Linker error parse without crash | Diagnostics Parser / GUI | **PASS** | `line=None` handled safely in badge & log without unhandled exceptions |
| **6** | `sec03` S2 patch suggestion safety | Patch Review / Gate 5 | **PASS** | 2 S2 candidate patches surfaced in Review Fixes; 0 auto-applied; file untouched |

---

## 2. Detailed Test Cases and Verification Records

### Check 1: Compile Warning-Only File (`wo05_implicit_conversion.cpp`)
- **Objective**: Ensure that when a file compiles successfully with warnings only (0 errors), the Message Log does not suppress compiler output, and the warnings are surfaced as cards.
- **Fixture**: [`benchmark/warnings_only/wo05_implicit_conversion.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/warnings_only/wo05_implicit_conversion.cpp)
- **Steps**:
  1. Load file into GUI via `window.load_file()`.
  2. Trigger analysis via `window.analyze()`.
  3. Wait for compiler worker thread completion.
  4. Inspect `window.terminal.toPlainText()` and `window.error_cards_layout.count()`.
- **Expected**: Terminal displays compiler output containing warning details; warning count equals 1; exactly 1 warning card rendered.
- **Actual**:
  - Compiler warning count: `1`
  - Warning card count: `1`
  - Terminal log excerpt: `[WARNING] Found 1 warning(s) during compilation... implicit conversion loses integer precision`
- **Status**: **PASS**

---

### Check 2: Agent Trace Timeline Text Visibility
- **Objective**: Verify that tree widget items in the Agent Trace timeline are readable in their default resting state, without requiring the user to hover over nodes.
- **Fixture**: [`src/gui.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py#L380-L415) (`AgentTracePage.tree` stylesheet)
- **Steps**:
  1. Inspect the QSS stylesheet attached to `AgentTracePage.tree`.
  2. Verify foreground text color token `color: #1E293B` and background `background-color: #FFFFFF`.
  3. Check that header labels and tree items inherit explicit text contrast rules.
- **Expected**: Resting foreground color is `#1E293B` (slate dark gray) on `#FFFFFF`, providing a WCAG AA contrast ratio > 10:1.
- **Actual**: Stylesheet declares explicit item color `#1E293B`, selected color `#0F172A`, header color `#334155`. Text is fully visible without hover.
- **Status**: **PASS**

---

### Check 3: Sidebar Icon Visual Selection Indicator
- **Objective**: Confirm that clicking through any sidebar icon provides an unmistakable visual indicator denoting the currently active view.
- **Fixture**: [`src/gui.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/gui.py#L65-L120) (`SidebarButton.paintEvent`)
- **Steps**:
  1. Iterate index `0` through `7` via `sidebar.set_active_index(i)`.
  2. At each step, assert `button[i].is_active == True`.
  3. Assert all other `button[j].is_active == False` for `j != i`.
  4. Verify `paintEvent` draws a 4px primary-color indicator strip along the left edge (`#2563EB`) and background `#1E293B`.
- **Expected**: Active button displays an active border/background indicator, while inactive buttons return to resting state.
- **Actual**: All 8 sidebar buttons cleanly toggle active states in isolation, with distinct left-edge indicator bars.
- **Status**: **PASS**

---

### Check 4: Run Code Fresh Output Sequence
- **Objective**: Guarantee that clicking "Run Code" executes the current in-editor text and clears stale output from prior runs.
- **Fixture**: Sequential execution of `ALPHA_RUN_101` followed by `BETA_RUN_202`.
- **Steps**:
  1. Editor loaded with `#include <iostream>\nint main() { std::cout << "ALPHA_RUN_101" << std::endl; return 0; }`.
  2. Click "Run Code", wait for process completion. Terminal captured as `out_1`.
  3. Editor loaded with `#include <iostream>\nint main() { std::cout << "BETA_RUN_202" << std::endl; return 0; }`.
  4. Click "Run Code", wait for process completion. Terminal captured as `out_2`.
  5. Check `out_2` contains `"BETA_RUN_202"` and strictly DOES NOT contain `"ALPHA_RUN_101"`.
- **Expected**: Terminal displays only the output of the currently compiled file.
- **Actual**:
  - `out_1`: `ALPHA_RUN_101`
  - `out_2`: `BETA_RUN_202` (Zero occurrences of `ALPHA_RUN_101`).
- **Status**: **PASS**

---

### Check 5: Compile Linker Error Repro File (`lk01_undef_func.cpp`)
- **Objective**: Verify that compiler linker errors (which lack line numbers, where `diag.line is None`) do not trigger `TypeError` or crash the GUI card layout.
- **Fixture**: [`benchmark/linker_errors/lk01_undef_func.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/linker_errors/lk01_undef_func.cpp)
- **Steps**:
  1. Load `lk01_undef_func.cpp` into GUI.
  2. Trigger analysis via `window.analyze()`.
  3. Await worker completion.
  4. Verify UI state, card generation, and absence of exceptions.
- **Expected**: GUI parses `undefined reference to 'computeArea(int, int)'`, creates a badge displaying `Linker Error` or `Global`, without exception.
- **Actual**: Linker error cleanly caught, formatted, and displayed in Message Log (`undefined reference to 'computeArea(int, int)'`). Error card count: `1`. No unhandled exceptions.
- **Status**: **PASS**

---

### Check 6: `sec03` S2 Patch Suggestion Safety Gate
- **Objective**: Validate that a security-vulnerable file (`sec03_strcpy_overflow.cpp`) generates S2 candidate patches in the planner, routes them to Review Fixes, and strictly DOES NOT auto-apply them to disk.
- **Fixture**: [`benchmark/security/sec03_strcpy_overflow.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security/sec03_strcpy_overflow.cpp)
- **Steps**:
  1. Record initial file MD5 hash / byte content.
  2. Invoke planner in review mode (`run_planner(sec_file, review_mode=True)`).
  3. Load suggestions into `window.review_page.load_patches()`.
  4. Compare file content on disk after execution against original content.
  5. Check count of auto-applied patches and generated suggestions.
- **Expected**: File is byte-identical (0 auto-applied); 2 S2 suggestions generated and loaded into Patch Review UI.
- **Actual**:
  - Original file content matches current file content byte-for-byte (`not_modified == True`).
  - Auto-applied patch count: `0`.
  - S2 suggestion patches generated: `2` (`strncpy` replacements).
  - All patches require explicit user confirmation before applying.
- **Status**: **PASS**

---

## 3. Automation Output Log

```text
==================================================
STARTING TASK 4: GUI MANUAL SMOKE TEST (HEADLESS)
==================================================

[Check 1] Compile warning-only file...
  -> PASS: Found 1 warnings and 1 cards. Terminal logs warning.

[Check 2] Agent Trace timeline text visibility...
  -> PASS: Resting text color explicitly styled (color: #1E293B on #FFFFFF).

[Check 3] Sidebar icon selection indicator...
  -> PASS: All 8 sidebar icons toggle active state with left accent bar and highlight.

[Check 4] Run Code fresh content sequence...
  -> PASS: Run 1 output has ALPHA, Run 2 output has BETA with zero stale ALPHA text.

[Check 5] Compile linker error repro file...
  -> PASS: Cleanly parsed linker error without crashing (line=None handled safely).

[Check 6] Load sec03, run Auto-Heal, verify S2 suggestion-only...
  -> PASS: File untouched, S2 patches surfaced (2 suggestions), 0 auto-applied.

==================================================
TASK 4 GUI SMOKE TEST SUMMARY:
==================================================
Check 1: Compile warning-only file: PASS
Check 2: Trace timeline text visible: PASS
Check 3: Sidebar icon distinct selection: PASS
Check 4: Run Code fresh output: PASS
Check 5: Linker error no crash: PASS
Check 6: sec03 S2 visible and not auto-applied: PASS
==================================================
```

---

## 4. Conclusion & Sign-Off

The GUI smoke test suite verifies that all four Week 10 presentation and safety defects have been resolved without regressions. The interface handles warnings, linker errors, and security suggestions with zero crashes, stale data, or unauthorized disk writes.
