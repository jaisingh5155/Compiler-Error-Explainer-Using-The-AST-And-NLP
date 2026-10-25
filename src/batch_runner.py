"""
src/batch_runner.py
───────────────────
Batch evaluation engine for C++ files and directories.

Features:
- Recursive discovery of *.cpp files.
- Non-destructive execution by default: files are copied to a temporary sandbox,
  and originals are never modified unless apply=True is specified.
- Robust per-file isolation: timeouts and exceptions/crashes are caught and recorded
  without aborting the batch.
- Comprehensive per-file tracking:
  - compiler status before & after
  - error / warning counts
  - diagnostics with category, confidence, and root-cause group ID
  - security findings with CWE ID and severity
  - patches applied, suggested, and blocked (with failing gate details)
  - post-repair optimize suggestions
  - execution trace log
- Aggregate summary metrics:
  - healed / gave_up / not_applicable / crashed counts
  - patches grouped by safety tier
  - gate failure breakdown
  - security findings by CWE
  - total wall-clock execution time
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import asdict, dataclass, field
import datetime
import hashlib
import os
import shutil
import tempfile
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from diagnostic import Diagnostic, Patch, ProgramModel, Suggestion
from planner import PlannerResult, run_planner
from root_cause_grouper import group_by_root_cause
from security_analyzer import get_cwe_for_vulnerability
from tools.detect import detect
from tools.optimize import optimize
from tools.understand import understand


def hash_file(file_path: str) -> str:
    """Return SHA-256 hash of a file's contents."""
    if not os.path.exists(file_path):
        return ""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as fp:
            for chunk in iter(lambda: fp.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


def find_cpp_files(target_dir: str) -> list[str]:
    """Recursively find and return all *.cpp files in target_dir, sorted alphabetically."""
    if os.path.isfile(target_dir):
        return [os.path.abspath(target_dir)] if target_dir.endswith(".cpp") else []

    cpp_files = []
    for root, _, files in os.walk(target_dir):
        if "agent_attacks" in root and os.path.basename(target_dir) != "agent_attacks":
            continue
        for fn in files:
            if fn.endswith(".cpp") and not fn.startswith("."):
                cpp_files.append(os.path.abspath(os.path.join(root, fn)))
    return sorted(cpp_files)


@dataclass
class FileRecord:
    filepath: str
    rel_path: str
    compiler_status_before: str
    compiler_status_after: str
    error_count_before: int
    error_count_after: int
    warning_count_before: int
    warning_count_after: int
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    security_findings: list[dict[str, Any]] = field(default_factory=list)
    patches_applied: list[dict[str, Any]] = field(default_factory=list)
    patches_suggested: list[dict[str, Any]] = field(default_factory=list)
    patches_blocked: list[dict[str, Any]] = field(default_factory=list)
    optimize_suggestions: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "not_applicable"
    outcome: str = "not_applicable"  # "healed" | "gave_up" | "not_applicable" | "crashed"
    duration: float = 0.0
    original_hash: str = ""
    final_hash: str = ""
    applied: bool = False
    error_message: Optional[str] = None
    trace_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchResult:
    summary: dict[str, Any]
    files: list[dict[str, Any]]
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "files": self.files,
            "timestamp": self.timestamp,
        }


def _extract_diagnostics(diags: Sequence[Diagnostic]) -> list[dict[str, Any]]:
    """Convert diagnostics into serialisable records with category, confidence, and root-cause ID."""
    try:
        grouped = group_by_root_cause(diags)
    except Exception:
        grouped = list(diags)

    results = []
    for d in grouped:
        results.append({
            "file": d.file,
            "line": d.line,
            "column": d.column,
            "kind": d.kind,
            "category": d.category or "other",
            "confidence": round(float(d.confidence or 0.0), 4),
            "root_cause_id": getattr(d, "root_cause_id", None),
            "message": d.message,
            "cwe": d.cwe,
        })
    return results


