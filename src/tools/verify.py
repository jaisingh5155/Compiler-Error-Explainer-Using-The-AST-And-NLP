"""
src/tools/verify.py
───────────────────
Tool 5: Multi-Gate Verification Pipeline.

Replaces the minimal compilation stub with the real multi-gate verification pipeline:
- Gate 1: Recompile Check (target diagnostic resolved, no new errors/warnings)
- Gate 2: Minimal Diff Check (line changes bounded by safety level S0/S1/S2)
- Gate 3: AST-Diff Structural Check (declarations, signatures, and counts preserved)
- Gate 4: Security Regression Check (location-aware CWE regression detection)
- Gate 5: Differential Execution Check (evaluated where pre-patch baseline exists)
- Gate 6: Patch Content Security Audit (anti-exfiltration / malicious patch blocking)

A candidate patch must pass ALL applicable gates to be auto-applied.
If any gate fails, verify() returns passed=False with failing_gate and failing_reason,
allowing the planner to roll back and downgrade the patch to suggestion-only.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Union, List, Dict, Any

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from diagnostic import Diagnostic, ProgramModel, Patch, VerifyResult, from_compiler_error
from compiler_runner import run_cpp_compiler
from error_parser import parse_errors
from tools.verify_gates import verify_patch_gates


def verify(
    program_model: Union[ProgramModel, str],
    patch: Optional[Patch] = None,
    enable_gate5: bool = True,
    differential_inputs: Optional[List[str]] = None,
) -> VerifyResult:
    """
    Verify whether the source (or candidate patch) passes all validation gates.

    Parameters
    ----------
    program_model : ProgramModel or str
        The current ProgramModel or source file path.
    patch : Patch, optional
        A candidate patch to verify. If None, verifies the source file as-is
        (standard compilation check).
    enable_gate5 : bool, default True
        Whether to evaluate Gate 5 (differential execution) when applicable.
    differential_inputs : list[str], optional
        Optional test inputs for Gate 5.

    Returns
    -------
    VerifyResult
        Contains passed, diagnostics, raw_output, gate_results, failing_gate, and failing_reason.
    """
    file_path = program_model.file_path if isinstance(program_model, ProgramModel) else program_model

    # If no patch is provided, verify whether the file compiles cleanly as-is
    if patch is None:
        raw_output = run_cpp_compiler(file_path)
        if not raw_output:
            return VerifyResult(passed=True, diagnostics=[], raw_output="")

        errors = parse_errors(raw_output)
        diags: list[Diagnostic] = [from_compiler_error(e) for e in errors]
        hard_errors = sum(1 for d in diags if d.kind in ("error", "linker_error"))
        return VerifyResult(
            passed=(hard_errors == 0),
            diagnostics=diags,
            raw_output=str(raw_output),
        )

    # Resolve original source text
    original_source: Optional[str] = None
    if isinstance(program_model, ProgramModel) and program_model.source_code:
        original_source = program_model.source_code
    elif isinstance(program_model, str):
        if os.path.exists(program_model):
            try:
                with open(program_model, "r", errors="ignore") as f:
                    original_source = f.read()
            except Exception:
                pass
        else:
            original_source = program_model
    elif patch.original_file and os.path.exists(patch.original_file):
        try:
            with open(patch.original_file, "r", errors="ignore") as f:
                original_source = f.read()
        except Exception:
            pass

    # Resolve pre-patch diagnostics and target diagnostic
    pre_diags = program_model.diagnostics if isinstance(program_model, ProgramModel) else None
    target_diag = patch.diagnostic

    # Run multi-gate verification
    gate_out = verify_patch_gates(
        patch=patch,
        target_diagnostic=target_diag,
        pre_patch_diagnostics=pre_diags,
        original_source=original_source,
        enable_gate5=enable_gate5,
        inputs=differential_inputs,
    )

    all_passed = bool(gate_out.get("passed", False))
    trace_log = gate_out.get("trace_log", [])

    # Identify first failing gate, if any
    failing_gate: Optional[str] = None
    failing_reason: Optional[str] = None
    for item in trace_log:
        if item.get("status") == "failed" or item.get("passed") is False:
            failing_gate = item.get("gate")
            failing_reason = item.get("reason")
            break

    # Extract diagnostics and new diagnostics from gate1 details
    gate1_dict = gate_out.get("gate1_recompile", {})
    gate1_details = gate1_dict.get("details", {})
    post_diags_dicts = gate1_details.get("post_diagnostics", [])
    new_diags_dicts = gate1_details.get("new_diagnostics", [])

    post_diags: list[Diagnostic] = []
    for d in post_diags_dicts:
        if isinstance(d, dict):
            post_diags.append(from_compiler_error(d))

    new_diags: list[Diagnostic] = []
    for d in new_diags_dicts:
        if isinstance(d, dict):
            new_diags.append(from_compiler_error(d))

    raw_output = f"Gate pipeline: {'PASSED' if all_passed else 'FAILED'}"
    if failing_gate:
        raw_output += f" (failed {failing_gate}: {failing_reason})"

    return VerifyResult(
        passed=all_passed,
        diagnostics=post_diags,
        raw_output=raw_output,
        new_diagnostics=new_diags,
        gate_results=trace_log,
        failing_gate=failing_gate,
        failing_reason=failing_reason,
    )
