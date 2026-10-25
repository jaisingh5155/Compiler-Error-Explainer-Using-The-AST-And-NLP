# Week 8 Sandbox Architecture & Platform Limitations Notes

**Milestone**: Week 8 Part 1 (Isolated Compilation & Execution Sandbox)  
**Date**: September 27, 2026  
**Host Platform**: macOS Darwin 24.6.0 (`arm64-apple-darwin24.6.0`, Apple Clang version 21.0.0)  

---

## 1. Overview & Architecture

[`src/sandbox.py`](file:///Users/jaisinghsaini/TOACD/cd1/src/sandbox.py) provides isolated, resource-bounded compilation and execution for C++ source files and binaries. It establishes a secure execution foundation for Week 8's upcoming multi-stage verification gates (Parts 2 & 3) and Week 9's interactive GUI.

### Core Guarantees:
1. **Directory Isolation**:
   - Every compilation and execution task runs within a dedicated temporary directory (`tempfile.mkdtemp(prefix="cpp_sandbox_...")`).
   - Source files are copied to the sandbox directory; the original source files are **never modified in place**.
   - Temporary paths appearing in compiler diagnostics (`stderr`) are automatically mapped back to the original source file path so downstream tools (`understand`, `error_classifier`, `planner`) maintain intact file references.
2. **Filesystem Write Containment**:
   - Under macOS Darwin, process execution is wrapped with Apple Seatbelt (`sandbox-exec`), restricting file write operations strictly to the designated temporary directory, `$TMPDIR`, and `/dev`.
   - Any attempt to write outside the sandbox (such as `~/`, `/tmp`, system roots, or relative traversal `../../`) is denied by the operating system kernel (`[Errno 1] Operation not permitted`), without corrupting host files.
3. **Network Isolation**:
   - Sandboxed execution enforces `(deny network*)`, preventing any outbound or inbound network connections.
   - Verified that neither compilation nor diagnostic parsing attempts network communication.
4. **Clean Runaway Process Termination**:
   - Runaway processes (e.g., infinite loops, runaway recursion) are terminated cleanly via timeouts and CPU limits without hanging or crashing the pipeline.

---

## 2. Resource Limits: What Works vs What Doesn't on macOS

Python's `resource` module interfaces with POSIX `getrlimit()` and `setrlimit()`. On macOS (Darwin/XNU), several limit behaviors differ substantially from Linux:

| Resource Limit | Mechanism | macOS Darwin Status | Behavior / Impact on Compiler Explainer |
| :--- | :--- | :---: | :--- |
| **Wall-Clock Timeout** | `subprocess.run(timeout=...)` + `proc.kill()` | **WORKING (Enforceable)** | Terminated via `SIGKILL` on timeout expiration. Cleanly handles CPU-bound loops, I/O hangs, and sleep states. |
| **CPU Time (`RLIMIT_CPU`)** | `resource.setrlimit(RLIMIT_CPU, ...)` | **WORKING (Enforceable)** | Kernel fires `SIGXCPU` (exit code -24) when process exceeds allotted CPU seconds. Terminated immediately without hanging. |
| **File Size (`RLIMIT_FSIZE`)** | `resource.setrlimit(RLIMIT_FSIZE, ...)` | **WORKING (Enforceable)** | Kernel fires `SIGXFSZ` (exit code -25) if process attempts to write a disk file exceeding limit. |
| **Core Dumps (`RLIMIT_CORE`)** | `resource.setrlimit(RLIMIT_CORE, (0, 0))` | **WORKING (Enforceable)** | Prevents writing massive `.core` crash dumps to disk on fatal signals. |
| **File Descriptors (`RLIMIT_NOFILE`)** | `resource.setrlimit(RLIMIT_NOFILE, ...)` | **WORKING (Enforceable)** | Restricts maximum open files/pipes per child process. |
| **Output Size Capping** | Python buffer chunk reader | **WORKING (Enforceable)** | Output buffer is capped in memory (default 512KB–1MB); truncates logs if infinite spam is emitted. |
| **Virtual Memory (`RLIMIT_AS`)** | `resource.setrlimit(RLIMIT_AS, ...)` | **UNENFORCEABLE on macOS** | Calling `setrlimit(RLIMIT_AS, ...)` on 64-bit Darwin raises `ValueError: current limit exceeds maximum limit`. The XNU kernel does not permit unprivileged processes to adjust address-space limits. (Enforceable on Linux). |
| **Data Segment (`RLIMIT_DATA`)** | `resource.setrlimit(RLIMIT_DATA, ...)` | **UNENFORCEABLE on macOS** | Darwin XNU kernel rejects setting `RLIMIT_DATA` below the system default, raising `ValueError`. |
| **Resident Set Size (`RLIMIT_RSS`)** | `resource.setrlimit(RLIMIT_RSS, ...)` | **UNENFORCEABLE on macOS** | Darwin aliases `RLIMIT_RSS` to `RLIMIT_AS` and rejects setting. |
| **Memory Watchdog (RSS Poller)** | Child process RSS polled every ~50ms | **WORKING (Enforceable)** | Active userspace watchdog (`psutil` / `ps -o rss`). SIGKILLs child process group if RSS exceeds limit (default 512MB). |

### Practical Mitigation on macOS:
Because virtual memory limits (`RLIMIT_AS`) cannot be lowered via `setrlimit` on macOS, memory exhaustion protection relies on:
1. **Active Memory Watchdog**:
   - Both `compile_sandboxed()` and `execute_sandboxed()` launch an active background watchdog thread polling child process RSS every ~50ms.
   - If resident memory exceeds the configured threshold (`max_mem_bytes`, default 512MB), the watchdog immediately sends `SIGKILL` (-9) to the process.
   - Reported cleanly as `resource_exceeded=True`, `timed_out=False`, `error_message="Memory limit exceeded: resident set size (X MB) exceeded limit (Y MB)"`.
2. **CPU & Wall-Clock Limits**: High-allocation loops quickly hit either CPU or timeout bounds.
3. **File Size & Pipe Buffering**: Output floods cannot exhaust disk or memory buffers.
4. **Seatbelt Containment**: Uncontrolled heap growth cannot write escaped crash artifacts to the filesystem.

---

## 3. Apple Seatbelt (`sandbox-exec`) Deprecation & Linux Cross-Platform Behavior

### Apple Seatbelt Status:
- `sandbox-exec` and the Seatbelt profile language (`(version 1) (allow default) ...`) were introduced in Mac OS X 10.5 (Leopard) and officially marked **deprecated** by Apple starting in macOS 10.8 (Mountain Lion) in favor of the modern App Sandbox (entitlement-based security).
- Despite deprecation, Apple continues to ship `/usr/bin/sandbox-exec` and the underlying `libsystem_sandbox.dylib` kernel interface in modern macOS (including macOS 14 Sonoma and macOS 15 Sequoia / Darwin 24.6.0) for system daemons and shell tools.
- **Fail-Closed Behavior**: If `sandbox-exec` is missing, damaged, or errors out on macOS, `execute_sandboxed()` **fails closed**. It strictly refuses to run the compiled binary unsandboxed, reports `sandbox_active=False`, and returns `returncode=-1` with an explicit error message.

### What Happens on Linux:
- `sandbox-exec` is strictly macOS-only and does not exist on Linux.
- **Memory Enforcement on Linux**: Unlike Darwin, Linux natively enforces `RLIMIT_AS` and `RLIMIT_DATA` via `resource.setrlimit()`. Calling `setrlimit(RLIMIT_AS, ...)` on Linux sets a hard kernel-level address space ceiling (process terminates with `std::bad_alloc` or `SIGSEGV` if it attempts to allocate beyond the cap).
- **Filesystem & Network Isolation on Linux**: Without Seatbelt, Linux environments achieve isolation via:
  1. Temporary directory isolation (`tempfile.mkdtemp()`) for all builds.
  2. Linux unshare / user namespaces (`unshare -m -n -p`) to create unprivileged mount and network namespaces.
  3. Landlock LSM (Linux 5.13+) or `bubblewrap` (`bwrap`) / `seccomp-bpf` for unprivileged filesystem read/write filtering.

---

## 4. Compile Overhead Benchmarking

Compilation timing was benchmarked across 20 representative benchmark files (8 clean, 8 syntax error, 4 name resolution), running 3 iterations each (median recorded) comparing unsandboxed direct compilation against `compile_sandboxed()`:

| Benchmark File | Category | Unsandboxed `g++` | Sandboxed `compile_sandboxed` | Overhead |
| :--- | :--- | :---: | :---: | :---: |
| `cl01_hello.cpp` | clean | 223.5 ms | 238.9 ms | +15.5 ms |
| `cl02_math.cpp` | clean | 222.1 ms | 237.0 ms | +14.9 ms |
| `cl03_loops.cpp` | clean | 225.1 ms | 241.1 ms | +16.0 ms |
| `cl04_struct.cpp` | clean | 226.4 ms | 240.3 ms | +13.9 ms |
| `cl05_class.cpp` | clean | 228.6 ms | 238.4 ms | +9.7 ms |
| `cl06_vector.cpp` | clean | 240.3 ms | 293.2 ms | +52.9 ms |
| `cl07_templates.cpp` | clean | 16.2 ms | 62.7 ms | +46.5 ms |
| `cl08_lambdas.cpp` | clean | 16.4 ms | 62.8 ms | +46.4 ms |
| `sx01_missing_semi_decl.cpp` | syntax | 204.0 ms | 241.0 ms | +37.0 ms |
| `sx02_missing_semi_multi.cpp` | syntax | 206.2 ms | 242.1 ms | +35.9 ms |
| `sx03_missing_brace.cpp` | syntax | 207.0 ms | 239.9 ms | +32.9 ms |
| `sx04_missing_semi_string.cpp` | syntax | 207.4 ms | 239.6 ms | +32.2 ms |
| `sx07_unmatched_paren.cpp` | syntax | 205.3 ms | 240.3 ms | +34.9 ms |
| `sx08_double_semi_func_scope.cpp` | syntax | 205.3 ms | 242.2 ms | +36.8 ms |
| `sx11_nested_bracket_mismatch.cpp` | syntax | 206.6 ms | 240.5 ms | +33.9 ms |
| `sx12_brackets_in_string.cpp` | syntax | 207.7 ms | 237.1 ms | +29.4 ms |
| `nr02_undeclared_result.cpp` | name_resolution | 212.1 ms | 240.7 ms | +28.6 ms |
| `nr03_keyword_retrun.cpp` | name_resolution | 212.1 ms | 235.1 ms | +22.9 ms |
| `nr06_misspelled_ident.cpp` | name_resolution | 225.5 ms | 242.6 ms | +17.0 ms |
| `nr07_missing_std_prefix.cpp` | name_resolution | 217.3 ms | 241.5 ms | +24.3 ms |

- **Mean Unsandboxed Compile Time**: **195.76 ms**
- **Mean Sandboxed Compile Time**: **224.84 ms**
- **Mean Per-Compile Overhead**: **+29.09 ms**

The ~29 ms overhead accounts for creating the unique temporary directory, copying the source file, registering rlimit hooks and watchdog polling thread, and mapping compiler error paths back to the caller.

---

## 5. Verification Suite Results

Verified via [`tests/week8_verification/test_sandbox.py`](file:///Users/jaisinghsaini/TOACD/cd1/tests/week8_verification/test_sandbox.py) (9 tests passing):
1. `test_normal_compile_and_execute_sanity`: **PASSED** (clean compile and execution).
2. `test_compiler_runner_integration_sanity`: **PASSED** (clean files produce 0 errors, syntax errors retain proper file mapping).
3. `test_timeout_kills_runaway_process_cleanly`: **PASSED** (infinite loop killed in 1.0s, reports clean timeout/resource failure).
4. `test_filesystem_isolation_blocks_escape_write`: **PASSED** (absolute write outside sandbox denied by Seatbelt).
5. `test_relative_path_escape_blocked`: **PASSED** (relative path traversal `../../` blocked).
6. `test_platform_limitations_structure`: **PASSED** (correctly reports Darwin capabilities and memory watchdog).
7. `test_memory_watchdog_kills_memory_hog`: **PASSED** (bounded memory-hog killed by watchdog at 25MB before timeout, returncode -9, reports clean memory failure).
8. `test_filesystem_isolation_positive_control`: **PASSED** (unsandboxed run writes to external path successfully, proving the sandboxed failure is caused strictly by Seatbelt).
9. `test_fail_closed_when_sandbox_exec_missing`: **PASSED** (simulated missing sandbox-exec refuses to run unsandboxed, fails closed with `sandbox_active=False`).
