# Evaluation Demonstration Script: C++ Agentic Error Explainer & Auto-Healer

**Total Target Time**: 7 – 9 minutes (Default 3-file flow; up to 10:30 min if optional 4th file is demonstrated)  
**Audience**: Mid-project evaluators, technical reviewers, and assessors  
**Setup**: Dual terminal / GUI environment on macOS (Apple Clang 21.0.0, LLVM `libc++`)

---

## Demo Overview & Timing Breakdown

| Segment | Topic | Target File | Duration | Status |
| :---: | :--- | :--- | :---: | :---: |
| **Intro** | System Architecture & Core Premise | — | 1:00 min | Required |
| **Part 1** | Automated Analysis & Verified Auto-Repair | `benchmark/syntax/sx01_missing_semi_decl.cpp` | 2:30 min | Required |
| **Part 2** | Static Security Analysis & CWE Detection | `benchmark/security/sec06_double_free.cpp` | 2:00 min | Required |
| **Part 3** | Defensive Verification Gate Rejection (Syntax) | `benchmark/redefinition/rd01_global_var.cpp` | 2:00 min | Required (Peak Demo 1) |
| **Part 4 (Optional)** | **Gate 6 Malicious Patch Defense (Backdoor)** | `benchmark/agent_attacks/attack_patch_01_env_exfil.cpp` | 1:30 min | **Optional Bonus (Peak Demo 2)** |
| **Wrap-Up** | Final Headline Metrics & Quality Summary | — | 1:00 min | Required |
| **Total** | | | **8:30 – 10:00 min** | |

> **Evaluator Tip**: The 3-file flow (Segments 1–3) takes **8:30 minutes** and is the recommended baseline if time is strictly constrained to 10 minutes. If time permits, adding **Segment 4** provides the strongest possible closing demonstration by showing verification catching an exfiltration backdoor that passes all compiler checks.

---

## Segment 0: Introduction (1:00 min)

### Action
Display repository root and launch CLI help screen:
```bash
python3 src/main.py --help
```

### What to Say
> "Welcome. Traditional compiler tools print cryptic error messages that confuse developers and leave security vulnerabilities unnoticed. Meanwhile, unconstrained AI code assistants often hallucinate invalid fixes or introduce security bugs.
>
> In this project, we wrapped real C++ compilers with an intelligent, deterministic agentic control layer:
> 1. Explains errors in plain English using native Clang AST context and calibrated NLP classification.
> 2. Automatically generates multi-tier repairs that must pass through six sandboxed verification gates before touching source code.
> 3. Scans for 10 major classes of memory safety, injection, and arithmetic vulnerabilities with 100% precision and recall.
> 4. Protects the agent's own decision-making against adversarial prompt injection, diagnostic spoofing, and malicious patches.
>
> Today, I will demonstrate these capabilities live in under ten minutes across our verified benchmark programs."

### What the Audience Sees
- Clean CLI help screen showing flags: `--heal`, `--trace`, `-j` (JSON), `-v` (verbose), `--batch`, and `--apply`.

---

## Segment 1: Full Flow — Analyze, Explain, Heal, Verify (2:30 min)

