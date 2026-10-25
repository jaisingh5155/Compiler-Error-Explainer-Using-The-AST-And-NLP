# SETUP.md — Installation & Operations Guide

**Project**: Compiler Error Explainer & Verified Auto-Healer Using AST, NLP, and Agentic Controls  
**Last Verified**: October 8, 2026 on macOS 21.0 (arm64, Apple Silicon) & GNU GCC 16.2.0  
**Current Milestone**: Week 10 Part 2 Final Release  

---

## 1. Prerequisites

### Operating System & Architecture
- **macOS**: Tested on macOS 14/15/21+ (Apple Silicon ARM64 and Intel x86_64).
- **Linux**: Supported on Ubuntu 20.04/22.04/24.04 LTS and Debian-based systems.

### Compiler Toolchains
You need either `clang++` or `g++` accessible on your PATH:
- **macOS**: Install Xcode Command Line Tools:
  ```bash
  xcode-select --install
  ```
  Verify active compiler:
  ```bash
  clang++ --version
  # Apple clang version 21.0.0 (or similar)
  ```
- **Linux**: Install standard build tools:
  ```bash
  sudo apt-get update && sudo apt-get install -y build-essential clang
  ```

### Python Environment
- **Python**: Version 3.10 to 3.13 (verified with Python 3.13.9).
- **Pip**: Latest version (`pip install --upgrade pip`).

---

## 2. Quickstart Installation (Under 2 Minutes)

### Step 1: Clone Repository
```bash
git clone https://github.com/jaisingh5155/Compiler-Error-Explainer-Using-The-AST-And-NLP.git cd1
cd cd1
```

### Step 2: Create and Activate Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Required Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

*Installed Packages Include:*
- `PyQt6` (Desktop GUI IDE)
- `scikit-learn` & `joblib` (Platt-calibrated ML error classifier)
- `numpy` (Numerical computing)
- `codecarbon` (Energy and carbon emissions monitoring)
- `pytest` (Test automation framework)
- `reportlab` & `python-docx` (Report and PDF generation)

### Step 4: Verify Installation
```bash
python3 -c "import PyQt6, sklearn, joblib, numpy; print('All core modules imported successfully.')"
```

---

## 3. Operations & Usage Guide

All commands are run from the project root directory.

### 3.1 CLI Analysis & Error Explanation
Analyze a C++ source file and print plain-English AST explanations:
```bash
python3 src/main.py benchmark/syntax/sx01_missing_semi_decl.cpp -v
```
- `-v`, `--verbose`: Displays detailed explanation with source context pointers.
- `-c N`, `--context N`: Adjusts context lines shown (default: 2).

### 3.2 CLI JSON Output (Automation & Scripting)
Output structured JSON containing status, diagnostics, and security findings:
```bash
python3 src/main.py benchmark/syntax/sx01_missing_semi_decl.cpp -j
```

### 3.3 CLI Automated Repair with Live Agent Execution Trace
Trigger the iterative state-machine planner and inspect per-gate verification decisions:
```bash
python3 src/main.py benchmark/syntax/sx01_missing_semi_decl.cpp --heal --trace
```
- `--heal`: Activates the automated repair engine.
- `--trace`: Outputs human-readable step-by-step agent decisions and gate results.
- `--apply`: Automatically writes accepted patches to disk (default is safe non-destructive simulation).

### 3.4 CLI Batch Evaluation Over Directories
Run automated batch processing over a collection of test files:
```bash
python3 src/main.py --batch benchmark/syntax/
```
Generates batch summary metrics (attempted, healed, gave up, crashed, latency).

### 3.5 Launching the Desktop GUI IDE
Launch the full PyQt6 graphical interface:
```bash
python3 src/gui.py
```
*Key GUI Features:*
- **Diagnostics Tab**: View formatted compiler error cards.
- **Explanation Tab**: Read plain-English AST explanations with Beginner/Detailed toggle.
- **Security Tab**: Inspect detected CWE vulnerabilities, severities, and line badges.
- **Agent Trace Tab**: Follow real-time verification gate decisions across healing iterations.
- **Patch Review Tab**: Interactive review session (accept/reject/undo patches with diff previews).
- **Run Code Tab**: Compile and execute program in an isolated console.

---

## 4. Benchmark & Test Verification

