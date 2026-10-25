#!/usr/bin/env python3
"""
src/tools/verify_gates.py
─────────────────────────
Verification gates for automated repair candidate patches.

Defines:
- GateResult: Result dataclass for individual gate evaluation.
- gate_recompile_check(): Gate 1 - Recompile check (target diagnostic resolved, no new errors/warnings).
- gate_minimal_diff_check(): Gate 2 - Minimal diff check (diff size bounded by safety level S0/S1/S2).
- verify_patch_gates(): Evaluates a patch through all enabled gates.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import difflib
import shutil
import tempfile
from diagnostic import Diagnostic, Patch, from_compiler_error
from compiler_runner import run_cpp_compiler
from error_parser import parse_errors
from diff_viewer import compute_diff, DiffLine, count_diff_lines
from sandbox import compile_sandboxed, execute_sandboxed, ExecutionResult
from ast_parser import parse_clang_ast, ASTNode
from security_analyzer import analyze as security_analyze, SecurityFinding


@dataclass
class GateResult:
    gate_name: str
    passed: Optional[bool]
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)
    status: Optional[str] = None

    def __post_init__(self):
        if self.status is None:
            if self.passed is True:
                self.status = "passed"
            elif self.passed is False:
                self.status = "failed"
            else:
                self.status = "not_applicable"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "status": self.status,
            "reason": self.reason,
            "details": self.details,
        }


# Documented thresholds for Gate 2 (Minimal Diff Size)
DEFAULT_DIFF_THRESHOLDS: Dict[str, int] = {
    "S0": 4,   # Low-risk trivial fix (include, semicolon, bracket): up to 4 modified lines
    "S1": 8,   # Local semantic/type adjustment (variable declaration, function swap): up to 8 modified lines
    "S2": 20,  # Broader refactor / suggestion-only patch: up to 20 modified lines
}


def _diagnostics_from_source(source_code: str, compiler_flags: Optional[List[str]] = None) -> List[Diagnostic]:
    """Compile source in sandbox and return parsed Diagnostic objects."""
    _compiler = os.environ.get("CXX_OVERRIDE", "g++")
    comp_res = compile_sandboxed(
        source_code,
        compiler=_compiler,
        extra_flags=compiler_flags or ["-std=c++17"],
        timeout=10.0,
    )
    if comp_res.timed_out:
        return [Diagnostic(
            kind="error",
            message="Compilation timed out inside sandbox (resource limit exceeded)",
            raw="error: compilation timed out",
        )]

    errors = []
    pattern = r"(.+):(\d+):(\d+):\s+(error|warning):\s+(.*)"
    for line in comp_res.stderr.splitlines():
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

    if comp_res.returncode != 0 and not errors:
        stderr_text = comp_res.stderr.strip()
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
            "file": "<input>",
            "line": None,
            "column": None,
            "type": "error",
            "message": msg,
            "raw": stderr_text,
            "category": "linker_error"
        })

    parsed = parse_errors(errors) if errors else []
    return [from_compiler_error(e) for e in parsed]


def _diagnostic_matches(d1: Diagnostic, d2: Diagnostic, *, require_line: bool = False) -> bool:
    """Determine if two diagnostics represent the same underlying compiler message.

    When *require_line* is True the match additionally requires the diagnostics'
    lines to be within 2 of each other (used for target-resolution checks where
    multiple identical messages may exist at different locations).
    """
    if d1.kind != d2.kind:
        return False

    msg_match = False
    # Exact message match
    if d1.message and d2.message and d1.message.strip() == d2.message.strip():
        msg_match = True

    # Normalized message match
    if not msg_match and d1.normalized_message and d2.normalized_message and d1.normalized_message == d2.normalized_message:
        msg_match = True

    if msg_match:
        if require_line:
            if d1.line is not None and d2.line is not None:
                return d1.line == d2.line
            # If either line is unknown, fall back to message-only match
            return True
        return True

    # Same category and line proximity (within 2 lines) - only when require_line is False
    if not require_line and d1.category and d2.category and d1.category == d2.category:
        if d1.line is not None and d2.line is not None:
            if abs(d1.line - d2.line) <= 2:
                # Check for significant token overlap in message (excluding English stopwords)
                _stop_words = {"did", "you", "mean", "to", "it", "a", "an", "the", "in", "of", "for", "at", "by", "with", "is", "be", "or", "not", "after", "before", "from", "on", "as"}
                words1 = set(re.findall(r"\w+", d1.message.lower())) - _stop_words
                words2 = set(re.findall(r"\w+", d2.message.lower())) - _stop_words
                overlap = words1.intersection(words2)
                if len(overlap) >= 2:
                    return True

    return False


def _map_line_through_diff(orig_line: int, orig_lines: List[str], post_lines: List[str]) -> Optional[int]:
    """Map a 1-based pre-patch line number to its post-patch position via SequenceMatcher.

    Returns the mapped 1-based line in post-patch coordinates, or None if the
    line was deleted.
    """
    matcher = difflib.SequenceMatcher(None, orig_lines, post_lines, autojunk=False)
    idx = orig_line - 1  # 0-based
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if i1 <= idx < i2:
            if tag == "equal":
                return j1 + (idx - i1) + 1
            elif tag == "replace":
                return j1 + 1  # approximate
            elif tag == "delete":
                return None
    return None


def gate_recompile_check(
    patch: Patch,
    target_diagnostic: Optional[Diagnostic] = None,
    pre_patch_diagnostics: Optional[List[Diagnostic]] = None,
    original_source: Optional[str] = None,
) -> GateResult:
    """
    Gate 1: Recompile Check.
    
    Validates candidate patch by compiling in sandbox:
    (a) The specific diagnostic the patch targeted must be resolved (gone).
    (b) No NEW error or warning appears that wasn't present before the patch.
        Existing pre-patch warnings remain acceptable.
    """
    # Resolve original source
    orig_src = original_source
    if orig_src is None and patch.original_file and os.path.exists(patch.original_file):
        try:
            with open(patch.original_file, "r", errors="ignore") as f:
                orig_src = f.read()
        except Exception:
            pass

    # Resolve pre-patch diagnostics
    pre_diags = pre_patch_diagnostics
    if pre_diags is None and orig_src is not None:
        pre_diags = _diagnostics_from_source(orig_src)
    elif pre_diags is None:
        pre_diags = []

    # Target diagnostic
    target_diag = target_diagnostic or patch.diagnostic

    # Compile patched source in sandbox
    post_diags = _diagnostics_from_source(patch.patched_source)

    # (a) Check if target diagnostic is resolved
    #     Map the target's pre-patch line through the diff to its post-patch
    #     coordinate, then require BOTH message AND mapped line to match when
    #     checking whether the target is still present. This prevents treating
    #     two identical messages at different lines as the same diagnostic.
    if target_diag is not None:
        target_line = target_diag.line
        if target_line is not None and pre_diags:
            exact_match = any(
                pd.line == target_line and _diagnostic_matches(target_diag, pd, require_line=False)
                for pd in pre_diags
            )
            if not exact_match:
                for pd in pre_diags:
                    if pd.line is not None and abs(pd.line - target_line) <= 1:
                        if _diagnostic_matches(target_diag, pd, require_line=False):
                            target_line = pd.line
                            break

        mapped_target = target_diag
        if target_line is not None and orig_src is not None:
            orig_lines_list = orig_src.splitlines()
            post_lines_list = patch.patched_source.splitlines()
            mapped_line = _map_line_through_diff(target_line, orig_lines_list, post_lines_list)
            if mapped_line is not None:
                # Create a copy with the mapped line for matching
                mapped_target = Diagnostic(
                    kind=target_diag.kind,
                    message=target_diag.message,
                    normalized_message=target_diag.normalized_message,
                    line=mapped_line,
                    column=target_diag.column,
                    file=target_diag.file,
                    category=target_diag.category,
                    code=target_diag.code,
                )
            else:
                # Target line was deleted by the patch — that's a resolution
                mapped_target = None

        still_present = False
        if mapped_target is not None:
            still_present = any(
                _diagnostic_matches(mapped_target, d, require_line=True)
                for d in post_diags
            )
        if still_present:
            return GateResult(
                gate_name="Gate 1: Recompile Check",
                passed=False,
                reason=f"Target diagnostic was not resolved by patch: {target_diag.message}",
                details={
                    "target_diagnostic": str(target_diag),
                    "mapped_line": getattr(mapped_target, 'line', None) if mapped_target else None,
                    "post_diagnostics_count": len(post_diags),
                    "post_diagnostics": [d.to_dict() for d in post_diags],
                    "failure_condition": "target_unresolved",
                }
            )

    # (b) Check for brand-new errors or warnings not present before
    new_diagnostics: List[Diagnostic] = []
    for post_d in post_diags:
        # Check if matched by any pre-patch diagnostic
        matched_pre = any(_diagnostic_matches(post_d, pre_d) for pre_d in pre_diags)
        if not matched_pre:
            new_diagnostics.append(post_d)

    if new_diagnostics:
        new_errors = [d for d in new_diagnostics if d.kind in ("error", "linker_error")]
        new_warnings = [d for d in new_diagnostics if d.kind == "warning"]

        if new_errors or new_warnings:
            first_new = (new_errors or new_warnings)[0]
            return GateResult(
                gate_name="Gate 1: Recompile Check",
                passed=False,
                reason=f"Patch introduced new {first_new.kind}: {first_new.message}",
                details={
                    "new_errors": [d.message for d in new_errors],
                    "new_warnings": [d.message for d in new_warnings],
                    "post_diagnostics": [d.to_dict() for d in post_diags],
                    "new_diagnostics": [d.to_dict() for d in new_diagnostics],
                    "failure_condition": "new_diagnostics_introduced",
                }
            )

    return GateResult(
        gate_name="Gate 1: Recompile Check",
        passed=True,
        reason="Target diagnostic resolved and no new errors/warnings introduced.",
        details={
            "pre_diagnostics_count": len(pre_diags),
            "post_diagnostics_count": len(post_diags),
            "post_diagnostics": [d.to_dict() for d in post_diags],
            "new_diagnostics": [],
        }
    )


def gate_minimal_diff_check(
    patch: Patch,
    original_source: Optional[str] = None,
    thresholds: Optional[Dict[str, int]] = None,
) -> GateResult:
    """
    Gate 2: Minimal Diff Size Check.

    Ensures the number of lines modified by the patch (+ and - lines)
    is within the acceptable threshold for its declared safety level (S0/S1/S2).
    """
    # Resolve original source
    orig_src = original_source
    if orig_src is None and patch.original_file and os.path.exists(patch.original_file):
        try:
            with open(patch.original_file, "r", errors="ignore") as f:
                orig_src = f.read()
        except Exception:
            pass

    if orig_src is None:
        return GateResult(
            gate_name="Gate 2: Minimal Diff Check",
            passed=False,
            reason="Cannot evaluate diff: original source not provided.",
            details={"failure_condition": "missing_source"}
        )

    # Compute line-by-line diff using diff_viewer
    diff_lines: List[DiffLine] = compute_diff(orig_src, patch.patched_source)
    added_lines = sum(1 for d in diff_lines if d.kind == "+")
    deleted_lines = sum(1 for d in diff_lines if d.kind == "-")
    modified_lines = count_diff_lines(diff_lines)

    # Resolve safety level and threshold
    safety_level = (patch.safety_level or "S0").upper()
    thresh_map = thresholds or DEFAULT_DIFF_THRESHOLDS
    max_allowed = thresh_map.get(safety_level, thresh_map.get("S0", 4))

    passed = modified_lines <= max_allowed
    if not passed:
        reason = (
            f"Diff size ({modified_lines} modified lines: +{added_lines}/-{deleted_lines}) "
            f"exceeds {safety_level} threshold of {max_allowed} lines."
        )
    else:
        reason = (
            f"Diff size ({modified_lines} modified lines: +{added_lines}/-{deleted_lines}) "
            f"is within {safety_level} threshold of {max_allowed} lines."
        )

    return GateResult(
        gate_name="Gate 2: Minimal Diff Check",
        passed=passed,
        reason=reason,
        details={
            "safety_level": safety_level,
            "modified_lines": modified_lines,
            "added_lines": added_lines,
            "deleted_lines": deleted_lines,
            "max_allowed": max_allowed,
        }
    )


def _extract_top_level_functions(source_code: str) -> Dict[str, List[str]]:
    """Extract top-level functions and their signatures from C++ source via Clang AST."""
    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as f:
        f.write(source_code)
        tmp_path = f.name
    try:
        nodes = parse_clang_ast(tmp_path)
        funcs: Dict[str, List[str]] = {}
        for n in nodes or []:
            if n.kind in ("FunctionDecl", "CXXMethodDecl", "FunctionTemplateDecl") and n.name:
                sig = n.type_name or "unknown"
                funcs.setdefault(n.name, []).append(sig)
        for k in funcs:
            funcs[k].sort()
        return funcs
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def gate_ast_diff_check(
    patch: Patch,
    original_source: Optional[str] = None,
) -> GateResult:
    """
    Gate 3: AST-Diff Structural Check.

    Compares the top-level AST function declarations before and after a patch:
    - Confirms no function was removed.
    - Confirms no function signature changed (return type, parameter types),
      UNLESS the change is declared in patch.expected_structural_changes.
    - Confirms no unexpected function was added (unless it already existed in pre-patch source text
      and was merely unblocked by fixing a syntax/brace/include issue).

    Declared exceptions:
      patch.expected_structural_changes = {"main": "return_type"}
      allows Gate 3 to accept a return-type change for main() while still
      rejecting any other undeclared structural change.
    """
    orig_src = original_source
    if orig_src is None and patch.original_file and os.path.exists(patch.original_file):
        try:
            with open(patch.original_file, "r", errors="ignore") as f:
                orig_src = f.read()
        except Exception:
            pass

    if orig_src is None:
        return GateResult(
            gate_name="Gate 3: AST-Diff Structural Check",
            passed=False,
            reason="Cannot evaluate AST diff: original source not provided.",
            details={"failure_condition": "missing_source"},
        )

    declared = getattr(patch, 'expected_structural_changes', None) or {}
    pre_funcs = _extract_top_level_functions(orig_src)
    post_funcs = _extract_top_level_functions(patch.patched_source)

    # 1. Check for removed functions or signature alterations
    for name, pre_sigs in pre_funcs.items():
        if name not in post_funcs:
            return GateResult(
                gate_name="Gate 3: AST-Diff Structural Check",
                passed=False,
                reason=f"Function '{name}' was removed by patch.",
                details={
                    "failure_condition": "function_removed",
                    "function_name": name,
                    "pre_signatures": pre_sigs,
                },
            )
        post_sigs = post_funcs[name]
        if pre_sigs != post_sigs:
            # Check if this change is declared as expected
            declared_change_type = declared.get(name)
            if declared_change_type == "return_type":
                # Verify only the return type changed (not parameters)
                # Signature format is typically "return_type (params)"
                def _extract_return_type(sig: str) -> str:
                    paren_idx = sig.find('(')
                    return sig[:paren_idx].strip() if paren_idx >= 0 else sig.strip()

                def _extract_params(sig: str) -> str:
                    paren_idx = sig.find('(')
                    return sig[paren_idx:].strip() if paren_idx >= 0 else '()'

                # Check all overloads: only return type should differ
                params_preserved = True
                if len(pre_sigs) == len(post_sigs):
                    for ps, qs in zip(sorted(pre_sigs), sorted(post_sigs)):
                        if _extract_params(ps) != _extract_params(qs):
                            params_preserved = False
                            break
                else:
                    params_preserved = False

                if params_preserved:
                    continue  # Declared return_type change accepted

            return GateResult(
                gate_name="Gate 3: AST-Diff Structural Check",
                passed=False,
                reason=f"Function signature changed for '{name}': {pre_sigs} -> {post_sigs}",
                details={
                    "failure_condition": "signature_changed",
                    "function_name": name,
                    "pre_signatures": pre_sigs,
                    "post_signatures": post_sigs,
                },
            )

    # 2. Check for unexpected newly added functions
    for name, post_sigs in post_funcs.items():
        if name not in pre_funcs:
            pattern = rf"\b{re.escape(name)}\s*\("
            if not re.search(pattern, orig_src):
                return GateResult(
                    gate_name="Gate 3: AST-Diff Structural Check",
                    passed=False,
                    reason=f"Unexpected function '{name}' was added by patch.",
                    details={
                        "failure_condition": "unexpected_function_added",
                        "function_name": name,
                        "signatures": post_sigs,
                    },
                )

    return GateResult(
        gate_name="Gate 3: AST-Diff Structural Check",
        passed=True,
        reason="AST structure preserved: function declarations, signatures, and counts unchanged.",
        details={
            "pre_functions": list(pre_funcs.keys()),
            "post_functions": list(post_funcs.keys()),
            "declared_exceptions": declared,
        },
    )


def _symbol_count(text: str, symbol: str) -> int:
    return len(re.findall(rf"\b{re.escape(symbol)}\b", text, re.IGNORECASE))


def _is_plausibly_introduced_by_patch(
    finding: SecurityFinding,
    patch_added_content: str,
    patch_removed_content: str = "",
) -> bool:
    """
    Checks if a security finding could plausibly have been introduced by the patch.
    Compares symbol counts in added vs removed lines:
    count_in_added > count_in_removed required for a symbol to be considered introduced.
    """
    if not patch_added_content.strip():
        return False

    desc = finding.description.lower()
    vuln_type = finding.vulnerability_type.lower()

    # 1. Dangerous functions
    dangerous_funcs = ["strcpy", "strcat", "sprintf", "vsprintf", "gets", "system", "popen", "memcpy"]
    for func in dangerous_funcs:
        if func in desc or func in vuln_type:
            n_add = _symbol_count(patch_added_content, func)
            n_rem = _symbol_count(patch_removed_content, func)
            if n_add > n_rem:
                return True
            if n_add > 0 and n_add <= n_rem:
                return False

    # 2. Variable name from description: e.g. "Variable 'foo' is read before..."
    var_match = re.search(r"variable ['\"]?([A-Za-z_]\w*)['\"]?", finding.description, re.IGNORECASE)
    if var_match:
        var_name = var_match.group(1)
        n_add = len(re.findall(rf"\b{re.escape(var_name)}\b", patch_added_content))
        n_rem = len(re.findall(rf"\b{re.escape(var_name)}\b", patch_removed_content))
        if n_add > n_rem:
            return True
        if n_add > 0 and n_add <= n_rem:
            return False

    return False


def gate_security_regression_check(
    patch: Patch,
    original_source: Optional[str] = None,
) -> GateResult:
    """
    Gate 4: Security Regression Check (Location-Aware).

    Runs security_analyzer.py's full scan on pre-patch and post-patch source.
    Compares findings using CWE + line mapping through the patch diff:
    - Fails ONLY if a new finding appears within +/-3 lines of the patched hunk,
      or is a new finding of a type the patch plausibly introduced.
    - Findings that appear elsewhere because the file now parses are returned
      in details["unmasked_findings"] as advisory and do not fail the gate.
    - Compares dangerous symbol counts in added vs removed lines so adding a
      semicolon to an existing dangerous line passes.
    """
    orig_src = original_source
    if orig_src is None and patch.original_file and os.path.exists(patch.original_file):
        try:
            with open(patch.original_file, "r", errors="ignore") as f:
                orig_src = f.read()
        except Exception:
            pass

    if orig_src is None:
        return GateResult(
            gate_name="Gate 4: Security Regression Check",
            passed=False,
            reason="Cannot evaluate security regression: original source not provided.",
            details={"failure_condition": "missing_source"},
        )

    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as f_pre:
        f_pre.write(orig_src)
        pre_file = f_pre.name

    with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as f_post:
        f_post.write(patch.patched_source)
        post_file = f_post.name

    try:
        pre_findings = security_analyze(pre_file, [])
        post_findings = security_analyze(post_file, [])

        orig_lines = orig_src.splitlines()
        post_lines = patch.patched_source.splitlines()

        matcher = difflib.SequenceMatcher(None, orig_lines, post_lines, autojunk=False)
        opcodes = matcher.get_opcodes()

        # Identify post-patch hunk line ranges (1-indexed) and collected added / removed lines
        post_hunks: List[tuple[int, int]] = []
        added_lines_text: List[str] = []
        removed_lines_text: List[str] = []

        for tag, i1, i2, j1, j2 in opcodes:
            if tag in ("replace", "insert"):
                hunk_start = j1 + 1
                hunk_end = max(j1 + 1, j2)
                post_hunks.append((hunk_start, hunk_end))
                added_lines_text.extend(post_lines[j1:j2])
            elif tag == "delete":
                del_anchor = max(1, j1)
                post_hunks.append((del_anchor, del_anchor))
            if tag in ("replace", "delete"):
                removed_lines_text.extend(orig_lines[i1:i2])

        added_patch_content = "\n".join(added_lines_text)
        removed_patch_content = "\n".join(removed_lines_text)

        # Map pre-patch findings to post-patch line coordinates
        mapped_pre_findings: List[tuple[str, Optional[int], str]] = []
        for pre_f in pre_findings:
            if pre_f.line is None:
                mapped_pre_findings.append((pre_f.vulnerability_type, None, pre_f.description))
                continue

            orig_line_idx = pre_f.line - 1
            mapped_line: Optional[int] = None
            for tag, i1, i2, j1, j2 in opcodes:
                if i1 <= orig_line_idx < i2:
                    if tag == "equal":
                        mapped_line = j1 + (orig_line_idx - i1) + 1
                    elif tag == "replace":
                        mapped_line = j1 + 1
                    elif tag == "delete":
                        mapped_line = None
                    break
            mapped_pre_findings.append((pre_f.vulnerability_type, mapped_line, pre_f.description))

        # Evaluate each post-patch finding
        introduced_regressions: List[SecurityFinding] = []
        unmasked_findings: List[SecurityFinding] = []

        for post_f in post_findings:
            matched = False
            for pre_type, pre_mapped_line, pre_desc in mapped_pre_findings:
                if post_f.vulnerability_type == pre_type:
                    if post_f.line is not None and pre_mapped_line is not None:
                        if abs(post_f.line - pre_mapped_line) <= 1:
                            matched = True
                            break
                    elif post_f.line is None and pre_mapped_line is None:
                        matched = True
                        break
                    elif post_f.description == pre_desc:
                        matched = True
                        break

            if matched:
                continue

            # Check if within +/- 3 lines of any patched hunk
            is_near_hunk = False
            if post_f.line is not None:
                for h_start, h_end in post_hunks:
                    if (h_start - 3) <= post_f.line <= (h_end + 3):
                        is_near_hunk = True
                        break
            else:
                is_near_hunk = True

            # Check dangerous symbols introduced by the diff (must compare counts in added vs removed)
            desc = post_f.description.lower()
            vuln_type = post_f.vulnerability_type.lower()
            dangerous_funcs = ["strcpy", "strcat", "sprintf", "vsprintf", "gets", "system", "popen", "memcpy"]
            func_in_finding = next((f for f in dangerous_funcs if f in desc or f in vuln_type), None)
            var_match = re.search(r"variable ['\"]?([A-Za-z_]\w*)['\"]?", post_f.description, re.IGNORECASE)

            is_introduced_symbol = False
            is_pre_existing_symbol = False

            if func_in_finding:
                n_add = _symbol_count(added_patch_content, func_in_finding)
                n_rem = _symbol_count(removed_patch_content, func_in_finding)
                if n_add > n_rem:
                    is_introduced_symbol = True
                elif n_add > 0 and n_add <= n_rem:
                    is_pre_existing_symbol = True
            elif var_match:
                vname = var_match.group(1)
                n_add = len(re.findall(rf"\b{re.escape(vname)}\b", added_patch_content))
                n_rem = len(re.findall(rf"\b{re.escape(vname)}\b", removed_patch_content))
                if n_add > n_rem:
                    is_introduced_symbol = True
                elif n_add > 0 and n_add <= n_rem:
                    is_pre_existing_symbol = True

            if is_pre_existing_symbol:
                unmasked_findings.append(post_f)
            elif is_introduced_symbol:
                introduced_regressions.append(post_f)
            elif is_near_hunk:
                introduced_regressions.append(post_f)
            elif _is_plausibly_introduced_by_patch(post_f, added_patch_content, removed_patch_content):
                introduced_regressions.append(post_f)
            else:
                unmasked_findings.append(post_f)

        if introduced_regressions:
            culprit = introduced_regressions[0]
            return GateResult(
                gate_name="Gate 4: Security Regression Check",
                passed=False,
                reason=(
                    f"Patch introduced new security finding: {culprit.vulnerability_type} "
                    f"({culprit.severity}) - {culprit.description}"
                ),
                details={
                    "failure_condition": "security_regression",
                    "pre_findings_count": len(pre_findings),
                    "post_findings_count": len(post_findings),
                    "introduced_regressions": [f.to_dict() for f in introduced_regressions],
                    "unmasked_findings": [f.to_dict() for f in unmasked_findings],
                },
            )

        return GateResult(
            gate_name="Gate 4: Security Regression Check",
            passed=True,
            reason=(
                f"No security regressions introduced in patched hunks "
                f"({len(unmasked_findings)} unmasked advisory findings)."
                if unmasked_findings else
                f"No security regressions introduced ({len(post_findings)} post-patch findings)."
            ),
            details={
                "pre_findings_count": len(pre_findings),
                "post_findings_count": len(post_findings),
                "unmasked_findings": [f.to_dict() for f in unmasked_findings],
            },
        )
    finally:
        for p in (pre_file, post_file):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def gate_differential_execution(
    patch: Patch,
    original_source: Optional[str] = None,
    inputs: Optional[List[str]] = None,
    timeout: float = 5.0,
) -> GateResult:
    """
    Gate 5: Differential Execution Test (Optional / Best-effort).

    Compares runtime behavior of pre-patch vs post-patch binaries.
    
    Applicability:
    If pre-patch code fails compilation (as with 0/56 repair targets),
    differential execution cannot produce a baseline run, so the gate returns
    status="not_applicable" (skipped).
    
    If pre-patch compiles cleanly (e.g. warnings-only or optimize passes), both binaries
    are executed with identical inputs in the sandbox, and stdout, stderr, and exit codes are compared.
    """
    orig_src = original_source
    if orig_src is None and patch.original_file and os.path.exists(patch.original_file):
        try:
            with open(patch.original_file, "r", errors="ignore") as f:
                orig_src = f.read()
        except Exception:
            pass

    if orig_src is None:
        return GateResult(
            gate_name="Gate 5: Differential Execution Check",
            passed=None,
            status="not_applicable",
            reason="Inapplicable: original source not provided for baseline execution.",
            details={"status": "skipped", "applicable": False, "reason": "missing_source"},
        )

    comp_pre = None
    comp_post = None
    try:
        # Check if pre-patch source compiles cleanly
        comp_pre = compile_sandboxed(orig_src, compiler=os.environ.get("CXX_OVERRIDE", "g++"), extra_flags=["-std=c++17"], timeout=timeout, keep_temp=True)
        if comp_pre.returncode != 0 or not comp_pre.executable_path or not os.path.exists(comp_pre.executable_path):
            return GateResult(
                gate_name="Gate 5: Differential Execution Check",
                passed=None,
                status="not_applicable",
                reason="Inapplicable: Pre-patch source does not compile, no baseline execution exists.",
                details={
                    "status": "skipped",
                    "applicable": False,
                    "reason": "no_pre_patch_baseline",
                    "compiler_stderr": comp_pre.stderr.strip()[:200],
                },
            )

        # Compile post-patch source
        comp_post = compile_sandboxed(patch.patched_source, compiler=os.environ.get("CXX_OVERRIDE", "g++"), extra_flags=["-std=c++17"], timeout=timeout, keep_temp=True)
        if comp_post.returncode != 0 or not comp_post.executable_path or not os.path.exists(comp_post.executable_path):
            return GateResult(
                gate_name="Gate 5: Differential Execution Check",
                passed=False,
                status="failed",
                reason="Post-patch source failed to compile for differential execution.",
                details={
                    "status": "failed",
                    "applicable": True,
                    "failure_condition": "post_compile_failed",
                    "compiler_stderr": comp_post.stderr.strip()[:200],
                },
            )

        test_inputs = inputs if inputs is not None else [""]
        for idx, inp in enumerate(test_inputs):
            res_pre = execute_sandboxed(comp_pre.executable_path, input_data=inp, timeout=timeout)
            res_post = execute_sandboxed(comp_post.executable_path, input_data=inp, timeout=timeout)

            if res_pre.returncode != res_post.returncode or res_pre.stdout != res_post.stdout or res_pre.stderr != res_post.stderr:
                return GateResult(
                    gate_name="Gate 5: Differential Execution Check",
                    passed=False,
                    status="failed",
                    reason=(
                        f"Differential execution output mismatch on input #{idx}: "
                        f"pre_rc={res_pre.returncode}, post_rc={res_post.returncode}; "
                        f"pre_stdout='{res_pre.stdout.strip()[:100]}', "
                        f"post_stdout='{res_post.stdout.strip()[:100]}'"
                    ),
                    details={
                        "status": "failed",
                        "applicable": True,
                        "failure_condition": "output_mismatch",
                        "input_index": idx,
                        "pre_returncode": res_pre.returncode,
                        "post_returncode": res_post.returncode,
                        "pre_stdout": res_pre.stdout,
                        "post_stdout": res_post.stdout,
                        "pre_stderr": res_pre.stderr,
                        "post_stderr": res_post.stderr,
                    },
                )

        return GateResult(
            gate_name="Gate 5: Differential Execution Check",
            passed=True,
            status="passed",
            reason=f"Differential execution passed across {len(test_inputs)} input(s): outputs match pre-patch baseline.",
            details={"status": "passed", "applicable": True, "tests_run": len(test_inputs)},
        )
    finally:
        for c in (comp_pre, comp_post):
            if c and c.sandbox_dir and os.path.exists(c.sandbox_dir):
                shutil.rmtree(c.sandbox_dir, ignore_errors=True)


def gate_patch_security_audit(
    patch: Patch,
    original_source: Optional[str] = None,
) -> GateResult:
    """
    Gate 6: Patch Content Security Audit.

    Scans proposed patch's patched_source against original_source for newly
    introduced exfiltration primitives (network sockets, env harvesting, sensitive files).
    """
    from agent_security import audit_patch_security
    detection = audit_patch_security(patch, original_source=original_source, log_on_detect=True)
    if detection:
        prim = detection.details.get("primitive", "unknown")
        return GateResult(
            gate_name="Gate 6: Patch Content Security Audit",
            passed=False,
            reason=f"Patch rejected: Malicious code pattern detected ({prim}: {detection.snippet})",
            details={
                "failure_condition": "malicious_patch",
                "attack_type": detection.attack_type,
                "primitive": prim,
                "snippet": detection.snippet,
                "risk_score": detection.risk_score,
                "action_taken": detection.action_taken,
            },
        )
    return GateResult(
        gate_name="Gate 6: Patch Content Security Audit",
        passed=True,
        reason="No malicious exfiltration primitives or backdoors detected in patch content.",
        details={"status": "clean"},
    )


def verify_patch_gates(
    patch: Patch,
    target_diagnostic: Optional[Diagnostic] = None,
    pre_patch_diagnostics: Optional[List[Diagnostic]] = None,
    original_source: Optional[str] = None,
    diff_thresholds: Optional[Dict[str, int]] = None,
    enable_gate5: bool = False,
    inputs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Convenience orchestrator evaluating verification gates in sequence.
    """
    gate1 = gate_recompile_check(
        patch=patch,
        target_diagnostic=target_diagnostic,
        pre_patch_diagnostics=pre_patch_diagnostics,
        original_source=original_source,
    )
    gate2 = gate_minimal_diff_check(
        patch=patch,
        original_source=original_source,
        thresholds=diff_thresholds,
    )
    gate3 = gate_ast_diff_check(
        patch=patch,
        original_source=original_source,
    )
    gate4 = gate_security_regression_check(
        patch=patch,
        original_source=original_source,
    )
    gate6 = gate_patch_security_audit(
        patch=patch,
        original_source=original_source,
    )

    gates = {
        "gate1_recompile": gate1.to_dict(),
        "gate2_diff_size": gate2.to_dict(),
        "gate3_ast_diff": gate3.to_dict(),
        "gate4_security_regression": gate4.to_dict(),
        "gate6_patch_security": gate6.to_dict(),
    }
    all_passed = bool(gate1.passed and gate2.passed and gate3.passed and gate4.passed and gate6.passed)

    trace_log = [
        {"gate": "gate1_recompile", "status": gate1.status, "passed": gate1.passed, "reason": gate1.reason},
        {"gate": "gate2_diff_size", "status": gate2.status, "passed": gate2.passed, "reason": gate2.reason},
        {"gate": "gate3_ast_diff", "status": gate3.status, "passed": gate3.passed, "reason": gate3.reason},
        {"gate": "gate4_security_regression", "status": gate4.status, "passed": gate4.passed, "reason": gate4.reason},
        {"gate": "gate6_patch_security", "status": gate6.status, "passed": gate6.passed, "reason": gate6.reason},
    ]

    if enable_gate5:
        gate5 = gate_differential_execution(
            patch=patch,
            original_source=original_source,
            inputs=inputs,
        )
        gates["gate5_differential_execution"] = gate5.to_dict()
        trace_status = "skipped" if gate5.status == "not_applicable" else gate5.status
        trace_log.append({
            "gate": "gate5_differential_execution",
            "status": trace_status,
            "passed": gate5.passed,
            "reason": gate5.reason,
        })
        if gate5.status != "not_applicable":
            all_passed = all_passed and bool(gate5.passed)

    return {
        "passed": all_passed,
        "trace_log": trace_log,
        **gates,
    }
