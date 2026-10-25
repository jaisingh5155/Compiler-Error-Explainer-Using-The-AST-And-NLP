"""
tools/detect.py
───────────────
Tool 2: Run classification & static security analysis, producing merged Diagnostic IR.

Wraps error_classifier.py's classification AND security_analyzer.py's scan into
ONE merged, ranked list of Diagnostic IR objects (both correctness and security
findings together, sorted by severity then confidence).
"""

from __future__ import annotations

import os
import sys
from typing import Union

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from diagnostic import Diagnostic, ProgramModel, from_security_finding
from security_analyzer import analyze as sa_analyze, SecurityFinding
from tools.understand import understand


def _severity_rank(diag: Diagnostic) -> int:
    """Return numeric rank (lower = higher severity)."""
    if diag.kind in ("error", "linker_error"):
        return 0
    for sf in diag.security_findings:
        sev = getattr(sf, "severity", "")
        if sev == "Critical":
            return 0
        if sev == "High":
            return 1
        if sev == "Medium":
            return 2
        if sev == "Low":
            return 3
    if diag.kind == "warning":
        return 2
    return 3


def detect(
    program_model: Union[ProgramModel, str],
    verbosity: str = "beginner",
) -> list[Diagnostic]:
    """
    Run detection across correctness diagnostics and static security findings.

    Parameters
    ----------
    program_model : ProgramModel or str
        The ProgramModel produced by understand(), or a file path string.
    verbosity : "beginner" | "detailed"
        Controls the verbosity returned in the primary 'explanation' field.
        Both modes are always populated in explanation_beginner and explanation_detailed.

    Returns
    -------
    list[Diagnostic]
        Merged, ranked list of Diagnostic objects sorted by severity then confidence.
    """
    if isinstance(program_model, str):
        program_model = understand(program_model)

    from models import CompilerError
    mock_errors: list[CompilerError] = []

    for d in program_model.diagnostics:
        ce = CompilerError(
            file=d.file or program_model.file_path,
            line=d.line,
            column=d.column,
            error_type=d.kind if d.kind != "linker_error" else "error",
            message=d.message,
            raw=d.raw,
        )
        ce.category = d.category
        ce.confidence = d.confidence
        mock_errors.append(ce)

    # Run security analyzer
    findings: list[SecurityFinding] = sa_analyze(program_model.file_path, mock_errors)

    # Convert security findings to Diagnostic IR
    security_diags: list[Diagnostic] = []
    for f in findings:
        diag = from_security_finding(f)
        if not diag.file:
            diag.file = program_model.file_path
        security_diags.append(diag)

    # Merge compiler diagnostics and security findings
    merged: list[Diagnostic] = list(program_model.diagnostics) + security_diags

    # Enrich name_resolution diagnostics with did_you_mean suggestions from symbol table
    sym_tab = getattr(program_model, "symbol_table", None)
    if sym_tab:
        import re
        ident_patterns = [
            re.compile(r"use of undeclared identifier ['‘\"](\w+)['’\"]"),
            re.compile(r"['‘\"](\w+)['’\"]\s+(?:was not declared|has not been declared)"),
            re.compile(r"unknown type name ['‘\"](\w+)['’\"]"),
            re.compile(r"no member named ['‘\"](\w+)['’\"]"),
        ]
        for d in merged:
            if d.kind in ("error", "warning") and (d.category == "name_resolution" or not d.did_you_mean):
                ident = None
                for pat in ident_patterns:
                    m = pat.search(d.message)
                    if m:
                        ident = m.group(1)
                        break
                if ident:
                    suggestion = sym_tab.find_closest_match(ident, d.line or 1, d.column or 1, max_distance=2)
                    if suggestion:
                        d.did_you_mean = suggestion

    # Populate dynamic Beginner and Detailed explanations on all diagnostics
    from error_explainer import explain_error
    for d in merged:
        if d.kind in ("error", "warning", "linker_error"):
            if getattr(d, "explanation_source", None) == "llm":
                continue
            res = explain_error(d, mode=verbosity)
            d.explanation_beginner = res["explanation_beginner"]
            d.explanation_detailed = res["explanation_detailed"]
            d.explanation = res["explanation"]
            if res.get("suggestion"):
                d.suggestion = res["suggestion"]
            if res.get("category") and (not d.category or d.category == "other"):
                d.category = res["category"]
                d.confidence = res["confidence"]
        else:
            # Security findings
            d.explanation_beginner = d.explanation or d.message
            d.explanation_detailed = (
                f"{d.explanation_beginner}\n\n"
                f"--- Detailed Security Context ---\n"
                f"CWE: {d.cwe or 'N/A'}\n"
                f"Severity Source: {d.severity_source}\n"
                f"Location: {d.file}:{d.line or 1}:{d.column or 1}"
            )
            d.explanation = d.explanation_detailed if verbosity == "detailed" else d.explanation_beginner

    # Run Agent Security Defense Scanner (defends agent against prompt injection)
    try:
        from agent_security import scan_source_for_injections
        src_code = getattr(program_model, "source_code", "")
        if not src_code and hasattr(program_model, "file_path") and os.path.exists(program_model.file_path):
            with open(program_model.file_path, "r", errors="ignore") as fp:
                src_code = fp.read()
        if src_code:
            injections = scan_source_for_injections(
                src_code,
                file_path=program_model.file_path if hasattr(program_model, "file_path") else None,
                log_on_detect=True,
                findings=merged,
            )
            for inj in injections:
                act_str = "BLOCKED" if inj.action_taken == "blocked" else "LOGGED"
                sugg_text = inj.advice.get("suggested_text", "Remove untrusted imperative injection directives from code.") if inj.advice else "Remove untrusted imperative injection directives from code."
                sec_diag = Diagnostic(
                    kind="security_attack",
                    file=inj.file_path or (program_model.file_path if hasattr(program_model, "file_path") else ""),
                    line=inj.line,
                    column=inj.col,
                    message=f"[AGENT SECURITY {act_str}] Adversarial instruction injection detected: {inj.snippet}",
                    category="adversarial_manipulation",
                    confidence=inj.risk_score,
                    explanation=f"Detected {inj.attack_type} in {inj.surface} (Risk Tier: {inj.risk_tier}). Action taken: {inj.action_taken}.",
                    suggestion=sugg_text,
                )
                sec_diag.risk_tier = inj.risk_tier
                sec_diag.action_taken = inj.action_taken
                sec_diag.attack_detection = inj.to_dict()
                sec_diag.explanation_beginner = sec_diag.message
                sec_diag.explanation_detailed = (
                    f"{sec_diag.message}\n\n"
                    f"--- Agent Security Context ---\n"
                    f"Attack Type: {inj.attack_type}\n"
                    f"Surface: {inj.surface}\n"
                    f"Risk Score: {inj.risk_score} ({inj.risk_tier})\n"
                    f"Action: {inj.action_taken}\n"
                    f"Reason: {inj.details.get('reason', '')}"
                )
                sec_diag.explanation = sec_diag.explanation_detailed if verbosity == "detailed" else sec_diag.explanation_beginner
                merged.append(sec_diag)
    except Exception:
        pass

    # Rank: severity first (ascending rank 0..3), then confidence descending
    merged.sort(key=lambda d: (_severity_rank(d), -d.confidence))

    return merged
