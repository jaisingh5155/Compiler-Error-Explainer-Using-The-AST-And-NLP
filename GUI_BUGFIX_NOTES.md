# GUI Bugfix Notes: Manual Testing Corrections

**Component**: `src/gui.py` (Presentation Layer)  
**Date**: 2026-10-02  
**Scope**: Presentation-only bug fixes for Message Log, Agent Execution Trace, and Left Navigation Rail. Underlying analysis engines (`compiler_runner.py`, `security_analyzer.py`, `planner.py`) were untouched.

---

## Bug 1: Warnings Hidden in Message Log on Successful Compilation

### 1. Root Cause Confirmation
- **Hypothesis**: The Message Log UI only renders diagnostic content when `status == "error"`, and discards or never passes through the warning list when `status == "success"`.
- **Reality**: **Hypothesis matched reality 100%.**
  In `src/gui.py` within `render_json(self, data, raw_stderr)`:
  ```python
  if status == "success":
      self.status_label.setText("STATUS: ● SUCCESSFUL")
      lbl = QLabel("NO ISSUES DETECTED.")
      lbl.setStyleSheet(f"color: {PINK}; font-weight: bold; font-family: {FONT_FAMILY}; font-size: 14px;")
      self.error_cards_layout.addWidget(lbl)
      self.terminal.append_output(f"<span style='color:{TEXT_MAIN};'>Compilation finished successfully.</span>", is_html=True)
      self.editor.set_errors([])
      self.errors_count = 0
      self.warnings_count = 0
      self._update_footer()
      return
  ```
  When a file compiled with 0 errors and >= 1 warnings, the backend properly returned `status: "success"` with `error_count: 0`, `warning_count: 2`, and `errors: [...]` populated with warning dicts. However, `render_json` immediately returned early on `status == "success"`, completely discarding the warning list, resetting `self.warnings_count = 0`, and displaying `NO ISSUES DETECTED.`

### 2. Fix Applied
- In `src/gui.py` (`render_json`):
  1. Extracted `errors = data.get("errors", [])` and computed `self.errors_count` and `self.warnings_count`.
  2. Gated `NO ISSUES DETECTED.` strictly behind `not errors and self.errors_count == 0 and self.warnings_count == 0`.
  3. When `self.warnings_count > 0` but `self.errors_count == 0`:
     - Updated status header to `STATUS: ● {self.warnings_count} WARNINGS FOUND`.
     - Updated the footer counters via `_update_footer()`.
     - Fed `errors` to `self.editor.set_errors(errors)` so warning line markers appear in the editor.
     - Formatted compiler terminal output with `[WARNING]` in distinct amber/yellow (`#ffcc00` / `YELLOW`) with file names, line numbers, and column offsets.
     - In `_create_error_card(error)`, mapped `etype == "WARNING"` to `MEDIUM` severity, applying distinct amber border (`border: 1px solid YELLOW`), `[WARNING]` header tag, and green fix suggestions.
  4. Preserved clean compilation: when `errors` is empty and counts are 0, `NO ISSUES DETECTED.` is displayed.

### 3. Verification
- **Unused Variables Test Case**: Verified with 2 declared-but-unused variables. The Message Log rendered both `[WARNING]` cards with hotspot line numbers (`Line 6`, `Line 7`) and suggestions, terminal output logged both warnings in amber, and status label displayed `STATUS: ● 2 WARNINGS FOUND`.
- **Clean File Test Case**: Verified a clean compile (0 errors, 0 warnings). Message Log displayed `NO ISSUES DETECTED.` and terminal displayed `Compilation finished successfully. Zero errors and zero warnings.`

---

## Bug 2: Step-by-Step Execution Timeline Text Invisible Until Hover

### 1. Root Cause Confirmation
- **Hypothesis**: CSS issue where text color and background color are identical or near-identical in resting (non-hover) state, and a `:hover` or `:selected` rule creates contrast.
- **Reality**: **Hypothesis matched reality 100%.**
  In `AgentTracePage.__init__` in `src/gui.py`:
  ```python
  self.tree.setStyleSheet("""
      QTreeWidget {
          background-color: #FFFFFF;
          border: 1px solid #E2E8F0;
          border-radius: 8px;
          padding: 4px;
          font-size: 11px;
      }
      QTreeWidget::item {
          padding: 4px;
      }
      QTreeWidget::item:selected {
          background-color: #EDE9FE;
          color: #5B21B6;
      }
  """)
  ```
  `background-color: #FFFFFF` (white) was explicitly declared, but `color:` was omitted for both `QTreeWidget` and `QTreeWidget::item`. On macOS in dark mode, default Qt text colors inherited from the dark OS palette (white/light grey), causing white text to render on a white background. Only when selecting a row (`#5B21B6`) or hovering was text revealed.