def _extract_security_findings(diags: Sequence[Diagnostic]) -> list[dict[str, Any]]:
    """Extract security findings and canonical CWEs from diagnostics."""
    findings: list[dict[str, Any]] = []
    seen = set()

    for d in diags:
        # Diagnostic itself might be kind == "security"
        if d.kind == "security":
            vuln_type = d.category or "Security Issue"
            cwe = d.cwe or get_cwe_for_vulnerability(vuln_type)
            key = (d.file, d.line, vuln_type)
            if key not in seen:
                seen.add(key)
                findings.append({
                    "file": d.file,
                    "line": d.line,
                    "column": d.column,
                    "severity": getattr(d, "severity_source", "High") if getattr(d, "severity_source", None) in ("Critical", "High", "Medium", "Low") else "High",
                    "vulnerability_type": vuln_type,
                    "cwe": cwe,
                    "description": d.message,
                    "recommendation": d.suggestion or "",
                    "source": d.severity_source,
                })

        for sf in getattr(d, "security_findings", []):
            if hasattr(sf, "to_dict"):
                item = sf.to_dict()
            elif isinstance(sf, dict):
                item = dict(sf)
            else:
                continue

            vuln = item.get("vulnerability_type", "Security Issue")
            cwe = item.get("cwe") or get_cwe_for_vulnerability(vuln)
            item["cwe"] = cwe
            key = (item.get("file"), item.get("line"), vuln)
            if key not in seen:
                seen.add(key)
                findings.append(item)

    return findings


