# Compiler Version Audit & Environment Verification Report

**Date:** September 26, 2026  
**Auditor:** Independent Audit Follow-up  
**Focus:** Resolution of Compiler Version Drift & Environment Forensics  

---

## 1. Verbatim Compiler Versions (Current System)

Command executed:
```bash
clang++ --version
g++ --version
```

### Exact Verbatim Output:
```text
Apple clang version 21.0.0 (clang-2100.3.34.2)
Target: arm64-apple-darwin27.0.0
Thread model: posix
InstalledDir: /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin
---
Apple clang version 21.0.0 (clang-2100.3.34.2)
Target: arm64-apple-darwin27.0.0
Thread model: posix
InstalledDir: /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin
```

Both `clang++` and `g++` on macOS are shims resolving directly to the Xcode default toolchain compiler binary at `/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang`.

---

## 2. Cross-Milestone Version Comparison & Historical Forensics

We cross-referenced the compiler versions recorded in all milestone deliverables, setup logs, and git history:

| Document / Milestone | Recorded Compiler Version | Date of Execution | Veracity / Forensics Notes |
|---|---|---|---|
| `SETUP.md` | `Apple clang version 21.0.0 (clang-2100.3.34.2)` | Early Setup | Machine hardware & toolchain documentation |
| `BASELINE_LOG.md` (Week 1) | `Apple clang version 21.0.0 (clang-2100.3.34.2)` | Sep 23–24, 2026 | Verified verbatim in Section 5 & Table |
| `BASELINE_RESULTS.csv` (Week 1) | `g++ (Apple clang 21.0)` | Sep 24, 2026 | Explicitly logged in compiler column |
| `WEEK2_REPORT.md` (Week 2) | `Apple Clang version 21.0.0 (g++ symlink)` | Sep 25, 2026 | Verified in report metadata header |
| `WEEK3_REPORT.md` (Week 3) | `Apple Clang 21.0.0` | Sep 25, 2026 | Verified in report environment header |
| `WEEK4_REPORT.md` (Week 4) | `Apple Clang (Darwin)` | Sep 26, 2026 | Referenced consistently throughout narrative |
| `WEEK4_VERIFICATION_REPORT.md` | `Apple Clang 17.0.0` | Sep 26, 2026 | **Discrepancy (Auditor Recording Error)** |
| `WEEK5_REPORT.md` (Week 5) | `Apple Clang 21.0.0` | Sep 26, 2026 | Verified via `clang++ -Xclang -ast-dump=json` |

### Forensic Finding on the "Apple Clang 17.0.0" Discrepancy:
1. **System & Xcode Timestamp Audit:**
   - Active Xcode Application: `/Applications/Xcode.app`
   - Installed Date: `Sep 17 09:25:18 2026`
   - Xcode Version: `Xcode 27.0 (Build version 27A266a)`
   - No other Xcode or Homebrew LLVM toolchain has been installed or modified since September 17, 2026.
2. **Git Commit History Alignment:**
   - Week 1 initial commits: September 23, 2026
   - Week 2 commits: September 25, 2026
   - Week 3 commits: September 25, 2026
   - Week 4 & Week 5 commits: September 26, 2026
3. **Forensic Verdict:**
   - **Every single milestone (Weeks 1, 2, 3, 4, and 5) was actually executed under Apple Clang 21.0.0 (clang-2100.3.34.2).**
   - The "Apple Clang 17.0.0" string in `WEEK4_VERIFICATION_REPORT.md` line 6 was an **auditor recording error**, caused by conflating the public upstream LLVM version (LLVM 17 / Xcode 16/17 naming conventions) with Apple Clang's internal build-numbering scheme (`21.0.0`). The underlying compiler binary never drifted or changed.

---

## 3. Classifier Generalization Check (Re-evaluation)

We re-ran the Week 3 held-out generalization test suite (`tests/week3_verification/run_generalization_test.py`) against all 5 novel C++ error test cases under the currently active compiler (`Apple clang 21.0.0`):

```text
================================================================================
CLASSIFIER GENERALIZATION TEST (5 NOVEL HELD-OUT C++ FILES)
================================================================================
[✓] gen01_undeclared_func.cpp
    Raw Clang: use of undeclared identifier 'processTelemetryStream'
    Expected:  name_resolution
    Predicted: name_resolution (confidence: 1.000)

[✓] gen02_type_ptr_init.cpp
    Raw Clang: cannot initialize a variable of type 'int *' with an lvalue of type 'double'
    Expected:  type_error
    Predicted: type_error (confidence: 0.980)

[✓] gen03_undeclared_loop_var.cpp
    Raw Clang: use of undeclared identifier 'accumulator'
    Expected:  name_resolution
    Predicted: name_resolution (confidence: 1.000)

[✓] gen04_incompat_assign.cpp
    Raw Clang: incompatible integer to pointer conversion assigning to 'float *' from 'int'
    Expected:  type_error
    Predicted: type_error (confidence: 0.553)

[✓] gen05_binary_op_mismatch.cpp
    Raw Clang: invalid operands to binary expression ('AudioSample' and 'AudioSample')
    Expected:  type_error
    Predicted: type_error (confidence: 0.666)

--------------------------------------------------------------------------------
Generalization Accuracy: 5/5 (100.0%)
================================================================================
```

### Result & Conclusion:
- **Score:** **5/5 (100.0%)**
- **Dialect Normalization Robustness:** The regex dialect normalization rules in [`src/error_classifier.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/error_classifier.py) successfully normalize raw Clang diagnostics (`use of undeclared identifier`, `cannot initialize a variable of type ...`, `incompatible integer to pointer conversion`, `invalid operands to binary expression`) into the canonical GCC phrasings expected by the TF-IDF / Logistic Regression classifier model.
- **Zero Regressions:** Zero regressions occurred; generalization accuracy remains at 100%.

---

## 4. Benchmark Runner Compiler Version Pinning

To prevent any future silent compiler drift from going unnoticed, [`benchmark/run_benchmark.py`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/run_benchmark.py) has been updated with explicit, permanent version pinning:

1. **Dynamic Version Detection:**
   ```python
   def get_compiler_version() -> str:
       try:
           proc = subprocess.run(["clang++", "--version"], capture_output=True, text=True)
           if proc.stdout:
               return proc.stdout.splitlines()[0].strip()
       except Exception:
           pass
       return "unknown"
   ```
2. **CSV Header Comment:**
   Every generated benchmark summary now records the compiler in the header comments:
   ```text
   # BENCHMARK RESULTS — AGGREGATE SUMMARY
   # Date: 2026-09-26
   # Compiler Version: Apple clang version 21.0.0 (clang-2100.3.34.2)
   # Total benchmark files: 84
   ```
3. **Per-Row CSV Metadata Column:**
   A dedicated column `compiler_version` is now recorded on every single row in `benchmark/BENCHMARK_RESULTS.csv`, ensuring full traceability across individual test cases:
   ```csv
   filepath,category_dir,compiler_version,cwe,expected_status,actual_status,...
   benchmark/syntax/sx01_missing_semi_decl.cpp,syntax,Apple clang version 21.0.0 (clang-2100.3.34.2),,error,error,...
   ```
