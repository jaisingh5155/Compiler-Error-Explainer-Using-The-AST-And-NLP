"""
diagnostic.py
─────────────
Defines the shared Diagnostic Intermediate Representation (IR) used by all
pipeline tools.  Every compiler error, security finding, or pre-scan warning
is normalised into a Diagnostic before downstream consumption.

Fields
------
kind        : "error" | "warning" | "note" | "security" | "linker_error"
code        : Compiler error code (e.g. "-Wreturn-type") or CWE-ID, if known
file        : Absolute or relative path to the source file
line        : 1-based line number (None for linker errors)
column      : 1-based column number (None when unavailable)
message     : Original diagnostic message from the compiler/scanner
normalized_message : Semantically normalised message (identifiers abstracted)
notes       : List of follow-on note/context lines from the compiler
fix_it      : Compiler-suggested fix-it text, if any
root_cause_id : Group ID linking cascading diagnostics to their root cause
confidence  : 0.0–1.0 classification confidence from the ML classifier
cwe         : CWE identifier string (e.g. "CWE-415") if security-relevant
severity_source : "compiler" | "static_scan" | "classifier"

category    : Classified error category (e.g. "syntax_error", "type_error")
explanation : Human-readable explanation text
suggestion  : Suggested fix text
context     : Source code context dict (start_line, lines)
security_findings : List of associated SecurityFinding objects
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Optional, Any


DiagnosticKind = Literal["error", "warning", "note", "security", "linker_error"]
SeveritySource = Literal["compiler", "static_scan", "classifier"]


@dataclass
class Diagnostic:
    """Unified diagnostic record consumed by all pipeline tools."""

    # ── Core identification ──────────────────────────────────────────
    kind: DiagnosticKind
    code: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None

    # ── Message variants ─────────────────────────────────────────────
    message: str = ""
    normalized_message: str = ""

    # ── Compiler context ─────────────────────────────────────────────
    notes: list[str] = field(default_factory=list)
    fix_it: Optional[str] = None

    # ── Grouping & classification ────────────────────────────────────
    root_cause_id: Optional[str] = None
    confidence: float = 0.0
    cwe: Optional[str] = None
    severity_source: SeveritySource = "compiler"

    # ── Extended fields (populated by enrichment steps) ──────────────
    category: Optional[str] = None
    explanation: Optional[str] = None
    explanation_beginner: Optional[str] = None
    explanation_detailed: Optional[str] = None
    suggestion: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    security_findings: list[Any] = field(default_factory=list)
    raw: str = ""

    # ── Week 5 extensions: AST & Symbol Table enrichment ─────────────
    ast_node_type: Optional[str] = None
    ast_node_summary: Optional[str] = None
    ast_fallback: bool = False
    did_you_mean: Optional[str] = None
    explanation_source: str = "template"
    fallback_reason: Optional[str] = None

    def __post_init__(self):
        if not self.cwe:
            if self.security_findings:
                f0 = self.security_findings[0]
                cwe_val = getattr(f0, "cwe", None) or (f0.get("cwe") if isinstance(f0, dict) else None)
                if cwe_val:
                    self.cwe = cwe_val
            if not self.cwe and self.category:
                try:
                    from security_analyzer import get_cwe_for_vulnerability
                    mapped = get_cwe_for_vulnerability(self.category)
                    if mapped and mapped != "CWE-Other":
                        self.cwe = mapped
                except Exception:
                    pass

    # ── Serialisation ────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict (compatible with legacy CompilerError.to_dict)."""
        findings = []
        for finding in self.security_findings:
            if hasattr(finding, "to_dict"):
                findings.append(finding.to_dict())
            elif isinstance(finding, dict):
                findings.append(finding)
            else:
                findings.append(str(finding))

        return {
            "kind": self.kind,
            "code": self.code,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "type": self.kind if self.kind != "linker_error" else "error",
            "error_type": self.kind if self.kind != "linker_error" else "error",
            "message": self.message,
            "normalized_message": self.normalized_message,
            "notes": self.notes,
            "fix_it": self.fix_it,
            "root_cause_id": self.root_cause_id,
            "confidence": self.confidence,
            "cwe": self.cwe,
            "severity_source": self.severity_source,
            "category": self.category,
            "explanation": self.explanation,
            "explanation_beginner": self.explanation_beginner,
            "explanation_detailed": self.explanation_detailed,
            "suggestion": self.suggestion,
            "context": self.context,
            "security_findings": findings,
            "raw": self.raw,
            "ast_node_type": self.ast_node_type,
            "ast_node_summary": self.ast_node_summary,
            "ast_fallback": self.ast_fallback,
            "did_you_mean": self.did_you_mean,
            "explanation_source": getattr(self, "explanation_source", "template"),
            "fallback_reason": getattr(self, "fallback_reason", None),
        }

    # ── Legacy CompilerError compatibility ───────────────────────────
    @property
    def error_type(self) -> str:
        """Alias for backward compat with code that reads error.error_type."""
        return self.kind if self.kind != "linker_error" else "error"

    @error_type.setter
    def error_type(self, value: str) -> None:
        self.kind = value  # type: ignore[assignment]

    @property
    def security_risk(self) -> Optional[str]:
        if hasattr(self, "_security_risk_override") and self._security_risk_override is not None:
            return self._security_risk_override
        if not self.security_findings:
            return None
        return "High" if any(
            getattr(f, "severity", None) in ("Critical", "High")
            for f in self.security_findings
        ) else "Low"

    @security_risk.setter
    def security_risk(self, value: Optional[str]) -> None:
        self._security_risk_override = value

    @property
    def risk_reason(self) -> Optional[str]:
        if hasattr(self, "_risk_reason_override") and self._risk_reason_override is not None:
            return self._risk_reason_override
        if not self.security_findings:
            return None
        types = [getattr(f, "vulnerability_type", str(f)) for f in self.security_findings]
        return f"Security issues detected: {', '.join(types)}"

    @risk_reason.setter
    def risk_reason(self, value: Optional[str]) -> None:
        self._risk_reason_override = value

    def __str__(self) -> str:
        parts = []
        location = ""
        if self.file:
            location += self.file
        if self.line:
            location += f":{self.line}"
        if self.column:
            location += f":{self.column}"
        if location:
            parts.append(location + " ")

        parts.append(f"{self.error_type.upper()}:{self.message}")

        if self.explanation:
            parts.append(f"\nExplanation: {self.explanation}")
        if self.suggestion:
            parts.append(f"\nSuggestion: {self.suggestion}")
        if self.category:
            parts.append(
                f"\nCategory: {self.category} (confidence: {self.confidence:.2f})"
            )
        if self.context and "lines" in self.context:
            parts.append("\nContext:")
            start = self.context["start_line"]
            for i, line in enumerate(self.context["lines"], start=start):
                marker = "→" if i == self.line else " "
                parts.append(f"\n{i:4} {marker} {line.rstrip()}")
                if i == self.line and self.column:
                    parts.append("\n" + " " * (self.column + 6) + "^")

        return "".join(parts)


