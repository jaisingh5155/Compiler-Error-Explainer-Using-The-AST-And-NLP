import os
import re
import subprocess
from error_classifier import ErrorClassifier
from diagnostic import Diagnostic
from tools.repair import repair
from tools.verify_gates import verify_patch_gates

ERR_PAT = re.compile(r"^(.+?):(\d+):(\d+):\s*(error|warning):\s*(.*)$")

sample_files = [
    "benchmark/syntax/sx01_missing_semi_decl.cpp",
    "benchmark/syntax/sx02_missing_semi_multi.cpp",
    "benchmark/syntax/sx03_missing_brace.cpp",
    "benchmark/syntax/sx04_missing_semi_string.cpp",
    "benchmark/syntax/sx07_unmatched_paren.cpp",
    "benchmark/syntax/sx08_double_semi_func_scope.cpp",
    "benchmark/syntax/sx11_nested_bracket_mismatch.cpp",
    "benchmark/syntax/sx12_brackets_in_string.cpp",
    "benchmark/syntax/sx13_deeply_nested_unclosed.cpp",
    "benchmark/name_resolution/nr02_undeclared_result.cpp",
    "benchmark/name_resolution/nr03_keyword_retrun.cpp",
    "benchmark/name_resolution/nr06_misspelled_ident.cpp",
    "benchmark/name_resolution/nr07_missing_std_prefix.cpp",
    "benchmark/type_errors/te05_wrong_stream_op.cpp",
    "benchmark/redefinition/rd03_local_redef.cpp",
]

clf = ErrorClassifier()

results = []
print("| Patch # | Benchmark Target | Gate 1 (Recompile) | Gate 2 (Diff Size) | Gate 3 (AST Diff) | Gate 4 (Security) | Combined Result |")
print("|---|---|---|---|---|---|---|")

for idx, fpath in enumerate(sample_files, 1):
    with open(fpath) as f:
        orig = f.read()

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
        print(f"| {idx} | `{fpath}` | FAIL (No diag) | - | - | - | **FAIL** |")
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
    if not patch:
        print(f"| {idx} | `{fpath}` | FAIL (No patch) | - | - | - | **FAIL** |")
        continue

    vr = verify_patch_gates(patch, target_diagnostic=diag, original_source=orig)
    g1 = vr["gate1_recompile"]["passed"]
    g2 = vr["gate2_diff_size"]["passed"]
    g3 = vr["gate3_ast_diff"]["passed"]
    g4 = vr["gate4_security_regression"]["passed"]
    all_p = vr["passed"]
    results.append((idx, fpath, g1, g2, g3, g4, all_p))

    p_str = lambda val: "**PASS**" if val else "**FAIL**"
    print(f"| {idx} | `{fpath}` | {p_str(g1)} | {p_str(g2)} | {p_str(g3)} | {p_str(g4)} | {p_str(all_p)} |")

passed_count = sum(1 for r in results if r[6])
print()
print(f"Total passed: {passed_count}/{len(sample_files)}")