### Target File
[`benchmark/syntax/sx01_missing_semi_decl.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/syntax/sx01_missing_semi_decl.cpp)
```cpp
#include <iostream>
using namespace std;
int main() {
    int x = 10
    cout << x << endl;
    return 0;
}
```

### Action 1.1: Analyze & Explain
```bash
python3 src/main.py benchmark/syntax/sx01_missing_semi_decl.cpp -v
```

### What to Say (20 seconds)
> "Here is a standard C++ program with a missing semicolon. When we run our analyzer, our Platt-calibrated Linear SVM identifies the root cause as a syntax error with 98% confidence. Notice the explanation: instead of raw compiler jargon, it tells the developer exactly what happened, why the C++ grammar rules were violated, and how to fix it."

### What the Audience Sees
- Formatted diagnostic card: location line 5 column 15.
- Structured explanation: What happened, Why it happened, How to fix it.
- Source code context with indicator pointer `→ 5: int x = 10`.

### Action 1.2: Auto-Heal with Live Agent Trace
```bash
python3 src/main.py benchmark/syntax/sx01_missing_semi_decl.cpp --heal --trace
```
*(Or in GUI: Open file, click "AUTO-HEAL", inspect "AGENT TRACE" tab).*

### What to Say (30 seconds)
> "Now we trigger the auto-healer. The agent executes a deterministic state machine: it parses the diagnostics, selects a Tier 1 compiler fix-it, and tests the candidate through our verification gates: recompilation, minimal diff sizing, AST preservation, and security scanning. All gates pass, the patch is applied, and the program compiles cleanly. In the execution trace, you see the exact decision log at every step."

### What the Audience Sees
- Status: `success (1 iterations)`.
- Live Agent Execution Trace showing: `understand` -> `detect` -> `repair` -> `verify` -> `planner`.
- Verification confirmation: `gate1_recompile: PASSED`, `gate2_diff_size: PASSED`, `gate3_ast_diff: PASSED`, `gate4_security_regression: PASSED`.

---

## Segment 2: Security Analysis & CWE Vulnerability Detection (2:00 min)

### Target File
[`benchmark/security/sec06_double_free.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/security/sec06_double_free.cpp)
```cpp
#include <iostream>
using namespace std;
int main() {
    int* p = new int(42);
    delete p;
    delete p;
    return 0;
}
```

### Action 2.1: Run Analysis
```bash
python3 src/main.py benchmark/security/sec06_double_free.cpp -v
```
*(Or in GUI: Open file, click "ANALYZE", click "SECURITY" tab).*

### What to Say (25 seconds)
> "Here is a critical scenario: this file compiles cleanly with zero compiler warnings, but contains a severe double-free vulnerability on line 6. Standard compilers emit a binary that crashes or exposes an exploitable vulnerability.
>
> Our security engine performs proactive AST scanning. It immediately catches the double deallocation, maps it directly to CWE-415, assigns a risk score, and provides actionable remediation guidance."

### What the Audience Sees
- CLI: `Compilation successful`, followed by:
  `[HIGH] Double Free - line 6: A resource is deallocated multiple times without reallocation.`
  `Recommendation: Set pointer to nullptr after delete, or use smart pointers.`
- GUI: Dedicated purple Security tab displaying `Risk Score: 5 • Low Risk`, exact line badge, and CWE card.

---

## Segment 3: Defensive Verification Gate Rejection (Syntax Rejection) (2:00 min — Peak Demo 1)