# ── Factory helpers ──────────────────────────────────────────────────

def from_compiler_error(error: Any) -> Diagnostic:
    """Convert a legacy CompilerError (or raw dict from compiler_runner) into a Diagnostic."""
    if isinstance(error, dict):
        sec_findings = error.get("security_findings", []) or []
        cwe_val = error.get("cwe")
        if not cwe_val and sec_findings:
            f0 = sec_findings[0]
            cwe_val = getattr(f0, "cwe", None) or (f0.get("cwe") if isinstance(f0, dict) else None)
        if not cwe_val and error.get("category"):
            try:
                from security_analyzer import get_cwe_for_vulnerability
                mapped = get_cwe_for_vulnerability(error.get("category"))
                if mapped and mapped != "CWE-Other":
                    cwe_val = mapped
            except Exception:
                pass

        return Diagnostic(
            kind=error.get("type", error.get("kind", "error")),
            file=error.get("file"),
            line=error.get("line"),
            column=error.get("column"),
            message=error.get("message", ""),
            raw=error.get("raw", ""),
            category=error.get("category"),
            confidence=error.get("confidence", 0.0),
            cwe=cwe_val,
            root_cause_id=error.get("root_cause_id"),
            notes=error.get("notes", []) or [],
            fix_it=error.get("fix_it"),
            explanation=error.get("explanation"),
            suggestion=error.get("suggestion"),
            context=error.get("context"),
            security_findings=sec_findings,
        )
    sec_findings = getattr(error, "security_findings", []) or []
    cwe_val = getattr(error, "cwe", None)
    if not cwe_val and sec_findings:
        f0 = sec_findings[0]
        cwe_val = getattr(f0, "cwe", None) or (f0.get("cwe") if isinstance(f0, dict) else None)
    if not cwe_val and getattr(error, "category", None):
        try:
            from security_analyzer import get_cwe_for_vulnerability
            mapped = get_cwe_for_vulnerability(getattr(error, "category", None))
            if mapped and mapped != "CWE-Other":
                cwe_val = mapped
        except Exception:
            pass

    return Diagnostic(
        kind=getattr(error, "error_type", "error"),
        file=getattr(error, "file", None),
        line=getattr(error, "line", None),
        column=getattr(error, "column", None),
        message=getattr(error, "message", ""),
        raw=getattr(error, "raw", ""),
        category=getattr(error, "category", None),
        confidence=getattr(error, "confidence", 0.0),
        cwe=cwe_val,
        root_cause_id=getattr(error, "root_cause_id", None),
        notes=getattr(error, "notes", []) or [],
        fix_it=getattr(error, "fix_it", None),
        explanation=getattr(error, "explanation", None),
        explanation_beginner=getattr(error, "explanation_beginner", None),
        explanation_detailed=getattr(error, "explanation_detailed", None),
        suggestion=getattr(error, "suggestion", None),
        context=getattr(error, "context", None),
        security_findings=sec_findings,
        explanation_source=getattr(error, "explanation_source", "template"),
        fallback_reason=getattr(error, "fallback_reason", None),
    )