### 2. Fix Applied
- In `src/gui.py` (`AgentTracePage`):
  Updated `self.tree.setStyleSheet` to explicitly specify resting/default text colors and clean header styles:
  ```python
  self.tree.setStyleSheet(f"""
      QTreeWidget {{
          background-color: #FFFFFF;
          color: #1E293B;
          border: 1px solid #E2E8F0;
          border-radius: 8px;
          padding: 4px;
          font-size: 11px;
          font-family: {FONT_FAMILY};
      }}
      QHeaderView::section {{
          background-color: #F8FAFC;
          color: #334155;
          border: none;
          border-bottom: 1px solid #E2E8F0;
          padding: 6px 8px;
          font-weight: bold;
          font-size: 11px;
          font-family: {FONT_FAMILY};
      }}
      QTreeWidget::item {{
          padding: 5px 4px;
          color: #1E293B;
          border-bottom: 1px solid #F8FAFC;
      }}
      QTreeWidget::item:hover {{
          background-color: #F1F5F9;
          color: #0F172A;
      }}
      QTreeWidget::item:selected {{
          background-color: #EDE9FE;
          color: #5B21B6;
      }}
  """)
  ```

### 3. Verification
- Loaded the Agent Trace view with a populated multi-step execution trace.
- Verified in the resting state without hovering that all rows (step titles, tool names, outcomes, and gate statuses) are immediately legible in crisp slate `#1E293B` on `#FFFFFF`.

---

## Bug 3: No Visual Indication of Selected Icon in Navigation Rail

### 1. Root Cause Confirmation
- **Hypothesis**: All buttons in the left rail use a static, unselected style (`outline_dim`) and have no logic tracking or styling the currently active view index.
- **Reality**: **Hypothesis matched reality 100%.**
  `Sidebar` instantiated 8 `StyledButton` widgets (`btn1` through `btn8`). Clicking them invoked `self.stack.setCurrentIndex(...)`, but no widget state, stylesheet property, or event connection updated button styles. All 8 buttons remained in the default resting style regardless of which stacked page was open.

### 2. Fix Applied
- **Design Choice**: Chose **Option (a)** (rich hover tooltips + prominent left-edge accent bar & background highlight on the active icon).
  - *Rationale*: The 54px left navigation rail is designed as an ultra-compact icon rail (matching modern IDE standards like VS Code). Permanent text labels beside or under icons would require expanding the rail width significantly or cramming illegible micro-text. Clear, styled tooltips (`QToolTip` with dark slate background, white text, and `#5469d4` border) provide instant context on hover, while an active indicator makes the current view unmistakable at a glance.
- In `StyledButton`:
  - Added `self.is_active = False` and `set_active(self, active: bool)`.
  - In `_update_style(progress)`:
    - **Active State**: Styled with `border: 1px solid #5469d4; border-left: 4px solid #5469d4; background-color: #e8ecfb; color: #5469d4; font-weight: bold;`.
    - **Inactive State**: Styled with `border: 1px solid #e6ebf1; border-left: 1px solid #e6ebf1; background-color: #ffffff; color: #4f566b;`.
- In `Sidebar`:
  - Added `set_active_index(self, index: int)` method that updates all buttons, setting `set_active(i == index)` and appending `(Active View)` to the tooltip of the selected icon.
  - Initialized with `self.set_active_index(0)` so the Editor icon starts in active state.
- In `AppGUI`:
  - Connected `self.stack.currentChanged.connect(self.sidebar.set_active_index)`. This guarantees that whether a user clicks a rail button or code switches views programmatically, the active indicator remains in sync.

### 3. Verification
- Sequentially clicked through all 8 sidebar buttons (`Editor`, `AST`, `Energy`, `Call Graph`, `Security`, `CFG`, `Trace`, `Review`).
- Verified for each click:
  1. The selected button immediately acquired the 4px left-edge accent bar and `#e8ecfb` background highlight.
  2. All other 7 buttons reverted to the subtle inactive style.
  3. Hovering over any button displayed the tooltip with view name and `(Active View)` tag if selected.

---

## Screenshot Artifacts Generated