def _extract_blocked_patches(trace_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract patches rejected during verify steps in the trace log."""
    blocked = []
    for step in trace_log or []:
        tool = step.get("tool_called", "").lower()
        failing_gate = step.get("failing_gate")
        if tool == "verify" and failing_gate:
            blocked.append({
                "step": step.get("step"),
                "failing_gate": failing_gate,
                "reason": step.get("output_summary") or step.get("decision", ""),
                "gate_details": step.get("gate_details", []),
            })
    return blocked


def process_single_file(
    file_path: str,
    *,
    base_dir: str = "",
    apply: bool = False,
) -> FileRecord:
    """
    Process a single C++ source file in a temporary sandbox.
    
    If apply is False (default), the original file is NEVER altered.
    If apply is True and the file was cleanly healed, the repaired content
    is copied back to the original file.
    """
    start_time = time.perf_counter()
    rel_path = os.path.relpath(file_path, base_dir) if base_dir else os.path.basename(file_path)
    orig_hash = hash_file(file_path)

    # 1. Read source
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        source_code = f.read()

    # 2. Setup sandbox in a temporary directory
    temp_dir = tempfile.mkdtemp(prefix="agy_batch_")
    temp_file = os.path.join(temp_dir, os.path.basename(file_path))
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(source_code)

    try:
        # Initial baseline analysis
        initial_model = understand(temp_file)
        initial_detect = detect(initial_model)

        compiler_diags = [d for d in initial_detect if d.kind in ("error", "warning", "linker_error")]
        error_count_before = sum(1 for d in compiler_diags if d.kind in ("error", "linker_error"))
        warning_count_before = sum(1 for d in compiler_diags if d.kind == "warning")
        status_before = "error" if error_count_before > 0 else ("warning" if warning_count_before > 0 else "clean")

        parsed_diags = _extract_diagnostics(compiler_diags)
        sec_findings = _extract_security_findings(initial_detect)

        # Non-error files without security issues do not require compiler/security healing
        if error_count_before == 0 and len(sec_findings) == 0:
            duration = time.perf_counter() - start_time
            # Post-repair optimization pass
            try:
                opt_suggestions = [s.to_dict() if hasattr(s, "to_dict") else dict(s) for s in optimize(initial_model)]
            except Exception:
                opt_suggestions = []

            return FileRecord(
                filepath=file_path,
                rel_path=rel_path,
                compiler_status_before=status_before,
                compiler_status_after=status_before,
                error_count_before=0,
                error_count_after=0,
                warning_count_before=warning_count_before,
                warning_count_after=warning_count_before,
                diagnostics=parsed_diags,
                security_findings=sec_findings,
                optimize_suggestions=opt_suggestions,
                stop_reason="not_applicable",
                outcome="not_applicable",
                duration=round(duration, 4),
                original_hash=orig_hash,
                final_hash=orig_hash,
                applied=False,
            )

        # Run planner healing loop inside sandbox
        planner_res: PlannerResult = run_planner(
            temp_file,
            max_iterations=10,
            backup=False,
            apply_to_disk=apply,
        )

        trace_log = planner_res.trace_log or []
        patches_applied = [
            p.to_dict() if hasattr(p, "to_dict") else dict(p)
            for p in (planner_res.patches_applied or getattr(planner_res, "pending_patches", []))
        ] if apply else []
        patches_suggested = [
            p.to_dict() if hasattr(p, "to_dict") else dict(p)
            for p in planner_res.suggestions
        ]
        patches_blocked = _extract_blocked_patches(trace_log)

        # Inspect final state in sandbox from planner_res.model
        final_errors = [d for d in planner_res.model.diagnostics if d.kind in ("error", "linker_error")]
        final_warnings = [d for d in planner_res.model.diagnostics if d.kind == "warning"]
        error_count_after = 0 if planner_res.clean else len(final_errors)
        warning_count_after = len(final_warnings)
        status_after = "error" if error_count_after > 0 else ("warning" if warning_count_after > 0 else "clean")

        if error_count_before == 0:
            is_healed = bool(planner_res.patches_applied or getattr(planner_res, "pending_patches", []))
        else:
            is_healed = planner_res.clean or (error_count_after == 0)
        outcome = "healed" if is_healed else "gave_up"
        stop_reason = "healed" if is_healed else planner_res.status

        # If healed, run optimize pass
        opt_suggestions = []
        if is_healed:
            try:
                opt_suggestions = [s.to_dict() if hasattr(s, "to_dict") else dict(s) for s in optimize(planner_res.model)]
            except Exception:
                opt_suggestions = []

        # Handle --apply
        applied_to_disk = False
        all_candidate_patches = planner_res.patches_applied or getattr(planner_res, "pending_patches", [])
        if apply and is_healed and all_candidate_patches:
            best_patch = all_candidate_patches[0]
            patched_src = getattr(best_patch, "patched_source", None)
            if patched_src:
                with open(file_path, "w", encoding="utf-8") as of:
                    of.write(patched_src)
            else:
                with open(temp_file, "r", encoding="utf-8") as tf:
                    repaired_content = tf.read()
                with open(file_path, "w", encoding="utf-8") as of:
                    of.write(repaired_content)
            applied_to_disk = True

        final_hash = hash_file(file_path)
        duration = time.perf_counter() - start_time

        return FileRecord(
            filepath=file_path,
            rel_path=rel_path,
            compiler_status_before=status_before,
            compiler_status_after=status_after,
            error_count_before=error_count_before,
            error_count_after=error_count_after,
            warning_count_before=warning_count_before,
            warning_count_after=warning_count_after,
            diagnostics=parsed_diags,
            security_findings=sec_findings,
            patches_applied=patches_applied,
            patches_suggested=patches_suggested,
            patches_blocked=patches_blocked,
            optimize_suggestions=opt_suggestions,
            stop_reason=stop_reason,
            outcome=outcome,
            duration=round(duration, 4),
            original_hash=orig_hash,
            final_hash=final_hash,
            applied=applied_to_disk,
            trace_log=trace_log,
        )

    except Exception as ex:
        duration = time.perf_counter() - start_time
        err_str = f"{type(ex).__name__}: {str(ex)}"
        tb_str = traceback.format_exc()
        return FileRecord(
            filepath=file_path,
            rel_path=rel_path,
            compiler_status_before="error",
            compiler_status_after="error",
            error_count_before=1,
            error_count_after=1,
            warning_count_before=0,
            warning_count_after=0,
            stop_reason="crashed",
            outcome="crashed",
            duration=round(duration, 4),
            original_hash=orig_hash,
            final_hash=orig_hash,
            applied=False,
            error_message=f"{err_str}\n{tb_str}",
        )
    finally:
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


def run_batch(
    target_path: str,
    *,
    apply: bool = False,
    timeout: int = 60,
    max_workers: int = 1,
    callback: Optional[Callable[[int, int, FileRecord], None]] = None,
) -> BatchResult:
    """
    Run batch evaluation over a directory or file.

    Parameters
    ----------
    target_path : str
        Directory to scan recursively for *.cpp files, or path to a single *.cpp.
    apply : bool
        If True, write accepted patches back to the original source files.
        Default is False (strictly non-destructive).
    timeout : int
        Per-file timeout limit in seconds.
    callback : callable, optional
        Invoked after each file with (current_index, total_count, record).

    Returns
    -------
    BatchResult
        Structured results including aggregate summary metrics and per-file records.
    """
    start_batch_time = time.perf_counter()
    files = find_cpp_files(target_path)
    base_dir = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)

    records: list[FileRecord] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        if max_workers == 1:
            for idx, fpath in enumerate(files, start=1):
                future = executor.submit(process_single_file, fpath, base_dir=base_dir, apply=apply)
                try:
                    rec = future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    rec = FileRecord(
                        filepath=fpath,
                        rel_path=os.path.relpath(fpath, base_dir),
                        compiler_status_before="error",
                        compiler_status_after="error",
                        error_count_before=1,
                        error_count_after=1,
                        warning_count_before=0,
                        warning_count_after=0,
                        stop_reason="timeout",
                        outcome="crashed",
                        duration=float(timeout),
                        original_hash=hash_file(fpath),
                        final_hash=hash_file(fpath),
                        applied=False,
                        error_message=f"TimeoutExpired: file execution exceeded {timeout}s",
                    )
                except Exception as ex:
                    rec = FileRecord(
                        filepath=fpath,
                        rel_path=os.path.relpath(fpath, base_dir),
                        compiler_status_before="error",
                        compiler_status_after="error",
                        error_count_before=1,
                        error_count_after=1,
                        warning_count_before=0,
                        warning_count_after=0,
                        stop_reason="crashed",
                        outcome="crashed",
                        duration=0.0,
                        original_hash=hash_file(fpath),
                        final_hash=hash_file(fpath),
                        applied=False,
                        error_message=f"{type(ex).__name__}: {str(ex)}",
                    )

                records.append(rec)
                if callback:
                    try:
                        callback(idx, len(files), rec)
                    except Exception:
                        pass
        else:
            # Parallel worker pool with individual file timeouts and deterministic output ordering
            future_to_info = {
                executor.submit(process_single_file, fpath, base_dir=base_dir, apply=apply): (idx, fpath)
                for idx, fpath in enumerate(files, start=1)
            }
            results_by_idx: dict[int, FileRecord] = {}
            done_count = 0

            for future in concurrent.futures.as_completed(future_to_info):
                idx, fpath = future_to_info[future]
                done_count += 1
                try:
                    rec = future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    rec = FileRecord(
                        filepath=fpath,
                        rel_path=os.path.relpath(fpath, base_dir),
                        compiler_status_before="error",
                        compiler_status_after="error",
                        error_count_before=1,
                        error_count_after=1,
                        warning_count_before=0,
                        warning_count_after=0,
                        stop_reason="timeout",
                        outcome="crashed",
                        duration=float(timeout),
                        original_hash=hash_file(fpath),
                        final_hash=hash_file(fpath),
                        applied=False,
                        error_message=f"TimeoutExpired: file execution exceeded {timeout}s",
                    )
                except Exception as ex:
                    rec = FileRecord(
                        filepath=fpath,
                        rel_path=os.path.relpath(fpath, base_dir),
                        compiler_status_before="error",
                        compiler_status_after="error",
                        error_count_before=1,
                        error_count_after=1,
                        warning_count_before=0,
                        warning_count_after=0,
                        stop_reason="crashed",
                        outcome="crashed",
                        duration=0.0,
                        original_hash=hash_file(fpath),
                        final_hash=hash_file(fpath),
                        applied=False,
                        error_message=f"{type(ex).__name__}: {str(ex)}",
                    )

                results_by_idx[idx] = rec
                if callback:
                    try:
                        callback(done_count, len(files), rec)
                    except Exception:
                        pass

            records = [results_by_idx[i] for i in range(1, len(files) + 1)]

    total_batch_time = time.perf_counter() - start_batch_time

    # ── Aggregate metrics ──────────────────────────────────────────────
    healed_count = sum(1 for r in records if r.outcome == "healed")
    gave_up_count = sum(1 for r in records if r.outcome == "gave_up")
    na_count = sum(1 for r in records if r.outcome == "not_applicable")
    crashed_count = sum(1 for r in records if r.outcome == "crashed")
    attempted_count = healed_count + gave_up_count

    heal_rate = (healed_count / attempted_count) if attempted_count > 0 else 0.0

    # Patches by safety tier
    patches_by_safety_tier: dict[str, int] = {}
    for r in records:
        for p in r.patches_applied:
            tier_num = p.get("safety_tier", 1)
            tier_name = p.get("tier_name") or f"Tier {tier_num}"
            patches_by_safety_tier[tier_name] = patches_by_safety_tier.get(tier_name, 0) + 1

    # Patches by safety level (applied and suggested across all files)
    patches_by_safety_level: dict[str, int] = {"S0": 0, "S1": 0, "S2": 0}
    security_patches_by_safety_level: dict[str, int] = {"S0": 0, "S1": 0, "S2": 0}
    files_with_security_patches = 0

    for r in records:
        file_has_sec_patch = False
        all_patches = r.patches_applied + r.patches_suggested
        for p in all_patches:
            lvl = p.get("safety_level", "S0")
            patches_by_safety_level[lvl] = patches_by_safety_level.get(lvl, 0) + 1
            diag = p.get("diagnostic") or {}
            diag_kind = diag.get("kind") if isinstance(diag, dict) else getattr(diag, "kind", "")
            is_sec = (diag_kind == "security") or ("/security/" in r.filepath)
            if is_sec:
                security_patches_by_safety_level[lvl] = security_patches_by_safety_level.get(lvl, 0) + 1
                file_has_sec_patch = True
        if file_has_sec_patch:
            files_with_security_patches += 1

    # Gate failure breakdown
    gate_failure_breakdown: dict[str, int] = {}
    for r in records:
        for pb in r.patches_blocked:
            gate_name = pb.get("failing_gate") or "unknown_gate"
            gate_failure_breakdown[gate_name] = gate_failure_breakdown.get(gate_name, 0) + 1

    # Security findings by CWE
    security_findings_by_cwe: dict[str, int] = {}
    for r in records:
        for sf in r.security_findings:
            cwe_id = sf.get("cwe") or "CWE-Other"
            security_findings_by_cwe[cwe_id] = security_findings_by_cwe.get(cwe_id, 0) + 1

    summary = {
        "total_files": len(records),
        "healed": healed_count,
        "gave_up": gave_up_count,
        "not_applicable": na_count,
        "crashed": crashed_count,
        "attempted": attempted_count,
        "heal_success_rate": round(heal_rate, 4),
        "heal_success_percent": f"{round(heal_rate * 100, 1)}%",
        "patches_by_safety_tier": patches_by_safety_tier,
        "patches_by_safety_level": patches_by_safety_level,
        "security_patches_by_safety_level": security_patches_by_safety_level,
        "files_with_security_patches": files_with_security_patches,
        "gate_failure_breakdown": gate_failure_breakdown,
        "security_findings_by_cwe": security_findings_by_cwe,
        "total_time": round(total_batch_time, 2),
        "apply": apply,
    }

    return BatchResult(
        summary=summary,
        files=[r.to_dict() for r in records],
    )
