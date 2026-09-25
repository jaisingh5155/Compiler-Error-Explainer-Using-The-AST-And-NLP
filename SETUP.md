# SETUP.md — Getting Started

> Last verified: 2026-09-25 on macOS 27.0 (arm64, Apple Silicon)

---

## Prerequisites

### Operating System
- macOS 27.0 (tested) or later
- Should also work on Linux with GNU g++ (untested this week)

### Compilers
You need both `g++` and `clang++` accessible from the command line.

On macOS with Xcode Command Line Tools installed, both `g++` and `clang++` point to **Apple Clang**:
```
$ g++ --version
Apple clang version 21.0.0 (clang-2100.3.34.2)
Target: arm64-apple-darwin27.0.0

$ clang++ --version
Apple clang version 21.0.0 (clang-2100.3.34.2)
```

Install Xcode CLT if missing:
```bash
xcode-select --install
```

### Python
- Python 3.13+ required (tested with 3.13.9)
- `pip` (comes with Python)

---

## Setup Steps

### 1. Clone the repository
```bash
git clone <repo-url> cd1
cd cd1
```

### 2. Create a virtual environment
```bash
python3 -m venv .venv
```

### 3. Activate the virtual environment
```bash
source .venv/bin/activate
```

### 4. Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs:
- `PyQt6==6.11.0` — GUI framework
- `scikit-learn==1.9.1` — ML classifier
- `joblib==1.6.0` — Model serialization
- `numpy==2.5.3` — Numerical computing (scikit-learn dependency)
- `codecarbon==3.3.1` — Carbon emissions tracking

### 5. Verify installation
```bash
python3 -c "import PyQt6; import sklearn; import joblib; import numpy; print('All imports OK')"
```

---

## Running the Tool

### CLI — Analyze a C++ file
```bash
cd src
python3 main.py <path-to-cpp-file>
```

Example:
```bash
python3 main.py ../test_cases/syntax_error.cpp
```

### CLI — JSON output
```bash
python3 main.py ../test_cases/syntax_error.cpp -j
```

### CLI — Verbose (with code context)
```bash
python3 main.py ../test_cases/syntax_error.cpp -v
```

### CLI — Adjust context lines
```bash
python3 main.py ../test_cases/syntax_error.cpp -v -c 5
```

### GUI
```bash
python3 gui.py
```

**Caveats**:
- Requires a display server (X11/Wayland on Linux, native on macOS).
- Will not work in a headless SSH session without X forwarding.
- PyQt6 must be installed (included in requirements.txt).

---

## Running Tests Over All Test Cases

### Batch run (human-readable)
```bash
cd src
for f in ../test_cases/*.cpp ../test_cases/mini/*.cpp; do
    echo "=== $(basename $f) ==="
    python3 main.py "$f"
    echo
done
```

### Batch run (JSON, for scripting)
```bash
cd src
for f in ../test_cases/*.cpp ../test_cases/mini/*.cpp; do
    echo "=== $(basename $f) ==="
    python3 main.py "$f" -j 2>/dev/null
    echo
done
```

### Direct compiler check (for comparison)
```bash
for f in test_cases/*.cpp test_cases/mini/*.cpp; do
    echo "=== $(basename $f) ==="
    g++ -std=c++17 -Wall "$f" -o /dev/null 2>&1
    echo "Exit: $?"
    echo
done
```

---

## Retraining the Classifier

If the pre-trained model (`data/error_classifier.joblib`) produces `InconsistentVersionWarning` errors, retrain it:

```bash
cd src
python3 error_classifier.py
```

This will:
1. Build a dataset from the test cases
2. Train a new LogisticRegression model
3. Save it to `data/error_classifier.joblib`
4. Evaluate accuracy on the test cases

---

## Known Issues (Week 1)

1. **sklearn version mismatch**: The pre-trained model was created with scikit-learn 1.6.1. Running with 1.9.1 produces `InconsistentVersionWarning` on every invocation. The model still works but may produce slightly different results.

2. **`g++` on macOS is Apple Clang**: The project assumes GNU g++. Apple Clang has minor differences in error message formatting and warnings.

3. **Auto-healer requires PyQt6 QThread**: The heal loop (`heal_loop.py`) cannot be run from the CLI. Only the low-level `attempt_fix()` in `auto_healer.py` can be called standalone.

4. **`compiler_runner.py` vs `heal_loop.py` flag mismatch**: `compiler_runner.py` does NOT pass `-Wall`, while `heal_loop.py` does.

---

## Project Structure

```
cd1/
├── src/                    # All Python source files
│   ├── main.py             # CLI entry point
│   ├── gui.py              # PyQt6 GUI
│   ├── compiler_runner.py  # Runs g++ and parses errors
│   ├── error_parser.py     # Parses raw compiler output into Error objects
│   ├── error_classifier.py # ML-based error category classifier
│   ├── error_explainer.py  # Generates human-readable explanations
│   ├── error_normalizer.py # Normalizes error messages
│   ├── common_errors.py    # Glossary of common error patterns
│   ├── security_analyzer.py # Static security analysis
│   ├── auto_healer.py      # Auto-fix logic per error category
│   ├── heal_loop.py        # Iterative heal loop (QThread)
│   ├── diff_viewer.py      # Diff computation and HTML formatting
│   ├── healing_suggester.py # Suggestions when healing fails
│   ├── ast_extractor.py    # Clang AST dump and parsing
│   ├── models.py           # CompilerError data class
│   ├── dataset_logger.py   # Logs examples for training
│   ├── prepare_training_data.py  # Training data preparation
│   └── build_dataset_from_tests.py # Builds dataset from test_cases/
├── data/
│   ├── training_data.json        # Training data (14 MB)
│   └── error_classifier.joblib   # Pre-trained model (36 MB)
├── test_cases/             # C++ test files with intentional errors
│   └── mini/               # Annotated test cases with expected behavior
├── requirements.txt        # Pinned Python dependencies
├── SETUP.md               # This file
├── BASELINE_LOG.md        # Week 1 observations
├── BASELINE_RESULTS.csv   # Per-file baseline results
├── DOCUMENTATION.md       # Senior's original documentation
├── PBL_Report.md          # Senior's PBL report
└── project_explanation.md # Senior's project explanation
```

## Tested Environment
| Component | Version |
|-----------|---------|
| macOS | 27.0 (Build 26A428) |
| Architecture | arm64 (Apple Silicon M2) |
| Python | 3.13.9 |
| g++ / clang++ | Apple clang 21.0.0 |
| PyQt6 | 6.11.0 |
| scikit-learn | 1.9.1 |
| joblib | 1.6.0 |
| numpy | 2.5.3 |
| codecarbon | 3.3.1 |