### 4.1 Running the Full 100-File Benchmark Suite
Executes the canonical benchmark suite from clean state:
```bash
python3 benchmark/run_benchmark.py
```
Outputs status accuracy (99.0%), classification accuracy (98.1%), security recall (100%), and healing metrics.

### 4.2 Running the Full Automated Pytest Suite
Run all 185 unit, integration, and security tests:
```bash
pytest
```
*Run specific test modules:*
```bash
pytest tests/week10_verification/test_agent_security.py   # Agent Security Layer tests
pytest tests/test_week7_security.py                       # Static CWE detector tests
pytest tests/week8_verification/                          # Multi-gate verification tests
pytest tests/week9_verification/                          # GUI & patch review tests
```

### 4.3 Evaluating the Agent Security Attack Benchmark
Evaluate the 17-file adversarial attack and decoy benchmark:
```bash
python3 -c "from src.agent_security import evaluate_attack_benchmark; res = evaluate_attack_benchmark(); print('Precision:', res['precision'], 'Recall:', res['recall'], 'Block Rate:', res['block_rate'])"
```

---

## 5. Repository Structure

```
cd1/
├── src/                          # Core source codebase
│   ├── main.py                   # Unified CLI entry point
│   ├── gui.py                    # PyQt6 Graphical IDE
│   ├── planner.py                # Deterministic state-machine Planner
│   ├── agent_security.py         # Agent Security Defense Layer (Tripwires & Gate 6)
│   ├── sandbox.py                # Seatbelt-isolated compilation & execution sandbox
│   ├── ast_parser.py             # Native Clang JSON AST extractor (-ast-dump=json)
│   ├── lexer.py                  # Deterministic DFA token stream lexer
│   ├── bracket_checker.py        # Bracket nesting stack automaton
│   ├── error_classifier.py       # Platt-calibrated Linear SVM classifier
│   ├── error_explainer.py        # Context-enriched NLP explanation engine
│   ├── security_analyzer.py      # Static AST security analyzer (10 CWEs)
│   ├── auto_healer.py            # Multi-tier repair generators & rule library
│   ├── patch_review.py           # Interactive patch review session state machine
│   ├── trace_view.py             # Agent execution trace formatters (CLI/HTML)
│   └── tools/                    # Modular tool interfaces (understand, detect, repair, verify)
│       └── verify_gates.py       # 6-Gate sandboxed verification pipeline
├── data/                         # Persistent models and audit logs
│   ├── error_classifier_v2.joblib # Calibrated SVM model artifact
│   ├── training_data_v2.json     # Curated classifier training dataset
│   └── agent_security_log.jsonl  # Append-only atomic security audit log
├── benchmark/                    # Benchmark test suites (100 files + 17 attacks)
│   ├── run_benchmark.py          # Benchmark evaluation orchestrator
│   ├── syntax/                   # C++ syntax error benchmarks
│   ├── type_errors/              # Semantic type error benchmarks
│   ├── name_resolution/          # Identifier lookup benchmarks
│   ├── missing_include/          # Header resolution benchmarks
│   ├── redefinition/             # Variable/function redefinition benchmarks
│   ├── return_type/              # Return type mismatch benchmarks
│   ├── security/                 # CWE vulnerability & decoy benchmarks
│   └── agent_attacks/            # 17 adversarial attack & decoy benchmarks
├── tests/                        # Comprehensive Pytest test suites (185 tests)
│   ├── week10_verification/      # Agent security verification tests
│   ├── week9_verification/       # Patch review and feedback tests
│   ├── week8_verification/       # Verification gate and sandbox tests
│   ├── week7_verification/       # Security analyzer generalization tests
│   └── week3_verification/       # Bug 1.1–7.1 regression suites
├── PBL_REPORT_FINAL.md           # Submission-ready final consolidated project report
├── PBL_REPORT_FINAL.docx         # Microsoft Word export of final report
├── PROJECT_DEMO_AND_VERIFICATION_GUIDE.md # Comprehensive evaluator demo guide
├── Project_Demo_and_Verification_Guide.pdf # Formatted PDF evaluation guide
├── Existing_and_Proposed_Architecture.pdf  # Architectural comparison diagrams (PDF)
├── DEMO_SCRIPT.md                # 10-minute presentation demo script
├── requirements.txt              # Pinned Python package dependencies
└── SETUP.md                      # This setup guide
```
