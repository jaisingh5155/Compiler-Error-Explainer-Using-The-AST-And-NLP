# Compiler Error Explainer & Verified Auto-Healer

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Compiler](https://img.shields.io/badge/Compiler-Apple%20Clang%20%7C%20GNU%20GCC-green.svg)](https://clang.llvm.org/)
[![Tests](https://img.shields.io/badge/Tests-185%2F185%20Passing-brightgreen.svg)](tests/)
[![Security Precision](https://img.shields.io/badge/Security%20Precision-1.000%20(100%25)-purple.svg)](benchmark/security/)
[![Agent Defense](https://img.shields.io/badge/Agent%20Defense-100%25%20Block%20Rate-red.svg)](src/agent_security.py)

> **"Rather than writing a toy parser from scratch or trusting an unconstrained Large Language Model to guess code fixes, this project wraps industry-standard compilers (Apple Clang / GNU GCC) with an intelligent, deterministic agentic control layer that explains errors using AST context and NLP, synthesizes verified multi-tier repairs, enforces static memory security, and protects its own decision-making against adversarial manipulation."**

---

## Key Features

1. **Deterministic Front-End Automata**:
   - Custom DFA Lexer (`src/lexer.py`) for token stream parsing, comment/string literal masking, and keyword classification.
   - Bracket Nesting Stack Automaton (`src/bracket_checker.py`) isolating mismatched syntax before compiler desynchronization.
2. **Native Clang JSON AST Integration**:
   - Leverages `clang++ -Xclang -ast-dump=json` (`src/ast_parser.py`) for complete structural fidelity, resolving exact source-range containment and lexical scopes.
3. **Platt-Calibrated Error Classifier**:
   - Linear SVM with Sigmoid probability calibration achieving **98.1% classification accuracy** across standard compiler diagnostic categories.
4. **Context-Enriched NLP Explainer**:
   - Translates raw compiler jargon into structured plain-English explanations with dynamic AST identifiers and actionable remediation steps.
5. **Static AST Security Analyzer (10 CWE Classes)**:
   - Evaluates memory safety, command injection, and arithmetic vulnerabilities (CWE-78, 120, 134, 190, 369, 401, 415, 416, 457, 476) with **100% precision and recall** on clean binaries.
6. **Multi-Tier Automated Repair Engine**:
   - Deterministic state-machine Planner (`src/planner.py`) driving 3 repair tiers (Compiler Fix-It, AST Rules, Heuristics) categorized by safety levels S0, S1, and S2.
7. **6-Gate Sandboxed Verification Pipeline**:
   - Multi-gate safety gauntlet enforcing recompilation, minimal diff sizing, AST preservation, zero CWE regressions, differential execution equivalence, and patch content security.
8. **Agent Security Defense Layer**:
   - Defends the agent's decision-making against instruction injection, policy bypasses, malicious patches (Gate 6), and validation suppression with tamper-evident atomic logging (`data/agent_security_log.jsonl`).
9. **Dual Interfaces**:
   - Scriptable CLI (`--heal`, `--trace`, `-j`, `-v`, `--batch`) and desktop PyQt6 IDE (`src/gui.py`) with interactive patch review sessions.

---

## Final Headline Results

| Metric | Target | Final Measured Value | Verdict / Parity |
|---|:---:|:---:|:---:|
| **Benchmark Suite Size** | $\ge 75$ | **100 files** (+17 attack files) | Benchmark Complete |
| **Status Accuracy** (Apple Clang / GCC) | $\ge 90.0\%$ | **99.0% (99/100)** / **96.9% (94/97)** | -2.1% transitive header delta |
| **Diagnostic Classification** (Apple Clang / GCC) | $\ge 90.0\%$ | **98.1% (53/54)** / **77.8% (42/54)** | Disclosed -20.3% GCC dialect gap |
| **Security Precision & Recall** (All 10 CWEs) | $1.000$ | **1.000 / 1.000 (19/19)** | **100% Parity** across Clang & GCC |
| **Decoy False Positive Rate** | $0.0\%$ | **0.0% (0/17)** | Zero false alarms |
| **Auto-Healer Success Rate** (Apple Clang / GCC) | $\ge 40.0\%$ | **47.2% (25/53)** / **41.5% (22/53)** | 0 crashes (100% pipeline stability) |
| **Runtime Oracle Correctness** | $100\%$ | **100.0% (24/24)** | All compiled repairs verified |
| **Agent Security Detection & Block Rate** | $100\%$ | **100.0% (12/12)** | 0% decoy FP; 0.042 ms latency |
| **Pytest Unit & Integration Suite** | $100\%$ | **185 / 185 passed (100%)** | Zero regressions |

---

## Quickstart

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/jaisingh5155/Compiler-Error-Explainer-Using-The-AST-And-NLP.git cd1
cd cd1

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Common CLI Commands
```bash
# 1. Analyze and explain a C++ error with source context:
python3 src/main.py benchmark/syntax/sx01_missing_semi_decl.cpp -v

# 2. Automated repair with step-by-step verification trace:
python3 src/main.py benchmark/syntax/sx01_missing_semi_decl.cpp --heal --trace

# 3. Scan a cleanly compiling binary for CWE vulnerabilities:
python3 src/main.py benchmark/security/sec06_double_free.cpp -v

# 4. Demonstrate defensive gate rejection (Gate 1):
python3 src/main.py benchmark/redefinition/rd01_global_var.cpp --heal --trace

# 5. Demonstrate Gate 6 catching an exfiltration backdoor in a patch:
python3 src/main.py benchmark/agent_attacks/attack_patch_01_env_exfil.cpp --heal --trace

# 6. Run batch evaluation across a directory:
python3 src/main.py --batch benchmark/syntax/
```

### 3. Launching the PyQt6 GUI IDE
```bash
python3 src/gui.py
```

### 4. Running the Complete Verification Suite
```bash
# Run the 100-file benchmark suite:
python3 benchmark/run_benchmark.py

# Run all 185 automated tests:
pytest
```

---

## Project Documentation Index

- [`PBL_REPORT_FINAL.md`](PBL_REPORT_FINAL.md): Final consolidated submission-ready project report.
- [`PBL_REPORT_FINAL.docx`](PBL_REPORT_FINAL.docx): Microsoft Word export of the final consolidated report.
- [`PROJECT_DEMO_AND_VERIFICATION_GUIDE.md`](PROJECT_DEMO_AND_VERIFICATION_GUIDE.md): Detailed evaluator feature guide and verification steps.
- [`Project_Demo_and_Verification_Guide.pdf`](Project_Demo_and_Verification_Guide.pdf): PDF evaluation and demonstration guide.
- [`Existing_and_Proposed_Architecture.pdf`](Existing_and_Proposed_Architecture.pdf): Architectural comparison diagrams (Senior's baseline vs. Current system).
- [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md): 10-minute live demonstration presentation script.
- [`AGENT_SECURITY_REPORT.md`](AGENT_SECURITY_REPORT.md): In-depth report on the Agent Security Defense Layer and ADV generalization audit.
- [`GNU_GCC_VERIFICATION_REPORT.md`](GNU_GCC_VERIFICATION_REPORT.md): Empirical dual-compiler comparison against GNU GCC 16.2.0.
- [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md): Transparent technical disclosures and toolchain boundaries.
- [`SETUP.md`](SETUP.md): Step-by-step installation, troubleshooting, and operations guide.

---

## License
Educational and research project for Problem-Based Learning (PBL) in Compiler Design.
