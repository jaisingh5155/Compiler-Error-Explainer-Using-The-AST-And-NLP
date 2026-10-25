import os, json, tempfile
from planner import run_planner
from sandbox import compile_sandboxed, execute_sandboxed

targets = [
    'benchmark/missing_include/mi01_iostream.cpp',
    'benchmark/missing_include/mi02_vector.cpp',
    'benchmark/missing_include/mi03_string.cpp',
    'benchmark/missing_include/mi04_map.cpp',
    'benchmark/missing_include/mi05_vector_standalone.cpp',
    'benchmark/missing_include/mi06_algorithm_sort.cpp',
    'benchmark/missing_include/mi07_utility_pair.cpp',
    'benchmark/multi_error/me02_syntax_and_missing_include.cpp',
    'benchmark/multi_error/me03_multiple_missing_includes.cpp',
    'benchmark/multi_error/me06_cascade_semicolons.cpp',
    'benchmark/multi_error/me07_cascade_class_errors.cpp',
    'benchmark/name_resolution/nr02_undeclared_var.cpp',
    'benchmark/name_resolution/nr03_std_cout.cpp',
    'benchmark/name_resolution/nr06_misspelled_ident.cpp',
    'benchmark/name_resolution/nr07_missing_std_prefix.cpp',
    'benchmark/redefinition/rd03_redeclared_var.cpp',
    'benchmark/return_type/rt02_void_main.cpp',
    'benchmark/return_type/rt03_void_with_return.cpp',
    'benchmark/syntax/sx01_missing_semi_decl.cpp',
    'benchmark/syntax/sx02_missing_semi_stmt.cpp',
    'benchmark/syntax/sx03_missing_closing_brace.cpp',
    'benchmark/syntax/sx04_missing_closing_paren.cpp',
    'benchmark/syntax/sx06_extra_semi_struct.cpp',
    'benchmark/syntax/sx07_unbalanced_brackets.cpp',
    'benchmark/syntax/sx08_missing_colon_switch.cpp',
    'benchmark/type_errors/te05_stream_op_wrong_dir.cpp',
]

for f in targets:
    with open(f) as fp:
        orig = fp.read()
    tmp = tempfile.NamedTemporaryFile(suffix='.cpp', delete=False, mode='w')
    tmp.write(orig)
    tmp.close()
    res = run_planner(tmp.name, max_iterations=5, backup=True)
    if res.clean:
        # compile
        c_res = compile_sandboxed(res.model.source_code)
        if c_res.success and c_res.executable_path:
            e_res = execute_sandboxed(c_res.executable_path)
            stdout = e_res.stdout
            print(f"FILE: {f}")
            print(f"  returncode: {e_res.returncode}")
            print(f"  stdout: {repr(stdout)}")
            if os.path.exists(c_res.executable_path):
                os.unlink(c_res.executable_path)
        else:
            print(f"FILE: {f} COMPILE FAILED: {c_res.stderr}")
    else:
        print(f"FILE: {f} PLANNER FAILED: {res.status}")
    for p in [tmp.name, tmp.name + '.bak']:
        if os.path.exists(p): os.unlink(p)
