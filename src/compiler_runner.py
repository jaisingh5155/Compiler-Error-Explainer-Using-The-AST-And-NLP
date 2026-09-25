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
    
    if not permissions.get("allow_system_calls", False):
        dangerous_patterns.extend([r'system\s*\(', r'exec\s*\(', r'popen\s*\(', r'fork\s*\('])
        
    if not permissions.get("allow_assembly", False):
        dangerous_patterns.extend([r'__asm__', r'shellcode'])
        
    if not permissions.get("allow_sys_includes", False):
        dangerous_patterns.extend([r'#include\s*[<"]\s*sys/'])

    for pattern in dangerous_patterns:
        if re.search(pattern, source):
            return False
    return True

def _sanitize_input(file_path: str, permissions: dict = None) -> bool:
    if not os.path.exists(file_path):
        return True
    with open(file_path, 'r', errors='ignore') as f:
        return _sanitize_code(f.read(), permissions)

def run_cpp_compiler(file_path, permissions=None):
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
        res=subprocess.run(
            ["g++","-std=c++17",file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        errors=[]
        pattern=r"(.+):(\d+):(\d+):\s+(error|warning):\s+(.*)"

        for line in res.stderr.splitlines():
            match=re.match(pattern, line)
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
        if res.returncode != 0 and not errors:
            stderr_text = res.stderr.strip()
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
        return[{
            "file":None,
            "line":None,
            "column":None,
            "type":"error",
            "message":"g++ compiler not found.",
            "raw":"g++ compiler not found."
        }]