#!/usr/bin/env python3
"""
src/trace_view.py
─────────────────
Agent Trace View formatters and summary helpers (pure Python, zero Qt dependencies).
Surfaces PlannerResult.trace_log for CLI rendering, HTML reports, and GUI embedding.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional


def format_trace_text(trace_log: List[Dict[str, Any]]) -> str:
    """
    Format a planner trace log into a human-readable text string for CLI output.

    Renders step numbers, tools called, input -> output summaries, decisions,
    and for verify steps, detailed per-gate outcomes highlighting failures.
    """
    if not trace_log:
        return "(No trace steps recorded)"

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("AGENT EXECUTION TRACE")
    lines.append("=" * 72)

    for step in trace_log:
        step_num = step.get("step", "?")
        tool = step.get("tool_called", "unknown").upper()
        decision = step.get("decision", "")
        inp = step.get("input_summary", "")
        out = step.get("output_summary", "")
        failing_gate = step.get("failing_gate")

        lines.append(f"\n[Step {step_num}] Tool: {tool}")
        if inp:
            lines.append(f"  Input : {inp}")
        if out:
            lines.append(f"  Output: {out}")
        if decision:
            lines.append(f"  Action: {decision}")

        # Render gate details if present (handles list or dict)
        gate_details = step.get("gate_details")
        if gate_details:
            lines.append("  Verification Gates:")
            gate_list = []
            if isinstance(gate_details, list):
                gate_list = gate_details
            elif isinstance(gate_details, dict):
                for k, v in gate_details.items():
                    if isinstance(v, dict):
                        gate_list.append({"gate": k, **v})
                    else:
                        gate_list.append({"gate": k, "passed": v})
            for g in gate_list:
                g_name = (
                    getattr(g, "gate", None)
                    or getattr(g, "gate_name", None)
                    or (g.get("gate") if isinstance(g, dict) else None)
                    or (g.get("gate_name") if isinstance(g, dict) else None)
                    or "unknown_gate"
                )
                passed_val = getattr(g, "passed", None) if hasattr(g, "passed") else (g.get("passed") if isinstance(g, dict) else None)
                status_val = getattr(g, "status", None) if hasattr(g, "status") else (g.get("status") if isinstance(g, dict) else None)
                g_status = (status_val or ("passed" if passed_val else "failed")).upper()
                g_reason = getattr(g, "reason", "") if hasattr(g, "reason") else (g.get("reason", "") if isinstance(g, dict) else "")
                is_failing = (failing_gate and failing_gate in g_name) or g_status == "FAILED"

                if is_failing:
                    lines.append(f"    --> [{g_status}] {g_name} (FAILING)")
                else:
                    lines.append(f"        [{g_status}] {g_name}")
                if g_reason:
                    lines.append(f"            Reason: {g_reason}")

        if failing_gate:
            lines.append(f"  >>> REJECTED BY: {failing_gate} <<<")

    lines.append("\n" + "=" * 72)
    return "\n".join(lines)


def format_trace_html(trace_log: List[Dict[str, Any]]) -> str:
    """
    Format a planner trace log into a self-contained, styled HTML snippet.
    Safe for direct embedding into PyQt QTextBrowser or standalone HTML reports.
    Uses no external assets.
    """
    if not trace_log:
        return (
            "<div style='font-family: sans-serif; color: #64748b; padding: 20px; "
            "text-align: center;'>No trace steps recorded.</div>"
        )

    html_parts: List[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'/><style>",
        ".gate-box { border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px; margin-top: 6px; background: #f8fafc; }",
        ".gate-item { margin: 3px 0; font-size: 11px; }",
        ".gate-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; }",
        ".badge-pass { background: #dcfce7; color: #15803d; }",
        ".badge-fail { background: #fee2e2; color: #b91c1c; }",
        "</style></head><body>",
        "<div class='agent-trace' style='font-family: -apple-system, BlinkMacSystemFont, "
        "\"Segoe UI\", Roboto, monospace; color: #1e293b; background: #ffffff; padding: 12px; line-height: 1.5;'>",
        "<div style='font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 12px; "
        "border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;'>Agent Execution Trace</div>"
    ]

    for step in trace_log:
        step_num = step.get("step", "?")
        tool = html.escape(str(step.get("tool_called", "unknown")).upper())
        decision = html.escape(str(step.get("decision", "")))
        inp = html.escape(str(step.get("input_summary", "")))
        out = html.escape(str(step.get("output_summary", "")))
        failing_gate = step.get("failing_gate")

        # Color coding by tool
        tool_bg = "#f1f5f9"
        tool_color = "#334155"
        if tool == "VERIFY":
            tool_bg = "#ecfdf5" if not failing_gate else "#fef2f2"
            tool_color = "#047857" if not failing_gate else "#b91c1c"
        elif tool == "REPAIR":
            tool_bg = "#eff6ff"
            tool_color = "#1d4ed8"
        elif tool == "DETECT":
            tool_bg = "#faf5ff"
            tool_color = "#7e22ce"
        elif tool == "UNDERSTAND":
            tool_bg = "#f0fdfa"
            tool_color = "#0f766e"
        elif tool == "PLANNER":
            tool_bg = "#fffbeb"
            tool_color = "#b45309"
        elif tool in ("SECURITY_GUARDRAIL", "SECURITY"):
            tool_bg = "#f3e8ff"
            tool_color = "#6b21a8"
        elif tool in ("GATE6_SECURITY_BLOCK", "GATE6", "GATE6_BLOCK"):
            tool_bg = "#fee2e2"
            tool_color = "#991b1b"

        card_border = "#dc2626" if ("GATE6" in tool or failing_gate) else ("#a855f7" if tool in ("SECURITY_GUARDRAIL", "SECURITY") else "#cbd5e1")

        html_parts.append(
            f"<div style='border: 1px solid {card_border}; border-radius: 6px; margin-bottom: 10px; "
            f"background: #f8fafc; overflow: hidden;'>"
            f"<div style='background: {tool_bg}; color: {tool_color}; padding: 6px 12px; font-weight: 600; "
            f"font-size: 13px; display: flex; justify-content: space-between; border-bottom: 1px solid #e2e8f0;'>"
            f"<span>Step {step_num}: {tool}</span>"
            f"</div>"
            f"<div style='padding: 8px 12px; font-size: 12px; color: #334155;'>"
        )

        if inp:
            html_parts.append(f"<div style='margin-bottom: 4px;'><strong>Input:</strong> {inp}</div>")
        if out:
            html_parts.append(f"<div style='margin-bottom: 4px;'><strong>Output:</strong> {out}</div>")
        if decision:
            html_parts.append(f"<div style='margin-bottom: 4px; color: #0f172a;'><strong>Action:</strong> {decision}</div>")

        gate_details = step.get("gate_details")
        if gate_details:
            gate_list = []
            if isinstance(gate_details, list):
                gate_list = gate_details
            elif isinstance(gate_details, dict):
                for k, v in gate_details.items():
                    if isinstance(v, dict):
                        gate_list.append({"gate": k, **v})
                    else:
                        gate_list.append({"gate": k, "passed": v})

            html_parts.append(
                "<div class='gate-box'>"
                "<strong>Verification Gates:</strong>"
                "<ul style='margin: 4px 0 0 16px; padding: 0;'>"
            )
            for g in gate_list:
                g_name = html.escape(str(
                    getattr(g, "gate", None)
                    or getattr(g, "gate_name", None)
                    or (g.get("gate") if isinstance(g, dict) else None)
                    or (g.get("gate_name") if isinstance(g, dict) else None)
                    or "unknown_gate"
                ))
                passed_val = getattr(g, "passed", None) if hasattr(g, "passed") else (g.get("passed") if isinstance(g, dict) else None)
                status_val = getattr(g, "status", None) if hasattr(g, "status") else (g.get("status") if isinstance(g, dict) else None)
                g_status = (status_val or ("passed" if passed_val else "failed")).upper()
                g_reason = html.escape(str(getattr(g, "reason", "") if hasattr(g, "reason") else (g.get("reason", "") if isinstance(g, dict) else "")))

                is_fail = (failing_gate and failing_gate in g_name) or g_status == "FAILED"
                badge_cls = "badge-fail" if is_fail else "badge-pass"
                html_parts.append(
                    f"<li class='gate-item'>"
                    f"<span class='gate-badge {badge_cls}'>{g_status}</span> "
                    f"<strong>{g_name}</strong>"
                    f"{f' — <em>{g_reason}</em>' if g_reason else ''}"
                    f"</li>"
                )
            html_parts.append("</ul></div>")

        if failing_gate:
            html_parts.append(
                f"<div style='margin-top: 6px; background: #fee2e2; color: #991b1b; padding: 4px 8px; "
                f"border-radius: 4px; font-weight: 600; font-size: 11px;'>Rejected by {html.escape(str(failing_gate))}</div>"
            )

        html_parts.append("</div></div>")

    html_parts.append("</div></body></html>")
    return "\n".join(html_parts)


def summarize_trace(trace_log: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarize tool invocation counts, patch outcomes, and final planner stop reason.

    Returns:
    {
        "total_steps": int,
        "tool_counts": dict[str, int],
        "patches_applied": int,
        "patches_rolled_back": int,
        "patches_pending": int,
        "patches_suggested": int,
        "stop_reason": str,
    }
    """
    tool_counts: Dict[str, int] = {}
    patches_applied = 0
    patches_rolled_back = 0
    patches_pending = 0
    patches_suggested = 0
    stop_reason = "unknown"

    if not trace_log:
        return {
            "total_steps": 0,
            "tool_counts": {},
            "patches_applied": 0,
            "patches_rolled_back": 0,
            "patches_pending": 0,
            "patches_suggested": 0,
            "stop_reason": "unknown",
        }

    for step in trace_log:
        tool = step.get("tool_called", "unknown")
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

        decision = (step.get("decision") or "").lower()
        output_sum = (step.get("output_summary") or "").lower()
        tool_lower = tool.lower()

        # Patch evaluation outcomes are counted from candidate verification steps
        if tool_lower == "verify":
            # (a) Candidate rejected / blocked by a gate during verification (real rollback)
            if (
                step.get("failing_gate")
                or "reject" in decision
                or "roll back" in decision
                or "rollback" in decision
                or "malicious patch detected" in decision
                or "failed " in output_sum
            ):
                patches_rolled_back += 1
            # (b) Candidate passed all gates and queued for review (pending user decision)
            elif (
                "queue" in decision
                or "pending" in decision
            ):
                patches_pending += 1
            # (c) Candidate directly applied to disk
            elif "apply patch" in decision or "applied" in decision:
                patches_applied += 1
            # (d) S2 suggestion only
            elif "surface patch as suggestion" in decision:
                patches_suggested += 1
        elif "surface patch as suggestion" in decision:
            patches_suggested += 1

        # Track stop reason from planner steps
        if tool_lower == "planner" and ("stop" in decision or "goal met" in decision or "max_iterations" in decision or "iteration" in decision):
            stop_reason = step.get("decision", stop_reason)

    if stop_reason == "unknown" and trace_log:
        last = trace_log[-1]
        stop_reason = last.get("decision") or last.get("output_summary") or "completed"

    gate6_blocked_count = sum(
        1 for s in trace_log
        if s.get("tool_called") in ("GATE6_SECURITY_BLOCK", "gate6_security_block")
        or (s.get("tool_called") == "verify" and s.get("failing_gate") == "gate6_patch_security")
    )
    # Deduplicate in case both verify and GATE6_SECURITY_BLOCK steps exist for the same rejection
    gate6_tool_count = sum(1 for s in trace_log if s.get("tool_called") in ("GATE6_SECURITY_BLOCK", "gate6_security_block"))
    if gate6_tool_count > 0:
        gate6_blocked_count = gate6_tool_count

    return {
        "total_steps": len(trace_log),
        "tool_counts": tool_counts,
        "patches_applied": patches_applied,
        "patches_rolled_back": patches_rolled_back,
        "patches_pending": patches_pending,
        "patches_suggested": patches_suggested,
        "stop_reason": stop_reason,
        "gate6_blocked_count": gate6_blocked_count,
    }

