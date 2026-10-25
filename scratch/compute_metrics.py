import os
import sys
import time
import subprocess
import tempfile
import re
from error_classifier import ErrorClassifier
from diagnostic import Diagnostic
from tools.repair import repair
from diff_viewer import compute_diff
from sandbox import compile_sandboxed

ERR_PAT = re.compile(r"^(.+?):(\d+):(\d+):\s*(error|warning):\s*(.*)$")

# Part A: Measure per-compile sandbox overhead over 20 benchmark files
all_benchmark_files = []
for root, dirs, files in os.walk("benchmark"):
    for f in sorted(files):
        if f.endswith(".cpp") and not f.startswith("."):
            all_benchmark_files.append(os.path.join(root, f))

sample_20 = all_benchmark_files[:20]
unsandboxed_times = []
sandboxed_times = []

for fpath in sample_20:
    with open(fpath) as f:
        src = f.read()

    # Unsandboxed compile
    with tempfile.NamedTemporaryFile("w", suffix=".cpp") as tmp:
        tmp.write(src)
        tmp.flush()
        t0 = time.perf_counter()
        subprocess.run(
            ["g++", "-std=c++17", tmp.name, "-o", "/dev/null"],
            capture_output=True, text=True
        )
        t1 = time.perf_counter()
        unsandboxed_times.append((t1 - t0) * 1000.0)

    # Sandboxed compile
    t0 = time.perf_counter()
    compile_sandboxed(src, compiler="g++", extra_flags=["-std=c++17"])
    t1 = time.perf_counter()
    sandboxed_times.append((t1 - t0) * 1000.0)

mean_unsandboxed = sum(unsandboxed_times) / len(unsandboxed_times)
mean_sandboxed = sum(sandboxed_times) / len(sandboxed_times)
overhead = mean_sandboxed - mean_unsandboxed

print("=== SANDBOX COMPILE OVERHEAD (20 benchmark files) ===")
print(f"Mean Unsandboxed Compile: {mean_unsandboxed:.2f} ms")
print(f"Mean Sandboxed Compile:   {mean_sandboxed:.2f} ms")
print(f"Mean Overhead:            {overhead:+.2f} ms ({(overhead/mean_unsandboxed)*100:.1f}%)")
print()

# Part B: Gate 2 diff-size across all 56 repair patches
clf = ErrorClassifier()

# Repair benchmark categories typically include syntax, name_resolution, type_errors, redefinition, missing_include, return_type, multi_error
repair_dirs = [
    "benchmark/syntax",
    "benchmark/name_resolution",
    "benchmark/type_errors",
    "benchmark/redefinition",
    "benchmark/missing_include",
    "benchmark/return_type",
    "benchmark/multi_error",
]

repair_files = []
for d in repair_dirs:
    if os.path.exists(d):
        for f in sorted(os.listdir(d)):
            if f.endswith(".cpp"):
                repair_files.append(os.path.join(d, f))

# Limit to 56 repair targets
repair_files = repair_files[:56]
print(f"Found {len(repair_files)} repair benchmark target files.")

diffs_by_level = {"S0": [], "S1": [], "S2": []}

for fpath in repair_files:
    with open(fpath) as f:
        src = f.read()

    proc = subprocess.run(
        ["g++", "-std=c++17", "-Wall", fpath, "-o", "/dev/null"],
        capture_output=True, text=True
    )
    errors = []
    for line in proc.stderr.splitlines():
        m = ERR_PAT.match(line.strip())
        if m:
            errors.append({
                "file": m.group(1), "line": int(m.group(2)),
                "column": int(m.group(3)), "type": m.group(4),
                "message": m.group(5), "raw": line
            })

    target = next((e for e in errors if e["type"] == "error"), None)
    if not target:
        target = next((e for e in errors if e["type"] == "warning"), None)

    if not target:
        continue

    cat, conf = clf.predict(target["message"])
    diag = Diagnostic(
        file=fpath,
        line=target["line"],
        column=target["column"],
        kind=target["type"],
        message=target["message"],
        raw=target["raw"],
        category=cat,
        confidence=conf,
    )

    patch = repair(fpath, diag)
    if patch and patch.patched_source:
        diff_lines = compute_diff(src, patch.patched_source)
        modified = sum(1 for d in diff_lines if d.kind in ("+", "-"))
        level = patch.safety_level or "S0"
        if level not in diffs_by_level:
            diffs_by_level[level] = []
        diffs_by_level[level].append(modified)

print("=== GATE 2 DIFF-SIZE DISTRIBUTION (across 56 repair targets) ===")
total_patches = sum(len(v) for v in diffs_by_level.values())
print(f"Total Patches Produced: {total_patches}")
for level in ["S0", "S1", "S2"]:
    sizes = diffs_by_level.get(level, [])
    if sizes:
        min_s = min(sizes)
        max_s = max(sizes)
        mean_s = sum(sizes) / len(sizes)
        print(f"Level {level} (n={len(sizes)}): min={min_s}, max={max_s}, mean={mean_s:.2f} lines modified")
    else:
        print(f"Level {level} (n=0): N/A")
