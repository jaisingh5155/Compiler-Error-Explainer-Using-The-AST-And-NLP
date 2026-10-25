"""
src/comment_hygiene_advisor.py
──────────────────────────────
Comment Hygiene Advisor Component.

Runs strictly AFTER security detection, independent of blocking/logging decisions.
Produces plain-language suggestions for the user when an adversarial or
risky comment is detected:
1. Explains why the comment is risky in plain terms.
2. Suggests concrete neutral alternative phrasing or recommends deletion.
   (Never generates a "cleaned up" version of an attack instruction).
3. Purely advisory — never auto-applied, never touches source files without
   explicit user action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any


@dataclass
class CommentHygieneAdvice:
    """Advisory recommendation for improving or removing risky comments."""
    original_comment: str
    risk_level: str               # "HIGH" | "MEDIUM"
    attack_type: str              # "instruction_injection" | "policy_bypass" | "validation_suppression"
    explanation: str              # Plain-language reason why this is risky
    recommended_action: str       # "delete" | "rephrase"
    suggested_text: str           # Concrete neutral alternative or deletion suggestion
    guidance_notes: str           # Best practices for comments near security logic

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_ADVICE_EXPLANATION = (
    "This comment is phrased as an instruction to an AI system rather than as a note for a human reader. "
    "Comments like this can be mistaken for legitimate directives by automated tools, including this one, "
    "and should be rewritten or removed."
)


def advise_comment_hygiene(
    snippet: str,
    risk_level: str = "HIGH",
    attack_type: str = "instruction_injection",
    contradicted_issue: Optional[str] = None,
) -> CommentHygieneAdvice:
    """
    Produce plain-language hygiene advice for a flagged comment snippet.
    
    Adheres to safety rules:
    - Never suggests a "cleaned up" version of an attack directive.
    - Recommends neutral developer documentation or comment deletion.
    """
    clean_snippet = (snippet or "").strip()

    # Determine recommended action:
    # Directives attempting to override security policy, disable validation, or fake status
    # should be deleted outright rather than rephrased.
    lower_s = clean_snippet.lower()
    is_blatant_override = any(
        k in lower_s
        for k in (
            "ignore the security policy",
            "disable the validation step",
            "mark as safe",
            "mark this code as safe",
            "override_verification",
            "force passed_gates",
            "status=clean",
            "safety_tier=s0",
            "skip gate",
        )
    )

    if is_blatant_override or risk_level == "HIGH":
        action = "delete"
        suggested_text = "Recommendation: Remove this comment completely from source."
        guidance = (
            "Security and validation policies are enforced deterministically by the toolchain. "
            "Comments attempting to suppress gates or alter classification provide no valid "
            "documentation value and will trigger automated security tripwires."
        )
    else:
        action = "rephrase"
        suggested_text = "// Note: Manual inspection completed; refer to module design docs for validation rationale."
        guidance = (
            "If this comment documents design constraints, use passive descriptive language "
            "(e.g., '// Note: ...') rather than imperative command verbs ('ignore', 'disable', 'skip')."
        )

    if contradicted_issue:
        explanation = (
            f"{_ADVICE_EXPLANATION} In this file, the comment claims safety or overrides checks "
            f"while a verifiable finding exists nearby ({contradicted_issue}), making it an active discrepancy."
        )
    else:
        explanation = _ADVICE_EXPLANATION

    return CommentHygieneAdvice(
        original_comment=clean_snippet,
        risk_level=risk_level,
        attack_type=attack_type,
        explanation=explanation,
        recommended_action=action,
        suggested_text=suggested_text,
        guidance_notes=guidance,
    )
