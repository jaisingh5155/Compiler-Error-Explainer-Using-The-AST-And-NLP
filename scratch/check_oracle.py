import os, json, tempfile, shutil
from planner import run_planner
from sandbox import compile_sandboxed, execute_sandboxed

# All 28 cleanly healed targets
healed_files = [
    'benchmark/missing_include/mi01_iostream.cpp',
    'benchmark/missing_include/mi02_vector.cpp',
    'benchmark/missing_include/mi03_string.cpp',
    'benchmark/missing_include/mi04_map.cpp',
    'benchmark/missing_include/mi05_vector_standalone.cpp',
    'benchmark/missing_include/mi06_algorithm_sort.cpp',
    'benchmark/missing_include/mi07_utility_pair.cpp',
    'benchmark/multi_error/me02_redef_and_security.cpp',
    'benchmark/multi_error/me03_missing_include_and_uaf.cpp',
    'benchmark/multi_error/me06_cascade_semicolons.cpp',
    'benchmark/multi_error/me07_cascade_class_errors.cpp',
    'benchmark/name_resolution/nr02_undeclared_result.cpp',
    'benchmark/name_resolution/nr03_keyword_retrun.cpp',
    'benchmark/name_resolution/nr06_misspelled_ident.cpp',
    'benchmark/name_resolution/nr07_missing_std_prefix.cpp',
    'benchmark/redefinition/rd03_local_redef.cpp',
    'benchmark/return_type/rt02_void_main.cpp',
    'benchmark/syntax/sx01_missing_semi_decl.cpp',
    'benchmark/syntax/sx02_missing_semi_multi.cpp',
    'benchmark/syntax/sx03_missing_brace.cpp',
    'benchmark/syntax/sx04_missing_semi_string.cpp',
    'benchmark/syntax/sx06_extra_semi_struct.cpp',
    'benchmark/syntax/sx07_unmatched_paren.cpp',
    'benchmark/syntax/sx08_double_semi_func_scope.cpp',
    'benchmark/syntax/sx11_nested_bracket_mismatch.cpp',
    'benchmark/syntax/sx12_brackets_in_string.cpp',
    'benchmark/syntax/sx13_deeply_nested_unclosed.cpp',
    'benchmark/type_errors/te05_wrong_stream_op.cpp',
]

results = []

for rel in healed_files:
    if not os.path.exists(rel):
        print(f"NOT FOUND: {rel}")
        continue
    with open(rel) as f:
        src = f.read()

    tmp = tempfile.NamedTemporaryFile(suffix='.cpp', delete=False, mode='w')
    tmp.write(src)
    tmp.close()
    
    res = run_planner(tmp.name, max_iterations=5, backup=True)
    if not res.clean:
        print(f"{rel}: Planner did not heal ({res.status})")
        for p in [tmp.name, tmp.name + '.bak']:
            if os.path.exists(p): os.unlink(p)
        continue

    patched_code = res.model.source_code
    for p in [tmp.name, tmp.name + '.bak']:
        if os.path.exists(p): os.unlink(p)

    c_res = compile_sandboxed(patched_code, keep_temp=True)
    if not c_res.success or not c_res.executable_path:
        print(f"{rel}: Compilation in sandbox failed")
        continue

    # Execute
    # For te05, it needs stdin
    stdin_data = "25\n" if "te05" in rel else None
    e_res = execute_sandboxed(c_res.executable_path, input_data=stdin_data)

    print(f"=== {rel} ===")
    print(f"  Returncode: {e_res.returncode}")
    print(f"  Stdout    : {repr(e_res.stdout)}")
    print(f"  Stderr    : {repr(e_res.stderr)}")
    
    results.append({
        "filepath": rel,
        "stdout": e_res.stdout,
        "returncode": e_res.returncode,
        "needs_stdin": stdin_data is not None,
        "stdin": stdin_data,
    })

    if c_res.sandbox_dir:
        shutil.rmtree(c_res.sandbox_dir, ignore_errors=True)

with open("scratch/healed_outputs.json", "w") as out_f:
    json.dump(results, out_f, indent=2)
print(f"\nSaved {len(results)} outputs to scratch/healed_outputs.json")
