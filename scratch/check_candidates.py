import sys
import os
import tempfile
from planner import run_planner

targets = [
    ("nr04", "benchmark/name_resolution/nr04_keyword_cosnt.cpp"),
    ("me01", "benchmark/multi_error/me01_syntax_and_type.cpp"),
    ("rd01", "benchmark/redefinition/rd01_global_var.cpp"),
    ("rd02", "benchmark/redefinition/rd02_duplicate_func.cpp")
]

for label, t in targets:
    with tempfile.NamedTemporaryFile(suffix=".cpp", delete=False, mode="w") as tmp:
        with open(t) as f:
            tmp.write(f.read())
        tmp_path = tmp.name

    try:
        res = run_planner(tmp_path, max_iterations=4)
        print(f"=== {label}: {t} ===")
        print(f"Status: {res.status}, Clean: {res.clean}")
        print(f"Patches applied: {len(res.patches_applied)}, Suggestions: {len(res.suggestions)}")
        for step in res.trace_log:
            tool = step.get("tool_called", "")
            act = step.get("action", "")
            cand_gates = step.get("candidate_gate_outcomes", [])
            gate_det = step.get("gate_details", [])
            fg = step.get("failing_gate")
            if tool == "repair":
                print(f"  Repair: {step.get('input_summary', '')} -> {step.get('output_summary', '')}")
            elif tool == "verify":
                print(f"  Verify: {step.get('input_summary', '')} -> {step.get('output_summary', '')} [failing={fg}]")
            elif cand_gates:
                for c in cand_gates:
                    passed = c.get("passed")
                    cfg = c.get("failed_gate")
                    reas = c.get("reason", "")[:50]
                    print(f"    Cand: tier={c.get('tier')} passed={passed} fail_gate={cfg} reason={reas}")
    finally:
        for p in [tmp_path, tmp_path + ".bak"]:
            if os.path.exists(p):
                os.unlink(p)