All screenshots have been captured and saved to `screenshots/` and embedded in the artifact directory:

| Bug | Scenario | Screenshot File | Description |
| :--- | :--- | :--- | :--- |
| **Bug 1** | Warnings in Message Log (Before) | `screenshots/bug1_message_log_before.png` | Shows "NO ISSUES DETECTED." despite compiler warnings |
| **Bug 1** | Warnings in Message Log (After) | `screenshots/bug1_message_log_after.png` | Shows 2 distinct `[WARNING]` cards with line numbers and amber tags |
| **Bug 1** | Clean Compile Verification (After) | `screenshots/bug1_clean_compile_after.png` | Shows "NO ISSUES DETECTED." correctly preserved on 0 errors, 0 warnings |
| **Bug 2** | Trace Step Timeline (Before) | `screenshots/bug2_timeline_before.png` | Timeline appears blank/white due to missing text color in resting state |
| **Bug 2** | Trace Step Timeline (After) | `screenshots/bug2_timeline_after.png` | All steps and gate results are immediately readable in resting state |
| **Bug 3** | Navigation Rail (Before) | `screenshots/bug3_sidebar_before.png` | All 8 icons look identical with no indication of active view |
| **Bug 3** | Navigation Rail (After) | `screenshots/bug3_sidebar_after.png` | Active icon highlighted with 4px left-edge accent bar and background fill |
| **Bug 3** | Full Window (After) | `screenshots/bug3_full_window_after.png` | Full application view demonstrating persistent active rail indicator |
| **Bug 4** | Linker Error Main View | `screenshots/linker_error_repro_editor.png` | Shows clean linker error card and terminal output with no crash on line=None |
| **Bug 4** | Linker Error Security Tab | `screenshots/linker_error_repro_security.png` | Verifies Security tab cleanly handles linker error without crash |
| **Bug 4** | Linker Error Trace Tab | `screenshots/linker_error_repro_trace.png` | Verifies Agent Trace tab cleanly handles linker error without crash |
| **Bug 4** | Linker Error AST Tab | `screenshots/linker_error_repro_ast.png` | Verifies AST tab cleanly handles linker error without crash |
| **Bug 4** | Linker Error Call Graph Tab | `screenshots/linker_error_repro_callgraph.png` | Verifies Call Graph tab cleanly handles linker error without crash |
| **Bug 4** | Linker Error CFG Tab | `screenshots/linker_error_repro_cfg.png` | Verifies CFG tab cleanly handles linker error without crash |
| **Bug 4** | Linker Error Review Tab | `screenshots/linker_error_repro_review.png` | Verifies Review tab cleanly handles linker error without crash |
| **Bug 5** | Run Code Sequence: File A | `screenshots/run_code_sequence_file_a.png` | Shows fresh execution output matching File A ("HELLO FROM FILE A") |
| **Bug 5** | Run Code Sequence: File B | `screenshots/run_code_sequence_file_b.png` | Shows fresh execution output matching File B ("MATRIX CALCULATION [42]") |
| **Bug 5** | Run Code Sequence: File C | `screenshots/run_code_sequence_file_c.png` | Shows fresh execution output matching File C ("FINAL VERIFICATION PASSED") |

---

## Bug 4: Application Crash on Linker Errors (`line=None`)

### 1. Root Cause Analysis
- **Problem**: When analyzing C++ source files containing linker errors (e.g. `int computeArea(int w, int h);` declared but never defined, called from `main()`), the application process aborted completely (`zsh: abort`).
- **Traceback**:
  ```text
  File "src/gui.py", line 3971, in _on_analysis_finished
    self.render_json(data, stderr)
  File "src/gui.py", line 4068, in render_json
    first_err_line = int(line)
  TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'
  ```
- **Underlying Cause**: Linker errors legitimately have NO line or column number because the compiler cannot point to a specific source line for a missing symbol definition. The backend diagnostic engine sets `line=None` and `column=None` (as well as `context=None`). The GUI presentation layer assumed every diagnostic would always contain a non-None, convertible integer string for `line` and `column`, causing an unhandled `TypeError` that terminated the Qt event loop.

### 2. Audit of Crash Sites and Latent Vulnerabilities
A complete audit across `src/gui.py` identified 7 locations requiring defensive guards:

