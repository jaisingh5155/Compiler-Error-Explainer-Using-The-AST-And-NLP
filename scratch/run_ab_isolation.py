#!/usr/bin/env python3
"""
scratch/run_ab_isolation.py
A/B Isolation Test:
Run all 56 error benchmark targets through run_planner twice:
- Run A: Gates forced to pass (gates_disabled=True, verify accepts any patch)
- Run B: Real validation gates (gates_disabled=False, full multi-gate pipeline)
"""

import os
import sys
import json
import tempfile
import time

PROJECT = "/Users/jaisinghsaini/TOACD/cd1"
SRC = os.path.join(PROJECT, "src")
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import tools.verify_gates as vg_mod
import tools.verify as v_mod
import planner as planner_mod
from planner import run_planner

def discover_56_targets():
    benchmark_dir = os.path.join(PROJECT, "benchmark")
    targets = []
    for root, _, files in os.walk(benchmark_dir):
        for f in sorted(files):
            if f.endswith(".json"):
                jpath = os.path.join(root, f)
                cpath = jpath[:-5] + ".cpp"
                if not os.path.exists(cpath):
                    continue
                try:
                    with open(jpath) as jf:
                        meta = json.load(jf)
                    if meta.get("expected_status") == "error":
                        rel = os.path.relpath(cpath, PROJECT)
                        targets.append((rel, cpath, meta))
                except Exception:
                    pass
    return sorted(targets, key=lambda x: x[0])

def run_target(cpath, force_gates_pass=False):
    with open(cpath) as f:
        src = f.read()

    tmp = tempfile.NamedTemporaryFile(suffix=".cpp", delete=False, mode="w")
    tmp.write(src)
    tmp.close()
    tmp_path = tmp.name

    import sys
    v_mod = sys.modules["tools.verify"]
    original_verify = v_mod.verify
    original_verify_gates = vg_mod.verify_patch_gates

    if force_gates_pass:
        def _forced_verify(*args, **kwargs):
            res = original_verify(*args, **kwargs)
            res.passed = True
            res.failing_gate = None
            res.failing_reason = None
            return res

        v_mod.verify = _forced_verify
        planner_mod.verify = _forced_verify
    else:
        v_mod.verify = original_verify
        planner_mod.verify = original_verify

    try:
        res = run_planner(tmp_path, max_iterations=10, backup=True)
        if res.clean:
            outcome = "compiled_clean"
        elif res.status == "no_fixable_finding":
            outcome = "gave_up"
        elif res.status == "max_iterations":
            outcome = "exhausted"
        else:
            outcome = res.status
        
        applied_count = len(res.patches_applied)
        suggested_count = len(res.suggestions)
        failing_gates = []
        for e in res.trace_log:
            if e.get("failing_gate"):
                failing_gates.append(e["failing_gate"])
                
        return outcome, applied_count, suggested_count, failing_gates
    finally:
        v_mod.verify = original_verify
        planner_mod.verify = original_verify
        for p in [tmp_path, tmp_path + ".bak"]:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass

def main():
    targets = discover_56_targets()
    print(f"Discovered {len(targets)} error targets (expected 56).")

    print("\n--- RUNNING RUN A: GATES FORCED TO PASS (Gates Disabled) ---")
    start_a = time.time()
    results_a = {}
    for rel, cpath, meta in targets:
        outcome, applied, sugg, fg = run_target(cpath, force_gates_pass=True)
        results_a[rel] = (outcome, applied, sugg, fg)
        print(f"  [OFF] {rel} -> {outcome} (applied={applied}, sugg={sugg})")
    time_a = time.time() - start_a

    print(f"\n--- RUNNING RUN B: REAL GATES PIPELINE (Gates Enabled) ---")
    start_b = time.time()
    results_b = {}
    for rel, cpath, meta in targets:
        outcome, applied, sugg, fg = run_target(cpath, force_gates_pass=False)
        results_b[rel] = (outcome, applied, sugg, fg)
        fg_str = f" [failed: {', '.join(fg)}]" if fg else ""
        print(f"  [ON ] {rel} -> {outcome} (applied={applied}, sugg={sugg}){fg_str}")
    time_b = time.time() - start_b

    # Analysis
    clean_a = sum(1 for o, _, _, _ in results_a.values() if o == "compiled_clean")
    clean_b = sum(1 for o, _, _, _ in results_b.values() if o == "compiled_clean")

    patched_a = sum(1 for _, app, sug, _ in results_a.values() if (app + sug) > 0)
    patched_b = sum(1 for _, app, sug, _ in results_b.values() if (app + sug) > 0)

    print("\n" + "=" * 60)
    print("A/B ISOLATION TEST SUMMARY")
    print("=" * 60)
    print(f"Total error benchmark files: {len(targets)}")
    print(f"Gates Disabled (Forced Pass): {clean_a}/56 compiled_clean (patches generated for {patched_a} files)")
    print(f"Gates Enabled  (Real Gates) : {clean_b}/56 compiled_clean (patches generated for {patched_b} files)")
    print(f"Difference (Gate Rejection) : {clean_a - clean_b} files rejected by gates (gates_on <= gates_off)")

    print("\nFiles that differ between Gates Disabled and Gates Enabled:")
    diff_count = 0
    for rel in sorted(results_a.keys()):
        oa, app_a, sug_a, _ = results_a[rel]
        ob, app_b, sug_b, fg = results_b[rel]
        if oa != ob:
            diff_count += 1
            print(f"  * {rel}: {oa} -> {ob} | Failing Gates: {fg}")
    if diff_count == 0:
        print("  (None)")

    # Save results to json for reporting
    out_data = {
        "targets_count": len(targets),
        "clean_gates_off": clean_a,
        "clean_gates_on": clean_b,
        "patched_gates_off": patched_a,
        "patched_gates_on": patched_b,
        "rejected_by_gates": clean_a - clean_b,
        "results_a": {k: {"outcome": v[0], "applied": v[1], "suggested": v[2]} for k, v in results_a.items()},
        "results_b": {k: {"outcome": v[0], "applied": v[1], "suggested": v[2], "failing_gates": v[3]} for k, v in results_b.items()},
    }
    with open("scratch/ab_results.json", "w") as jf:
        json.dump(out_data, jf, indent=2)
    print("\nSaved detailed results to scratch/ab_results.json")

if __name__ == "__main__":
    main()