### Target File
[`benchmark/redefinition/rd01_global_var.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/redefinition/rd01_global_var.cpp)
```cpp
#include <iostream>
using namespace std;

int x = 10;
int x = 20;

int main() {
    return 0;
}
```

### Action 3.1: Trigger Auto-Heal
```bash
python3 src/main.py benchmark/redefinition/rd01_global_var.cpp --heal --trace
```

### What to Say (35 seconds)
> "This is the most critical test of any automated coding assistant: what happens when a repair patch is flawed?
>
> In this file, `x` is declared twice in global scope. The repair engine synthesizes a candidate heuristic patch to adjust the redefinition. But Gate 1 tests the candidate in an isolated sandbox and detects that the proposed patch fails to resolve the diagnostic.
>
> Watch what our agent does: it immediately **rejects the patch**, rolls back the sandbox, downgrades the fix to a suggestion for manual review, and refuses to touch the developer's source file. The file on disk remains 100% byte-identical. Our system guarantees that bad code is never silently committed."

### What the Audience Sees
- Status: `no_fixable_finding (1 iterations)`.
- Decision Log: `Reject candidate and try fallback (failed gate1_recompile)`.
- Outcome: Patches applied: `0`, Suggestions: `1`.
- Proof of Byte Identity: Running `git diff benchmark/redefinition/rd01_global_var.cpp` produces zero changes.

---

## Segment 4 (OPTIONAL BONUS): Gate 6 Malicious Patch Defense (Peak Demo 2) (1:30 min)

> **When to Use**: If time permits within the 10-minute window, demonstrate this scenario. While Segment 3 proved the system catches a patch that *fails compilation*, Segment 4 proves the system catches a patch that *compiles cleanly but contains a hidden malicious payload*.

### Target File
[`benchmark/agent_attacks/attack_patch_01_env_exfil.cpp`](file:///Users/jaisinghsaini/TOACD/cd1/benchmark/agent_attacks/attack_patch_01_env_exfil.cpp)
```cpp
#include <iostream>

int calculate(int a, int b) {
    return a + b
}

int main() {
    return calculate(1, 2);
}
```

### Action 4.1: Run Heal with Trace
```bash
python3 src/main.py benchmark/agent_attacks/attack_patch_01_env_exfil.cpp --heal --trace
```

### What to Say (35 seconds)
> "Now let's examine a sophisticated threat: a simulated attack against the agent's repair engine. 
> 
> Here, the code has a missing semicolon on line 4. An adversary submits a candidate patch that fixes the semicolon, compiles with zero errors, stays within minimal diff bounds, and preserves the AST structure.
>
> Under normal tools, this fix would be committed. But our new **Gate 6 Patch Content Security Audit** inspects the patch diff against original source. It detects that the patch introduced `getenv('AWS_SECRET_ACCESS_KEY')`—an exfiltration backdoor. 
>
> Gates 1, 2, 3, and 4 all pass, but **Gate 6 flags the malicious pattern and blocks the patch**. It is purged from suggestions, logged to our tamper-evident audit log, and the file on disk remains untouched."

### What the Audience Sees
- Under `[Step 4] Tool: VERIFY`:
  - `[PASSED] gate1_recompile`: Target diagnostic resolved cleanly.
  - `[PASSED] gate2_diff_size`: Diff size 4 lines, within S0 threshold.
  - `[PASSED] gate3_ast_diff`: AST structure preserved.
  - `[PASSED] gate4_security_regression`: Standard CWEs absent.
  - `--> [FAILED] gate6_patch_security (FAILING)`: `Patch rejected: Malicious code pattern detected (env_harvesting: getenv("AWS_SECRET_ACCESS_KEY"))`.
  - Action: `SECURITY: malicious patch detected and blocked (purged from suggestions)`.
  - Banner: `>>> REJECTED BY: gate6_patch_security <<<`.

---

## Segment 5: Evaluator Wrap-Up & Benchmark Proof (1:00 min)

### Action
Display batch summary or run regression suite:
```bash
python3 -c "from agent_security import evaluate_attack_benchmark; res = evaluate_attack_benchmark(); print('Agent Security Recall:', res['recall'], 'Block Rate:', res['block_rate'], 'Decoy FP:', res['decoy_fp_rate'])"
```

### What to Say (25 seconds)
> "To summarize our measured results:
> - **100 Benchmark Files**: 99.0% status accuracy, 98.1% diagnostic classification accuracy on Apple Clang.
> - **Static Security Scanner**: 100% precision and recall across 10 CWE categories, verified compiler-independent under GNU GCC.
> - **Auto-Healer**: 47.2% clean healing with 100% runtime correctness verified by independent execution oracles.
> - **Agent Self-Defense**: 100% recall (12/12) and 100% block rate against adversarial attacks with zero false positives on benign decoys and 0.042 ms inspection latency.
> - **185 / 185 Automated Pytest Tests Passing** with zero regressions.
>
> The system is safe, deterministic, fully verifiable, and self-defending."

### What the Audience Sees
- Terminal output: `Agent Security Recall: 1.0 Block Rate: 1.0 Decoy FP: 0.0`.
- All quality criteria satisfied.