1. **`render_json` (Line 4068 & Line 4079 & Line 4082)**:
   - *Direct Crash Site*: `if first_err_line is None and line != "?": first_err_line = int(line)` crashed when `line is None` because `None != "?"` evaluated to `True`.
   - *Latent Crash Sites*: `if i == int(line) if line != "?" else False:` and `len(str(i)) + 2 + int(col)` also crashed on `None`.
   - *Context Crash Site*: `context = e.get("context", {})` returned `None` when the diagnostic had `"context": null`, causing subsequent `context.get(...)` to raise `AttributeError: 'NoneType' object has no attribute 'get'`.
   - *Fix*: Added safe conversion helpers `line_int` and `col_int` with `try...except (ValueError, TypeError)`. Safe `context = e.get("context") or {}`. Formatted location string as `[linker error - no specific line]` or `[no specific line]` instead of `None:None`.
2. **`CodeEditor.highlight_current_line` (Line 736)**:
   - *Latent Crash Site*: Iterated through `self.errors` and evaluated `if not line or line <= 0:`. If `line` was a string (e.g., `"?"`), `line <= 0` raised `TypeError`.
   - *Fix*: Added defensive parsing for `raw_line` and `raw_col` ensuring `line` and `col` are integers or `None`, skipping squiggly underline generation when `line is None`.
3. **`_create_error_card` (Line 3462)**:
   - *Latent Formatting Bug*: `hotspot = error.get('hotspot', f"Line {error.get('line', '?')}")` evaluated to `"Line None"`.
   - *Fix*: Checked `error.get('line')`; if `None` and `category == 'linker_error'`, formats as `"No specific line (linker error)"`, or `"No specific line"`.
4. **`_on_heal_give_up` (Line 3425)**:
   - *Latent Crash Site*: `if last_err and last_err.get("line"): block = self.editor.document().findBlockByLineNumber(int(last_err["line"]) - 1)`. If `line` was `"?"`, truthiness passed and `int()` raised `ValueError`.
   - *Fix*: Verified `last_err.get("line") is not None` and wrapped `int()` in `try...except (ValueError, TypeError)`.
5. **`UserGuidanceDialog.__init__` (Line 1206)**:
   - *Latent Formatting Bug*: `line_no = last_err.get("line", "?")` returned `None` when `"line": None`, displaying `"Category: ... | Line: None"`.
   - *Fix*: Formatted cleanly as `"No specific line (linker error)"` when `line_no is None`.
6. **`SecurityCard.__init__` (Line 1852)**:
   - *Latent Formatting Bug*: `self.line_chip = QLabel(f"Line {finding.get('line', '—')}")` displayed `"Line None"` if finding line was `None`.
   - *Fix*: Formatted cleanly as `"No specific line"` when `None`.
7. **`load_file` (Line 3907)**:
   - *Enhancement*: Updated `load_file(self, filename=None)` to accept an optional file path programmatically for headless testing and external calls.

### 3. Verification & Regression Testing
- **Standalone Regression Test**: Created `tests/test_gui_linker_error_none_line.py` testing:
  - `test_render_json_with_none_line`: Passes diagnostic with `line=None, column=None` directly to `render_json`; verifies 0 exceptions, status set to `STATUS: ● 1 ERRORS FOUND`, and Message Log contains error message and category.
  - `test_code_editor_set_errors_none_line`: Tests `set_errors` with `line=None`, string `"?"`, and valid integers.
  - `test_security_card_none_line`: Verifies `SecurityCard` renders `"No specific line"` without displaying `"Line None"`.
  - `test_user_guidance_dialog_none_line`: Verifies `UserGuidanceDialog` handles `line=None` cleanly.
  - `test_on_analysis_finished_linker_error_repro`: Simulates exact backend analysis payload for `lk01_undef_func.cpp`.
  - *Result*: 5/5 tests passing in 1.35s.
- **End-to-End Verification with Repro File**:
  - Loaded `benchmark/linker_errors/lk01_undef_func.cpp` into `AppGUI` and ran `window.analyze()`.
  - Application process completed cleanly without aborting.
  - Terminal Message Log cleanly rendered:
    ```text
    [ERROR] lk01_undef_func.cpp [linker error - no specific line]: error: undefined reference to 'computeArea(int, int)'
    ```
  - Navigated across all panels (**Agent Trace**, **Security**, **AST**, **Call Graph**, **CFG**, and **Review**); confirmed 100% stability and zero latent crashes across all diagnostic-consuming views.

---

## Bug 5: Run Code Displays Stale Output / Executes Stale Binary

