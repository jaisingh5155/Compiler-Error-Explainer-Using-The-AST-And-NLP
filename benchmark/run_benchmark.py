#!/usr/bin/env python3
"""
run_benchmark.py
────────────────
Run the Compiler Error Explainer pipeline against every .cpp in benchmark/
and compare actual outputs against expected metadata.

Outputs:
  - benchmark/BENCHMARK_RESULTS.csv
  - Aggregate summary printed to stdout and saved at the top of the CSV as comments
"""
import csv
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
SRC = os.path.join(PROJECT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

BENCHMARK = os.path.join(PROJECT, "benchmark")
MANIFEST  = os.path.join(BENCHMARK, "manifest.json")
PYTHON    = os.path.join(PROJECT, ".venv", "bin", "python3")
MAIN_PY   = os.path.join(SRC, "main.py")

# ── Collect all benchmark .cpp files with their metadata ──────────
def discover():
    pairs = []
    for dirpath, _, filenames in os.walk(BENCHMARK):
        if "agent_attacks" in dirpath:
            continue
        for fn in sorted(filenames):
            if not fn.endswith(".cpp"):
                continue
            cpp_path = os.path.join(dirpath, fn)
            json_path = cpp_path.replace(".cpp", ".json")
            if not os.path.exists(json_path):
                print(f"WARNING: no metadata for {cpp_path}", file=sys.stderr)
                continue
            with open(json_path) as f:
                meta = json.load(f)
            rel = os.path.relpath(cpp_path, PROJECT)
            category_dir = os.path.relpath(dirpath, BENCHMARK)
            pairs.append((rel, cpp_path, category_dir, meta))
    return pairs

# ── Helper to detect compiler version ────────────────────────────
def get_compiler_version(compiler_binary: str = "clang++") -> str:
    try:
        proc = subprocess.run([compiler_binary, "--version"], capture_output=True, text=True)
        if proc.stdout:
            return proc.stdout.splitlines()[0].strip()
    except Exception:
        pass
    return "unknown"


# ── Run main.py -j on a file ─────────────────────────────────────
def run_pipeline(cpp_path, compiler_override: str = None):
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "ignore"
    if compiler_override:
        env["CXX_OVERRIDE"] = compiler_override
    proc = subprocess.run(
        [PYTHON, MAIN_PY, cpp_path, "-j"],
        capture_output=True, text=True, env=env,
        cwd=PROJECT, timeout=30
    )
    try:
        data = json.loads(proc.stdout)
    except Exception:
        data = None
    return data, proc.returncode, proc.stderr

# ── Extract fields from pipeline JSON ────────────────────────────
def extract_actual(data):
    if data is None:
        return "crash", None, 0.0, "unknown", []

    status = data.get("status", "unknown")

    # Category / confidence from first error
    errors = data.get("errors", [])
    if errors:
        cat = errors[0].get("category", None)
        conf = errors[0].get("confidence", 0.0)
    else:
        cat = None
        conf = 0.0

    # Security verdict
    sec_findings = data.get("security_findings", [])
    sec_report = data.get("security_report", "")
    # Determine if vulnerable based on findings
    if sec_findings:
        # Filter out Low/unused-variable findings for verdict
        real_findings = [f for f in sec_findings
                         if f.get("severity", "") in ("Critical", "High", "Medium")]
        verdict = "vulnerable" if real_findings else "clean"
    else:
        verdict = "clean"

    return status, cat, conf, verdict, sec_findings

# ── Run healer on a file (on a temp copy) ────────────────────────
def run_healer(cpp_path, meta):
    """Run planner with multi-gate verify pipeline on a copy; returns (outcome, planner_result)."""
    from planner import run_planner

    with open(cpp_path) as f:
        original = f.read()

    suffix = os.path.splitext(cpp_path)[1] or ".cpp"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w")
    tmp.write(original)
    tmp.close()
    tmp_path = tmp.name

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
        return outcome, res
    except Exception as ex:
        return f"crashed:{type(ex).__name__}", None
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        bak = tmp_path + ".bak"
        if os.path.exists(bak):
            try:
                os.unlink(bak)
            except OSError:
                pass


# ── Main ──────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run the full benchmark suite.")
    parser.add_argument(
        "--compiler",
        default=None,
        metavar="BINARY",
        help=(
            "Override the compiler binary used for every compile step in this run "
            "(sets CXX_OVERRIDE env var; default: use system g++ as configured). "
            "Example: --compiler=g++-14"
        ),
    )
    args = parser.parse_args()
    compiler_override = args.compiler  # None means use default

    # Determine which binary to query for version string
    if compiler_override:
        compiler_ver = get_compiler_version(compiler_override)
    else:
        compiler_ver = get_compiler_version("clang++")

    pairs = discover()
    print(f"Discovered {len(pairs)} benchmark files (Compiler: {compiler_ver})")
    if compiler_override:
        print(f"  [COMPILER OVERRIDE] Using: {compiler_override} ({compiler_ver})")

    # ── Manifest consistency check ────────────────────────────────
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as mf:
            manifest = json.load(mf)
        expected_total = manifest["denominators"]["total"]
        if len(pairs) != expected_total:
            print(f"\n⚠ MANIFEST MISMATCH: discovered {len(pairs)} files "
                  f"but manifest.json expects {expected_total}.")
            print(f"  Update manifest.json or add missing .json metadata files.")
            print(f"  Continuing with discovered {len(pairs)} files...\n")
        else:
            print(f"  ✓ Manifest check: {len(pairs)} files match manifest.json")
    else:
        print(f"  ⚠ No manifest.json found — denominators computed ad-hoc")
        manifest = None

    # Check if training_data.json gets modified
    td_path = os.path.join(PROJECT, "data", "training_data.json")
    td_hash_before = hashlib.md5(open(td_path, "rb").read()).hexdigest() if os.path.exists(td_path) else None
    td_size_before = os.path.getsize(td_path) if os.path.exists(td_path) else 0

    rows = []
    for rel, cpp_path, cat_dir, meta in pairs:
        print(f"  Running: {rel} ...", end=" ", flush=True)
        try:
            data, rc, stderr = run_pipeline(cpp_path, compiler_override)
        except subprocess.TimeoutExpired:
            data, rc = None, -1
        actual_status, actual_cat, conf, actual_sec, sec_findings = extract_actual(data)

        exp_status = meta.get("expected_status", "")
        exp_cat = meta.get("expected_category")
        exp_sec = meta.get("expected_security_verdict", "clean")
        cwe = meta.get("cwe")

        status_match = (actual_status == exp_status)
        cat_match = (actual_cat == exp_cat) if exp_cat else None
        sec_match = (actual_sec == exp_sec)

        # Run healer on error files only; non-error files are not applicable
        heal_outcome = ""
        planner_res = None
        if exp_status == "error":
            try:
                # Pass compiler override into the healer subprocess environment
                if compiler_override:
                    os.environ["CXX_OVERRIDE"] = compiler_override
                elif "CXX_OVERRIDE" in os.environ:
                    del os.environ["CXX_OVERRIDE"]
                heal_outcome, planner_res = run_healer(cpp_path, meta)
            except Exception as ex:
                heal_outcome = f"crashed:{type(ex).__name__}"
        else:
            heal_outcome = "not_applicable"
            planner_res = None

        gate_failures = ""
        if planner_res and getattr(planner_res, "trace_log", None):
            failures = []
            for e in planner_res.trace_log:
                if e.get("tool_called") == "verify" and e.get("failing_gate"):
                    failures.append(f"{e['failing_gate']}: {e.get('output_summary', '')}")
            gate_failures = "; ".join(failures)

        row = {
            "filepath": rel,
            "category_dir": cat_dir,
            "compiler_version": compiler_ver,
            "cwe": cwe or "",
            "expected_status": exp_status,
            "actual_status": actual_status,
            "status_match": status_match,
            "expected_category": exp_cat or "",
            "actual_category": actual_cat or "",
            "category_match": cat_match if cat_match is not None else "",
            "confidence": round(conf, 4) if conf else "",
            "expected_security_verdict": exp_sec,
            "actual_security_verdict": actual_sec,
            "security_match": sec_match,
            "heal_outcome": heal_outcome,
            "gate_failures": gate_failures,
            "notes": meta.get("notes", ""),
        }
        rows.append(row)
        status_sym = "✓" if status_match else "✗"
        cat_sym = ""
        if cat_match is True:
            cat_sym = " cat:✓"
        elif cat_match is False:
            cat_sym = f" cat:✗({actual_cat})"
        sec_sym = "" if sec_match else f" sec:✗({actual_sec})"
        heal_sym = f" heal:{heal_outcome}" if heal_outcome else ""
        if gate_failures:
            heal_sym += f" [{gate_failures[:40]}...]"
        print(f"{status_sym}{cat_sym}{sec_sym}{heal_sym}")

    # ── Compute aggregates ────────────────────────────────────────
    total = len(rows)
    status_correct = sum(1 for r in rows if r["status_match"])

    cat_rows = [r for r in rows if r["expected_category"]]
    cat_correct = sum(1 for r in cat_rows if r["category_match"] is True)

    sec_rows_vuln = [r for r in rows if r["expected_security_verdict"] == "vulnerable"]
    sec_rows_clean = [r for r in rows if r["expected_security_verdict"] == "clean"]

    sec_tp = sum(1 for r in sec_rows_vuln if r["actual_security_verdict"] == "vulnerable")
    sec_fn = sum(1 for r in sec_rows_vuln if r["actual_security_verdict"] != "vulnerable")
    sec_fp = sum(1 for r in sec_rows_clean if r["actual_security_verdict"] != "clean")
    sec_tn = sum(1 for r in sec_rows_clean if r["actual_security_verdict"] == "clean")

    sec_precision = sec_tp / (sec_tp + sec_fp) if (sec_tp + sec_fp) else 0
    sec_recall = sec_tp / (sec_tp + sec_fn) if (sec_tp + sec_fn) else 0

    # Per-CWE
    cwe_stats = {}
    for r in rows:
        if r["cwe"]:
            cwe_id = r["cwe"]
            if cwe_id not in cwe_stats:
                cwe_stats[cwe_id] = {"tp": 0, "fn": 0}
            if r["actual_security_verdict"] == "vulnerable":
                cwe_stats[cwe_id]["tp"] += 1
            else:
                cwe_stats[cwe_id]["fn"] += 1

    # False positive rate on clean + decoy
    clean_decoy = [r for r in rows if r["category_dir"] in ("clean", "security") and r["expected_security_verdict"] == "clean"]
    fp_count = sum(1 for r in clean_decoy if r["actual_security_verdict"] != "clean")
    fp_rate = fp_count / len(clean_decoy) if clean_decoy else 0

    # Healer stats (evaluated strictly on eligible error files)
    heal_rows = [r for r in rows if r["heal_outcome"] and r["heal_outcome"] != "not_applicable"]
    heal_success = sum(1 for r in heal_rows if r["heal_outcome"] == "compiled_clean")
    heal_gave_up = sum(1 for r in heal_rows if r["heal_outcome"] == "gave_up")
    heal_crashed = sum(1 for r in heal_rows if "crashed" in r["heal_outcome"])

    # training_data.json check
    td_hash_after = hashlib.md5(open(td_path, "rb").read()).hexdigest() if os.path.exists(td_path) else None
    td_size_after = os.path.getsize(td_path) if os.path.exists(td_path) else 0
    td_modified = td_hash_before != td_hash_after

    # ── Print summary ─────────────────────────────────────────────
    today = datetime.date.today().isoformat()
    summary_lines = [
        "# BENCHMARK RESULTS — AGGREGATE SUMMARY",
        f"# Date: {today}",
        f"# Compiler Version: {compiler_ver}",
        f"# Total benchmark files: {total}",
        f"#",
        f"# CANONICAL DENOMINATORS (from manifest/metadata):",
        f"#   Total files (Status denominator):         {total}",
        f"#   Classification denominator:               {len(cat_rows)} (files with expected_category)",
        f"#   Security denominator (vulnerable/clean):  {sec_tp + sec_fn} vulnerable / {len(clean_decoy)} clean/decoy",
        f"#   Auto-Healer denominator:                  {len(heal_rows)} (error files eligible for healing)",
        f"#",
        f"# STATUS ACCURACY: {status_correct}/{total} ({100*status_correct/total:.1f}%)",
        f"# CLASSIFICATION ACCURACY: {cat_correct}/{len(cat_rows)} ({100*cat_correct/len(cat_rows):.1f}%)" if cat_rows else "# CLASSIFICATION ACCURACY: N/A",
        f"#",
        f"# SECURITY SCANNER:",
        f"#   True Positives:  {sec_tp}",
        f"#   False Negatives: {sec_fn}",
        f"#   False Positives: {sec_fp}",
        f"#   True Negatives:  {sec_tn}",
        f"#   Precision: {sec_precision:.3f}",
        f"#   Recall:    {sec_recall:.3f}",
        f"#   FP rate on clean/decoy files: {fp_count}/{len(clean_decoy)} ({100*fp_rate:.1f}%)",
        f"#",
        f"# PER-CWE RECALL:",
    ]
    for cwe_id in sorted(cwe_stats.keys()):
        s = cwe_stats[cwe_id]
        recall = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) else 0
        summary_lines.append(f"#   {cwe_id}: {s['tp']}/{s['tp']+s['fn']} ({100*recall:.0f}%)")
    summary_lines += [
        f"#",
        f"# AUTO-HEALER:",
        f"#   Attempted:      {len(heal_rows)}",
        f"#   compiled_clean:  {heal_success}",
        f"#   gave_up:         {heal_gave_up}",
        f"#   crashed:         {heal_crashed}",
        f"#   success rate:    {100*heal_success/len(heal_rows):.1f}%" if heal_rows else "#   success rate: N/A",
        f"#",
        f"# TRAINING DATA MUTATION CHECK:",
        f"#   Size before: {td_size_before} bytes, MD5: {td_hash_before}",
        f"#   Size after:  {td_size_after} bytes, MD5: {td_hash_after}",
        f"#   Modified by benchmark run: {'YES — DATA LEAK!' if td_modified else 'No (safe)'}",
        f"#",
    ]

    for line in summary_lines:
        print(line)

    # ── Write CSV ─────────────────────────────────────────────────
    csv_path = os.path.join(BENCHMARK, "BENCHMARK_RESULTS.csv")
    if compiler_override:
        # Save GCC run to a separate file to avoid overwriting the canonical Clang results
        safe_name = compiler_override.replace("/", "_").replace(" ", "_")
        csv_gcc_path = os.path.join(BENCHMARK, f"BENCHMARK_RESULTS_GCC_{safe_name}.csv")
        out_paths = [csv_gcc_path]
        print(f"\n[Override] Results written to {csv_gcc_path} (canonical CSV untouched)")
    else:
        csv_week8_path = os.path.join(BENCHMARK, "BENCHMARK_RESULTS_WEEK8.csv")
        out_paths = [csv_path, csv_week8_path]
    fieldnames = [
        "filepath", "category_dir", "compiler_version", "cwe",
        "expected_status", "actual_status", "status_match",
        "expected_category", "actual_category", "category_match",
        "confidence",
        "expected_security_verdict", "actual_security_verdict", "security_match",
        "heal_outcome", "gate_failures", "notes"
    ]
    for out_p in out_paths:
        with open(out_p, "w", newline="") as f:
            for line in summary_lines:
                f.write(line + "\n")
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    if not compiler_override:
        print(f"\nResults written to {csv_path} and {os.path.join(BENCHMARK, 'BENCHMARK_RESULTS_WEEK8.csv')}")
    return rows, summary_lines

if __name__ == "__main__":
    main()
