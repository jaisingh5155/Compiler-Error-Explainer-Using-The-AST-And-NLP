import subprocess
import re
import os

def _sanitize_code(source: str, permissions: dict = None) -> bool:
    if permissions is None:
        permissions = {
            "allow_system_calls": os.environ.get("ALLOW_SYSTEM_CALLS") == "1",
            "allow_assembly": os.environ.get("ALLOW_ASSEMBLY") == "1",
            "allow_sys_includes": os.environ.get("ALLOW_SYS_INCLUDES") == "1",
        }
    
    dangerous_patterns = []

    try:
        from config_loader import get as cfg_get
        blocked = cfg_get("security", "blocked_patterns") or {}
    except Exception:
        blocked = {}

    system_calls = blocked.get("system_calls", [r'\bsystem\s*\(', r'\bexec\s*\(', r'\bpopen\s*\(', r'\bfork\s*\('])
    assembly = blocked.get("assembly", [r'\b__asm__\b', r'\bshellcode\b'])
    sys_includes = blocked.get("sys_includes", [r'#include\s*[<"]\s*sys/'])

    if not permissions.get("allow_system_calls", False):
        dangerous_patterns.extend(system_calls)
        
    if not permissions.get("allow_assembly", False):
        dangerous_patterns.extend(assembly)
        
    if not permissions.get("allow_sys_includes", False):
        dangerous_patterns.extend(sys_includes)

    for pattern in dangerous_patterns:
        if re.search(pattern, source):
            return False
    return True

def _sanitize_input(file_path: str, permissions: dict = None) -> bool:
    if not os.path.exists(file_path):
        return True
    with open(file_path, 'r', errors='ignore') as f:
        return _sanitize_code(f.read(), permissions)

def run_cpp_compiler(file_path, permissions=None, timeout=10.0):
    if not _sanitize_input(file_path, permissions):
        return [{
            "file": file_path,
            "line": 1,
            "column": 1,
            "type": "error",
            "message": "Security Error: Malicious command injection or forbidden system call detected.",
            "raw": "error: Malicious command injection or forbidden system call detected."
        }]

    try:
        from sandbox import compile_sandboxed
        # CXX_OVERRIDE allows a non-default compiler binary for verification runs
        # (e.g. CXX_OVERRIDE=g++-14 for GNU GCC testing).
        # When absent the pipeline uses the original default "g++" unchanged.
        _compiler = os.environ.get("CXX_OVERRIDE", "g++")
        compile_res = compile_sandboxed(
            file_path,
            compiler=_compiler,
            extra_flags=["-std=c++17"],
            timeout=timeout,
        )

        if "compiler not found" in (compile_res.stderr or "").lower() and compile_res.returncode == -1:
            raise FileNotFoundError()

        if compile_res.timed_out:
            return [{
                "file": file_path,
                "line": None,
                "column": None,
                "type": "error",
                "message": f"Compilation timed out after {timeout}s (resource limit exceeded)",
                "raw": f"error: compilation timed out after {timeout}s"
            }]

        errors = []
        pattern = r"(.+):(\d+):(\d+):\s+(error|warning):\s+(.*)"

        for line in compile_res.stderr.splitlines():
            match = re.match(pattern, line)
            if match:
                errors.append({
                    "file": match.group(1),
                    "line": int(match.group(2)),
                    "column": int(match.group(3)),
                    "type": match.group(4),
                    "message": match.group(5),
                    "raw": line
                })

        # Bug 1.2: Check compiler returncode for linker errors if no line:col errors matched
        if compile_res.returncode != 0 and not errors:
            stderr_text = compile_res.stderr.strip()
            sym_match = re.search(r'^\s*"([^"]+)",\s*referenced from:', stderr_text, re.MULTILINE)
            if sym_match:
                msg = f"undefined reference to '{sym_match.group(1)}'"
            else:
                undef_gcc = re.search(r"undefined reference to [`']?([^']+)'?", stderr_text)
                if undef_gcc:
                    msg = f"undefined reference to '{undef_gcc.group(1)}'"
                else:
                    msg = stderr_text.splitlines()[0] if stderr_text else "linker command failed"
            errors.append({
                "file": file_path,
                "line": None,
                "column": None,
                "type": "error",
                "message": msg,
                "raw": stderr_text,
                "category": "linker_error"
            })

        return errors

    except FileNotFoundError:
        return [{
            "file": None,
            "line": None,
            "column": None,
            "type": "error",
            "message": "g++ compiler not found.",
            "raw": "g++ compiler not found."
        }]