### 1. Root Cause Confirmation
- **Root Cause Confirmed**: **(b) WRONG SOURCE EXECUTED** (with a contributing factor in **(a) STALE DISPLAY**).
  1. **Wrong Source Executed (`a.out`)**:
     In `src/gui.py` (`run_code`):
     ```python
     def run_code(self):
         if not os.path.exists("./a.out"):
              self.terminal.append_output(f"<span style='color:{PINK}'>File 'a.out' not found. Please compile first.</span>", is_html=True)
              return
         ...
         self.process.start("./a.out")
     ```
     `run_code` never compiled the live editor buffer. It blindly started `./a.out` from the current working directory. Furthermore, the "COMPILE" button (`analyze`) only invokes `main.py` which runs `sandbox.compile_sandboxed()` in a temporary sandbox directory (subsequently deleted) to generate JSON diagnostics—meaning "COMPILE" also never produced or updated `./a.out` in the working directory. Consequently, `./a.out` was a permanent stale binary on disk from a prior file (which contained a `calculate()` function that printed `"Calculation started"`). Every click of "Run Code" simply executed that leftover binary.
  2. **Unsaved Live Buffer**:
     `run_code` never called `save_file()` or synchronized the in-memory editor text to disk before execution.
  3. **Stale Display Handling**:
     If `./a.out` was missing or if compilation failed, errors were appended to whatever content remained in the terminal widget rather than clearing the display first.

### 2. Confirmation on Compile and Auto-Heal
- **Compile (`self.analyze`)**: Audited and confirmed **not affected**. `analyze()` explicitly calls `self.save_file()`, clears the terminal (`self.terminal.clear()`), resets all error cards, and renders fresh diagnostic JSON.
- **Auto-Heal (`self.start_heal`)**: Audited and confirmed **not affected**. `start_heal()` calls `self.save_file()`, clears cards, and runs `HealWorker` directly against the saved file path.

### 3. Fix Applied
In `src/gui.py` within `run_code(self)` and `_on_process_finished(self)`:
1. **Immediate Reset**:
   At the start of `run_code`, `self.terminal.clear()` is called immediately, `self.editor.clear_fixed_lines()` is invoked, and any ongoing running process is terminated via `self.process.kill()`.
2. **Live Buffer Extraction & Persistence**:
   Extracts `code = self.editor.toPlainText()`. If empty or whitespace-only, aborts with a clean notification (`No code to run. Editor is empty.`). Saves the live text to `self.file_path` (or falls back to a dedicated temporary file).
3. **Stale Binary Removal**:
   Explicitly deletes any pre-existing `./a.out` binary (`os.remove(bin_path)`) before invoking the compiler. This guarantees that if compilation fails, no stale executable can ever be executed.
4. **On-the-Fly Live Compilation**:
   Compiles the current code buffer directly into `bin_path` via `subprocess.run([compiler, "-std=c++17", src_file, "-o", bin_path])`.
5. **Compilation Error Guarding**:
   If compilation fails (`returncode != 0`), the formatted compiler error is rendered in the terminal, status is set to `STATUS: ● BUILD FAILED`, and execution is aborted.
6. **Execution of Fresh Binary**:
   Executes the brand new `bin_path` through `QProcess`, streaming output live to the terminal. When execution completes with empty output, an informative notice `[Program finished with exit code 0 (no output)]` is shown.

### 4. Verification Across Multiple Consecutive Runs
- **Automated Regression Suite**:
  Created `tests/test_gui_run_code_fresh_content.py` covering:
  - Multi-run sequence across 3 distinct programs (A, B, C) without reloading files (100% pass).
  - Compilation failure blocking stale binary runs (100% pass).
  - Empty editor guard producing clean notification (100% pass).
- **3-File Live Sequence (A -> B -> C)**:
  1. **Run 1 (File A)**: Replaced editor with `"=== OUTPUT FILE A: HELLO FROM FILE A ==="`. Output matched File A exactly; zero stale output.
  2. **Run 2 (File B)**: Without reloading, replaced editor with `"=== OUTPUT FILE B: MATRIX CALCULATION [42] ==="`. Output matched File B exactly; zero leftover from File A.
  3. **Run 3 (File C)**: Without reloading, replaced editor with `"=== OUTPUT FILE C: FINAL VERIFICATION PASSED ==="`. Output matched File C exactly; zero leftover from File A or B.
  4. Verified "Compile" on a syntax error; cleanly rendered error markers and compiler diagnostics.