def from_security_finding(finding: Any) -> Diagnostic:
    """Convert a SecurityFinding into a Diagnostic."""
    vuln_type = getattr(finding, "vulnerability_type", None) or (finding.get("vulnerability_type") if isinstance(finding, dict) else None)
    cwe = getattr(finding, "cwe", None) or (finding.get("cwe") if isinstance(finding, dict) else None)
    if not cwe and vuln_type:
        try:
            from security_analyzer import get_cwe_for_vulnerability
            cwe = get_cwe_for_vulnerability(vuln_type)
        except Exception:
            cwe = None

    source_val = getattr(finding, "source", "") or (finding.get("source", "") if isinstance(finding, dict) else "")
    file_val = getattr(finding, "file", None) or (finding.get("file") if isinstance(finding, dict) else None)
    line_val = getattr(finding, "line", None) or (finding.get("line") if isinstance(finding, dict) else None)
    col_val = getattr(finding, "column", None) or (finding.get("column") if isinstance(finding, dict) else None)
    desc_val = getattr(finding, "description", "") or (finding.get("description", "") if isinstance(finding, dict) else "")

    return Diagnostic(
        kind="security",
        file=file_val,
        line=line_val,
        column=col_val,
        message=desc_val,
        category=vuln_type,
        cwe=cwe,
        severity_source="static_scan" if source_val == "static_scan" else "compiler",
        security_findings=[finding],
    )


# ── Pipeline Tool Data Contracts ──────────────────────────────────────

@dataclass
class ProgramModel:
    """Output contract for understand(file_path)."""
    file_path: str
    source_code: str = ""
    compile_output: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=list)
    ast_text: Optional[str] = None
    ast_node: Optional[Any] = None
    ast_nodes: Optional[list[Any]] = None
    symbol_table: Optional[Any] = None

    def __iter__(self):
        """Allow iterating directly over diagnostics."""
        return iter(self.diagnostics)

    def __len__(self):
        return len(self.diagnostics)

    def __getitem__(self, idx):
        return self.diagnostics[idx]


@dataclass
class Patch:
    """Output contract for repair(program_model, diagnostic)."""
    original_file: str
    patched_source: str
    diff: str = ""
    diagnostic: Optional[Diagnostic] = None
    safety_tier: int = 1
    tier_name: str = "Tier 1: Compiler Fix-It"
    safety_description: str = ""
    safety_level: str = "S0"
    suggestion_only: bool = False
    expected_structural_changes: Optional[dict[str, str]] = None  # e.g. {"main": "return_type"}

    def __getitem__(self, key: str) -> Any:
        if key == "patched_source":
            return self.patched_source
        if key == "diff":
            return self.diff
        if key == "original_file":
            return self.original_file
        if key == "diagnostic":
            return self.diagnostic
        if key == "safety_tier":
            return self.safety_tier
        if key == "tier_name":
            return self.tier_name
        if key == "safety_description":
            return self.safety_description
        if key == "safety_level":
            return self.safety_level
        if key == "suggestion_only":
            return self.suggestion_only
        if key == "expected_structural_changes":
            return self.expected_structural_changes
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_file": self.original_file,
            "patched_source": self.patched_source,
            "diff": self.diff,
            "safety_tier": self.safety_tier,
            "tier_name": self.tier_name,
            "safety_description": self.safety_description,
            "safety_level": self.safety_level,
            "suggestion_only": self.suggestion_only,
            "expected_structural_changes": self.expected_structural_changes,
        }


@dataclass
class Suggestion:
    """Output contract for optimize(program_model)."""
    description: str = ""
    confidence: float = 0.0
    replacement: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    file: Optional[str] = None
    optimization_type: str = ""

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "confidence": self.confidence,
            "replacement": self.replacement,
            "line": self.line,
            "column": self.column,
            "file": self.file,
            "optimization_type": self.optimization_type,
        }


@dataclass
class VerifyResult:
    """Output contract for verify(program_model, patch)."""
    passed: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)
    raw_output: str = ""
    new_diagnostics: list[Diagnostic] = field(default_factory=list)
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    failing_gate: Optional[str] = None
    failing_reason: Optional[str] = None

    @property
    def clean(self) -> bool:
        return self.passed

    def __getitem__(self, key: str) -> Any:
        if key in ("passed", "clean"):
            return self.passed
        if key == "diagnostics":
            return self.diagnostics
        if key == "raw_output":
            return self.raw_output
        if key == "new_diagnostics":
            return self.new_diagnostics
        if key == "gate_results":
            return self.gate_results
        if key == "failing_gate":
            return self.failing_gate
        if key == "failing_reason":
            return self.failing_reason
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "clean": self.clean,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "raw_output": self.raw_output,
            "new_diagnostics": [d.to_dict() for d in self.new_diagnostics],
            "gate_results": self.gate_results,
            "failing_gate": self.failing_gate,
            "failing_reason": self.failing_reason,
        }

