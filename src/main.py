#!/usr/bin/env python3

import argparse
import json
import os
import sys
import textwrap
import warnings

warnings.filterwarnings("ignore")

from compiler_runner import run_cpp_compiler
from error_parser import parse_errors
from error_explainer import enrich_error
from security_analyzer import analyze, format_security_report
from dataset_logger import log_example
from ast_extractor import extract_ast, extract_node_near_line

RED="\033[91m"
YELLOW="\033[93m"
GREEN="\033[92m"
BLUE="\033[95m"
BOLD="\033[1m"
RESET="\033[0m"


def _is_security_only_diagnostic(error) -> bool:
    message = (getattr(error, "message", "") or "").lower()
    error_type = (getattr(error, "error_type", "") or "").lower()
    return error_type == "warning" and (
        "unused variable" in message
        or "set but not used" in message
        or "declared but never used" in message
    )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="C++ Error Explanation & Auto-Repair Tool",
        epilog="""
Exit codes:
  0 : All files clean or not applicable (0 unhealed errors remain)
  1 : One or more files have unhealed errors
  2 : One or more files crashed, timed out, or invalid arguments
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source_file", nargs="?", default=None, help="C++ source file to compile")
    parser.add_argument("--batch", type=str, default=None, metavar="DIR", help="Run batch evaluation over DIR (recursive over *.cpp)")
    parser.add_argument("--report", type=str, default=None, metavar="OUT", help="Path to write report (.json or .html)")
    parser.add_argument("--apply", action="store_true", default=False, help="Apply proposed fixes back to original source files (default: OFF / safe sandbox)")
    parser.add_argument("--timeout", type=int, default=60, help="Per-file timeout in seconds for batch mode (default: 60)")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker threads for parallel batch execution (default: 1)")
    parser.add_argument("-j", "--json", action="store_true", help="print output in JSON format")
    parser.add_argument("-v", "--verbose", action="store_true", help="show detailed context")
    parser.add_argument("-c", "--context", type=int, default=2, help="number of context lines")
    parser.add_argument("--log-training", action="store_true", default=False, help="opt-in flag to log predictions into training_data.json")
    parser.add_argument("--heal", action="store_true", default=False, help="run planner auto-healing on the source file")
    parser.add_argument("--trace", action="store_true", default=False, help="print formatted agent execution trace")
    parser.add_argument("--llm-explain", action="store_true", default=False, help="enable LLM-enhanced explanations (requires llm_explainer.enabled in config)")
    parser.add_argument("--llm-enabled", action="store_true", default=False, help="runtime override to enable llm_explainer config for this invocation")
    parser.add_argument("--user-instructions", type=str, default=None, help="Optional user guidance instruction prompt for explanation style")

    return parser.parse_args()


def print_error(error, verbose=False):
    etype=error.error_type.lower()

    if etype=="error":
        color=RED
    elif etype=="warning":
        color=YELLOW
    else:
        color=BLUE

    print(f"\n{color}{BOLD}{etype.upper()}:{error.message}{RESET}")

    if error.file:
        location=f"{error.file}"
        if error.line is not None:
            location+=f" (line {error.line}"
            if error.column is not None:
                location+=f", column {error.column}"
            location+=")"
        print(f"  {BLUE}Location:{RESET} {location}")

    if error.explanation:
        print(f"\n  {BLUE}{BOLD}Explanation:{RESET}")
        for block in error.explanation.split("\n\n"):
            wrapped = textwrap.fill(block, width=80)
            print(f"  {BLUE}{wrapped}{RESET}\n")

    if error.suggestion:
        print(f"\n  {GREEN}{BOLD}Suggestion:{RESET}")
        wrapped=textwrap.fill(error.suggestion,width=80)
        for line in wrapped.split("\n"):
            print(f"  {GREEN}{line}{RESET}")

    if hasattr(error, "security_risk"):
        print(f"\n  {YELLOW}{BOLD}Security Assessment:{RESET}")
        print(f"  {YELLOW}Risk Level: {error.security_risk}{RESET}")

        if error.risk_reason:
            print(f"  {YELLOW}{error.risk_reason}{RESET}")

    if verbose and error.context and "lines" in error.context:
        print(f"\n  {BOLD}Code Context:{RESET}")
        start=error.context["start_line"]

        for i,line in enumerate(error.context["lines"],start=start):
            marker="→" if i==error.line else " "
            print(f"  {marker} {i}: {line.rstrip()}")

    print()

def main():
    args=parse_arguments()

    # Batch evaluation mode
    if args.batch:
        from batch_runner import run_batch
        from report_renderer import save_report

        if not os.path.exists(args.batch):
            print(f"Error: Target path does not exist: {args.batch}", file=sys.stderr)
            return 2

        if not args.json:
            print(f"Starting batch evaluation on: {args.batch}")
            print(f"Mode: {'LIVE WRITEBACK (--apply)' if args.apply else 'SAFE SIMULATION (read-only)'}")
            print(f"Per-file timeout: {args.timeout}s\n")

        def progress(idx, total, rec):
            outcome_sym = {
                "healed": f"{GREEN}HEALED{RESET}",
                "gave_up": f"{YELLOW}GAVE UP{RESET}",
                "not_applicable": f"{BLUE}N/A{RESET}",
                "crashed": f"{RED}CRASHED{RESET}",
            }.get(rec.outcome, rec.outcome.upper())
            print(f"  [{idx}/{total}] {rec.rel_path} -> {outcome_sym} ({rec.duration:.2f}s)")

        batch_result = run_batch(
            args.batch,
            apply=args.apply,
            timeout=args.timeout,
            max_workers=getattr(args, "workers", 1),
            callback=progress if not args.json else None,
        )

        # Write report if requested
        if args.report:
            save_report(batch_result, args.report)
            if not args.json:
                print(f"\nReport written to: {args.report}")

        s = batch_result.summary
        if args.json:
            print(json.dumps(batch_result.to_dict(), indent=2))
        else:
            print("\n" + "=" * 60)
            print("BATCH EVALUATION SUMMARY")
            print("=" * 60)
            print(f"Total Files:       {s['total_files']}")
            print(f"Attempted Heals:   {s['attempted']}")
            print(f"Healed (Clean):    {s['healed']} ({s['heal_success_percent']})")
            print(f"Gave Up:           {s['gave_up']}")
            print(f"Not Applicable:    {s['not_applicable']}")
            print(f"Crashed:           {s['crashed']}")
            print(f"Total Time:        {s['total_time']:.2f}s")
            print(f"Applied to Disk:   {s['apply']}")
            print("=" * 60)

        # Exit code: 0 if all clean/not_applicable, 1 if any unhealed error remains, 2 if any crashed
        if s["crashed"] > 0:
            return 2
        if s["gave_up"] > 0:
            return 1
        return 0

    if not args.source_file:
        print("Error: either source_file or --batch DIR is required.", file=sys.stderr)
        return 2

    if args.heal:
        from planner import run_planner
        res = run_planner(args.source_file, log_training=args.log_training, apply_to_disk=args.apply)
        if args.json:
            print(json.dumps({
                "status": res.status,
                "iterations": res.iterations,
                "trace_log": res.trace_log,
                "patches_applied": len(res.patches_applied),
                "pending_patches": len(getattr(res, "pending_patches", [])),
                "apply_mode": args.apply,
            }, indent=2))
        else:
            mode_str = "LIVE WRITEBACK (--apply)" if args.apply else "SAFE REVIEW MODE (disk untouched; pass --apply to write fixes)"
            print(f"Healing status: {res.status} ({res.iterations} iterations) [{mode_str}]")
            pending = getattr(res, "pending_patches", [])
            if not args.apply and pending:
                print(f"  → {len(pending)} verified candidate patch(es) generated. Source file remains untouched.")
                print("  → Re-run with '--heal --apply' to write verified fixes to disk.")
            if args.trace:
                from trace_view import format_trace_text
                print()
                print(format_trace_text(res.trace_log))
        return 0 if res.clean else 1

    from tools.understand import understand
    from tools.detect import detect
    from security_analyzer import format_security_report
    from root_cause_grouper import select_group_representatives

    cfg_override = None
    if getattr(args, "llm_enabled", False) or getattr(args, "llm_explain", False):
        from config_loader import load_config
        cfg_override = dict(load_config())
        llm_sub = dict(cfg_override.get("llm_explainer", {}))
        llm_sub["enabled"] = True
        cfg_override["llm_explainer"] = llm_sub

    model = understand(
        args.source_file,
        context_lines=args.context,
        log_training=args.log_training,
        llm_explain=getattr(args, "llm_explain", False),
        config=cfg_override,
    )

    # Scan user instructions if provided (Task B2 & B3)
    user_instruction_detections = []
    if getattr(args, "user_instructions", None):
        try:
            from agent_security import scan_user_instruction
            user_instruction_detections = scan_user_instruction(
                args.user_instructions,
                file_path=args.source_file,
                log_on_detect=True,
            )
        except Exception:
            pass

    all_findings = detect(model)

    # Extract agent security detections (Task A1 & B3)
    agent_security_findings = []
    for d in all_findings:
        if d.kind == "security_attack":
            att_dict = getattr(d, "attack_detection", None) or {
                "attack_type": "instruction_injection",
                "surface": "line_comment",
                "file_path": d.file,
                "line": d.line,
                "column": d.column,
                "snippet": d.message,
                "risk_score": d.confidence,
                "risk_tier": getattr(d, "risk_tier", "HIGH"),
                "action_taken": getattr(d, "action_taken", "blocked"),
                "details": {"reason": d.explanation},
            }
            agent_security_findings.append(att_dict)

    for u_inj in user_instruction_detections:
        agent_security_findings.append(u_inj.to_dict())

    # Extract security findings
    raw_security_findings = []
    seen_sf = set()
    for d in all_findings:
        for sf in d.security_findings:
            key = (getattr(sf, 'file', ''), getattr(sf, 'line', 0), getattr(sf, 'vulnerability_type', ''))
            if key not in seen_sf:
                seen_sf.add(key)
                raw_security_findings.append(sf)

    # Use detect()'s enriched compiler findings, selecting each root-cause group's
    # representative diagnostic by (severity_rank, -confidence) while preserving
    # group order so downstream diagnostics never outrank earlier root causes.
    compiler_findings = [d for d in all_findings if d.kind in ("error", "warning", "linker_error")]
    errors = select_group_representatives(compiler_findings) if compiler_findings else model.diagnostics


    # Decouple security scan report
    sec_report = format_security_report(raw_security_findings)

    if not model.compile_output:
        if args.json:
            print(json.dumps({
                "status": "success",
                "file": args.source_file,
                "security_findings": [f.to_dict() if hasattr(f, "to_dict") else f for f in raw_security_findings],
                "security_report": sec_report,
                "agent_security_detections": agent_security_findings,
                "agent_security_count": len(agent_security_findings),
            }, indent=2))
        else:
            print("Compilation successful")
            if agent_security_findings:
                print(f"\n{YELLOW}{BOLD}[AGENT SECURITY DEFENSE]{RESET} {len(agent_security_findings)} attack(s) intercepted:")
                for asf in agent_security_findings:
                    print(f"  • {asf.get('attack_type')} ({asf.get('surface')}): {asf.get('snippet')} -> {asf.get('action_taken').upper()}")
            print()
            print(sec_report, end="")
        return 0

    visible_errors = [e for e in errors if not _is_security_only_diagnostic(e)]
    visible_error_count = sum(1 for e in visible_errors if e.error_type == "error")
    visible_warning_count = sum(1 for e in visible_errors if e.error_type == "warning")

    # JSON mode
    if args.json:
        result={
            "status": "error" if visible_error_count > 0 else "success",
            "file": args.source_file,
            "error_count": visible_error_count,
            "warning_count": visible_warning_count,
            "errors": [e.to_dict() for e in visible_errors],
            "security_findings": [f.to_dict() if hasattr(f, "to_dict") else f for f in raw_security_findings],
            "security_report": sec_report,
            "agent_security_detections": agent_security_findings,
            "agent_security_count": len(agent_security_findings),
        }

        print(json.dumps(result, indent=2))
        return 1 if visible_error_count > 0 else 0

    # Human readable output
    print(f"\n{len(visible_errors)} issue(s) found:\n")

    error_count=0
    warning_count=0

    for e in visible_errors:
        if e.error_type=="error":
            error_count+=1
        elif e.error_type=="warning":
            warning_count+=1

        print_error(e,verbose=args.verbose)

    print(f"{error_count} error(s), {warning_count} warning(s)")
    print()
    print(sec_report, end="")
    return 1 if error_count > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
