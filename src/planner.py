"""
planner.py
──────────
Deterministic state-machine planner that manages tool execution in the
correct order.  Replaces the ad-hoc flow in heal_loop.py with an explicit,
inspectable sequence:

  model = understand(file)
  loop while iterations < max_iterations:
    findings = detect(model)
    if no findings: stop, goal met
    finding = pick highest-priority finding from findings
    patch = repair(model, finding)
    if patch is None: mark unfixable, try next
    result = verify(model, patch)
    if result.passed: apply patch, refresh model = understand(file), continue
    else: roll back, mark failed-verification, try next finding

Stop conditions:
  - "success": no findings left (goal met)
  - "max_iterations": iteration limit reached
  - "no_fixable_finding": all remaining findings are unfixable or failed verification

Accumulates an inspectable structured trace log:
  [{"step": int, "tool_called": str, "input_summary": str, "output_summary": str, "decision": str}, ...]
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Generator, Optional, Sequence

_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from diagnostic import Diagnostic, ProgramModel, Patch, VerifyResult
from tools.understand import understand
from tools.detect import detect
from tools.repair import repair
from tools.optimize import optimize
from tools.verify import verify
from diff_viewer import count_diff_lines, compute_diff
from root_cause_grouper import select_group_representatives
from config_loader import get as cfg_get


class PlanState(Enum):
    INIT = auto()
    UNDERSTAND = auto()
    DETECT = auto()
    REPAIR = auto()
    OPTIMIZE = auto()
    VERIFY = auto()
    REPORT = auto()
    DONE = auto()


@dataclass
class PlanStep:
    """A single step record yielded by the generator-based planner."""
    state: PlanState
    tool: Optional[str] = None
    attempt: int = 0
    max_attempts: int = 10
    diagnostics: list[Diagnostic] = field(default_factory=list)
    security_diagnostics: list[Diagnostic] = field(default_factory=list)
    result: Optional[dict[str, Any]] = None
    status: str = ""


@dataclass
class PlanConfig:
    """Configuration for a planning run."""
    source_path: str
    max_attempts: int = 10
    run_security: bool = True
    log_training: bool = False
    backup_before_repair: bool = True
    review_mode: bool = False


@dataclass
class PlannerResult:
    """Structured outcome returned by run_planner()."""
    status: str                         # "success" | "max_iterations" | "no_fixable_finding"
    iterations: int
    model: ProgramModel
    trace_log: list[dict[str, Any]]     # [{step, tool_called, input_summary, output_summary, decision}]
    patches_applied: list[Patch] = field(default_factory=list)
    suggestions: list[Patch] = field(default_factory=list)
    pending_patches: list[Patch] = field(default_factory=list)
    blocked_attacks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.status == "success"



def _priority_score(d: Diagnostic) -> tuple[int, float]:
    """
    Sort key for picking the highest-priority finding:
    errors (0) before warnings (1) before security (2), then highest confidence first (-conf).
    """
    if d.kind in ("error", "linker_error"):
        kind_rank = 0
    elif d.kind == "warning":
        kind_rank = 1
    elif d.kind == "security":
        kind_rank = 2
    else:
        kind_rank = 3
    return (kind_rank, -d.confidence)


class Planner:
    """Deterministic state-machine planner."""

    def __init__(
        self,
        file_path: str,
        *,
        max_iterations: Optional[int] = None,
        backup: bool = True,
        log_training: bool = False,
        hint: Optional[str] = None,
        review_mode: bool = False,
        apply_to_disk: bool = False,
        on_attempt_start: Optional[Any] = None,
        on_patch_accepted: Optional[Any] = None,
        on_trace_step: Optional[Any] = None,
    ):
        self.file_path = file_path
        self.max_iterations = (
            max_iterations
            if max_iterations is not None
            else cfg_get("pipeline", "max_heal_attempts", 10)
        )
        self.backup = backup
        self.log_training = log_training
        self.hint = hint
        self.review_mode = review_mode
        self.apply_to_disk = apply_to_disk and not review_mode
        self.on_attempt_start = on_attempt_start
        self.on_patch_accepted = on_patch_accepted
        self.on_trace_step = on_trace_step
        self.trace_log: list[dict[str, Any]] = []
        self.patches_applied: list[Patch] = []
        self.suggestions: list[Patch] = []
        self.pending_patches: list[Patch] = []
        self.blocked_attacks: list[dict[str, Any]] = []
        self._step_counter = 0

    def _record_trace(
        self,
        tool_called: str,
        input_summary: str,
        output_summary: str,
        decision: str,
        gate_details: Optional[list[dict[str, Any]]] = None,
        failing_gate: Optional[str] = None,
    ) -> None:
        self._step_counter += 1
        entry: dict[str, Any] = {
            "step": self._step_counter,
            "tool_called": tool_called,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "decision": decision,
        }
        if gate_details is not None:
            entry["gate_details"] = gate_details
        if failing_gate is not None:
            entry["failing_gate"] = failing_gate
        self.trace_log.append(entry)
        if self.on_trace_step:
            try:
                self.on_trace_step(entry)
            except Exception:
                pass

    def run(self) -> PlannerResult:
        """Run the full deterministic planning loop until a stop condition is met."""
        # Capture initial source for review mode restoration
        initial_source = None
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", errors="ignore") as f:
                    initial_source = f.read()
            except Exception:
                pass

        try:
            return self._run_internal(initial_source)
        finally:
            if not self.apply_to_disk and initial_source is not None:
                # Universal Review mode fail-closed: restore original source bytes so the file on disk is untouched
                try:
                    with open(self.file_path, "w", encoding="utf-8") as f:
                        f.write(initial_source)
                except Exception:
                    pass

    def _run_internal(self, initial_source: Optional[str]) -> PlannerResult:
        if self.hint:
            self._record_trace(
                tool_called="planner",
                input_summary=self.file_path,
                output_summary=f"Hint: {self.hint}",
                decision="User guidance hint supplied",
            )

        # Pre-repair backup baseline (Week 3 rollback safety)
        if self.backup:
            bak_path = self.file_path + ".bak"
            try:
                with open(self.file_path, "r", errors="ignore") as f:
                    orig = f.read()
                with open(bak_path, "w") as f:
                    f.write(orig)
            except Exception:
                pass

        # 1. Initial understand
        model = understand(self.file_path, log_training=self.log_training)
        self._record_trace(
            tool_called="understand",
            input_summary=self.file_path,
            output_summary=f"{len(model.diagnostics)} diagnostics parsed",
            decision="Initial analysis complete",
        )

        iterations = 0
        status = "give_up"

        while iterations < self.max_iterations:
            iterations += 1

            # 2. Detect
            findings = detect(model)
            # Check for adversarial prompt injection attacks targeting the agent
            security_attacks = [f for f in findings if f.kind == "security_attack" or f.category == "adversarial_manipulation"]
            if security_attacks:
                self._record_trace(
                    tool_called="security_guardrail",
                    input_summary=f"{len(security_attacks)} prompt injection payload(s) intercepted in source",
                    output_summary="SECURITY: instruction injection detected and blocked",
                    decision="Refuse automated execution of untrusted directives; enforce agent control integrity",
                )
                for sa in security_attacks:
                    att_det = getattr(sa, "attack_detection", {}) or {}
                    blocked_item = {
                        "type": "instruction_injection",
                        "attack_type": att_det.get("attack_type", "instruction_injection"),
                        "surface": att_det.get("surface", "line_comment"),
                        "gate": "security_guardrail",
                        "detector": "Agent Security Guardrail (Prompt Injection Scanner)",
                        "attempted": f"Adversarial instruction injection: {sa.message}",
                        "reason": sa.message,
                        "snippet": att_det.get("snippet", sa.message),
                        "risk_score": att_det.get("risk_score", getattr(sa, "confidence", 0.90)),
                        "risk_tier": getattr(sa, "risk_tier", att_det.get("risk_tier", "HIGH")),
                        "action_taken": "blocked",
                        "line": sa.line or 1,
                    }
                    if not any(b.get("snippet") == blocked_item["snippet"] for b in self.blocked_attacks):
                        self.blocked_attacks.append(blocked_item)

            # Only consider actionable errors/warnings/security
            hard_errors = [f for f in findings if f.kind in ("error", "linker_error")]
            warnings = [f for f in findings if f.kind == "warning"]
            security = [f for f in findings if f.kind == "security"]

            self._record_trace(
                tool_called="detect",
                input_summary=f"Model with {len(model.diagnostics)} diags",
                output_summary=f"{len(findings)} total findings ({len(hard_errors)} errors, {len(warnings)} warnings, {len(security)} security)",
                decision="Evaluate findings for repair",
            )

            # If no hard errors, warnings, or security findings, check if goal is met
            if not hard_errors and not warnings and not security:
                gate6_blocked_count = sum(
                    1 for b in self.blocked_attacks if b.get("gate") == "gate6_patch_security"
                )
                if gate6_blocked_count > 0:
                    plural = "attempt" if gate6_blocked_count == 1 else "attempts"
                    decision_str = f"Goal met: compilation clean and secure ({gate6_blocked_count} malicious patch {plural} blocked during this session)"
                else:
                    decision_str = "Goal met: no findings remaining"
                self._record_trace(
                    tool_called="planner",
                    input_summary="0 findings",
                    output_summary="Clean compilation",
                    decision=decision_str,
                )
                status = "success"
                break

            # If no hard errors and no security findings remain, file compiles successfully and has no security issues
            if not hard_errors and not security:
                gate6_blocked_count = sum(
                    1 for b in self.blocked_attacks if b.get("gate") == "gate6_patch_security"
                )
                if gate6_blocked_count > 0:
                    plural = "attempt" if gate6_blocked_count == 1 else "attempts"
                    decision_str = f"Goal met: compilation clean and secure ({gate6_blocked_count} malicious patch {plural} blocked during this session)"
                else:
                    decision_str = "Goal met: no hard errors remaining"
                self._record_trace(
                    tool_called="planner",
                    input_summary=f"{len(warnings)} warnings remaining, 0 errors, 0 security issues",
                    output_summary="Clean compilation achieved",
                    decision=decision_str,
                )
                status = "success"
                break

            # Prioritize findings using root-cause representative selection
            actionable = [f for f in findings if f.kind in ("error", "warning", "security")]
            try:
                actionable = select_group_representatives(actionable)
            except Exception:
                actionable.sort(key=_priority_score)

            patch_found: Optional[Patch] = None
            target_finding: Optional[Diagnostic] = None
            unfixable_count = 0

            attempt_notified = False
            for candidate in actionable:
                if self.on_attempt_start and not attempt_notified:
                    try:
                        self.on_attempt_start(iterations, candidate)
                    except Exception:
                        pass
                    attempt_notified = True

                # 3. Repair (Gate-driven candidate fallback)
                patch_candidates = repair(model, candidate)
                if patch_candidates is None:
                    cand_list = []
                elif isinstance(patch_candidates, list):
                    cand_list = list(patch_candidates)
                else:
                    cand_list = [patch_candidates]
                self._record_trace(
                    tool_called="repair",
                    input_summary=f"Finding line {candidate.line}: {candidate.message[:50]}",
                    output_summary=f"{len(cand_list)} candidate patch(es) generated" if cand_list else "No patch available",
                    decision="Evaluate candidate patches through verify()" if cand_list else "Mark finding unfixable",
                )

                if not cand_list:
                    unfixable_count += 1
                    continue

                finding_healed = False
                failed_candidates: list[Patch] = []
                best_patch: Optional[Patch] = None
                best_verify_res: Optional[VerifyResult] = None

                for cand_idx, patch in enumerate(cand_list):
                    tier_label = getattr(patch, "tier_name", f"Tier {getattr(patch, 'safety_tier', '?')}")
                    diff_source = patch.diff
                    if not diff_source and initial_source and getattr(patch, "patched_source", None):
                        diff_source = compute_diff(initial_source, patch.patched_source)
                    diff_count = count_diff_lines(diff_source)

                    # 4. Verify candidate patch through gate pipeline
                    verify_res = verify(model, patch)
                    failing_gate = getattr(verify_res, "failing_gate", None)
                    failing_reason = getattr(verify_res, "failing_reason", None)
                    gate_results = getattr(verify_res, "gate_results", [])

                    # Safety Gate: In direct auto-apply mode, S2 repairs alter program semantics and must not be auto-applied
                    if getattr(patch, "suggestion_only", False) or (getattr(patch, "safety_level", "") == "S2" and self.apply_to_disk):
                        patch.suggestion_only = True
                        failed_candidates.append(patch)
                        summary_msg = f"{'passed=True across all gates' if verify_res.passed else 'passed=False, failed ' + str(failing_gate or 'verification_gate') + ': ' + str(failing_reason or 'validation failed')}, S2 suggestion only"
                        self._record_trace(
                            tool_called="verify",
                            input_summary=f"Candidate {cand_idx+1}/{len(cand_list)} ({tier_label}, {diff_count} diff lines, {patch.safety_level})",
                            output_summary=summary_msg,
                            decision="Surface patch as suggestion for manual review; do not auto-apply (S2)",
                            gate_details=gate_results,
                            failing_gate=failing_gate if not verify_res.passed else None,
                        )
                        continue

                    if verify_res.passed:
                        action_decision = "Apply patch and refresh model" if self.apply_to_disk else "Queue candidate patch for review (pending explicit user accept)"
                        self._record_trace(
                            tool_called="verify",
                            input_summary=f"Candidate {cand_idx+1}/{len(cand_list)} ({tier_label}, {diff_count} diff lines, {patch.safety_level})",
                            output_summary=f"passed=True across all gates, {len(verify_res.diagnostics)} diagnostics",
                            decision=action_decision,
                            gate_details=gate_results,
                        )
                        # Clean compilation: immediate optimal heal
                        if len(verify_res.diagnostics) == 0:
                            best_patch = patch
                            best_verify_res = verify_res
                            break
                        # Otherwise remember first candidate that passed
                        if best_patch is None:
                            best_patch = patch
                            best_verify_res = verify_res
                    else:
                        # Candidate failed verification: roll back and try next candidate
                        is_malicious = (failing_gate == "gate6_patch_security")
                        if not is_malicious:
                            patch.suggestion_only = True
                            failed_candidates.append(patch)

                        # Roll back to pre-patch backup
                        if initial_source is not None:
                            try:
                                with open(self.file_path, "w") as f:
                                    f.write(initial_source)
                            except Exception:
                                pass
                        elif self.backup:
                            bak_path = self.file_path + ".bak"
                            if os.path.exists(bak_path):
                                try:
                                    with open(bak_path, "r", errors="ignore") as f:
                                        orig_src = f.read()
                                    with open(self.file_path, "w") as f:
                                        f.write(orig_src)
                                except Exception:
                                    pass

                        gate_name = failing_gate or "verification_gate"
                        reason_str = failing_reason or "validation gate failed"
                        decision_str = (
                            "SECURITY: malicious patch detected and blocked (purged from suggestions)"
                            if is_malicious else
                            f"Reject candidate and try fallback (failed {gate_name})"
                        )
                        self._record_trace(
                            tool_called="verify",
                            input_summary=f"Candidate {cand_idx+1}/{len(cand_list)} ({tier_label}, {diff_count} diff lines, {patch.safety_level})",
                            output_summary=f"passed=False, failed {gate_name}: {reason_str}",
                            decision=decision_str,
                            gate_details=gate_results,
                            failing_gate=failing_gate,
                        )
                        if is_malicious:
                            self._record_trace(
                                tool_called="GATE6_SECURITY_BLOCK",
                                input_summary=f"Malicious patch candidate #{cand_idx+1}: {reason_str}",
                                output_summary=f"SECURITY: gate6_patch_security blocked malicious backdoor ({reason_str})",
                                decision="Refuse application of malicious patch; purge from suggestions; enforce gate integrity",
                                gate_details=gate_results,
                                failing_gate="gate6_patch_security",
                            )
                            blocked_item = {
                                "type": "malicious_patch",
                                "attack_type": "malicious_patch",
                                "surface": "patch_diff",
                                "gate": "gate6_patch_security",
                                "detector": "Gate 6: Patch Content Security Audit (gate6_patch_security)",
                                "attempted": f"Malicious exfiltration patch: {reason_str}",
                                "reason": reason_str,
                                "risk_score": 0.95,
                                "risk_tier": "CRITICAL",
                                "patch": patch,
                                "diff": patch.diff,
                                "snippet": getattr(patch, "patched_source", reason_str),
                                "action_taken": "blocked",
                                "line": getattr(patch.diagnostic, "line", 1) if patch.diagnostic else 1,
                            }
                            self.blocked_attacks.append(blocked_item)

                if best_patch is not None:
                    patch_found = best_patch
                    target_finding = candidate
                    finding_healed = True
                    # Attach verification gate details to the patch
                    best_patch.verify_result = best_verify_res
                    best_patch.gate_results = getattr(best_verify_res, "gate_results", [])
                    if not any(p.patched_source == best_patch.patched_source for p in self.pending_patches):
                        self.pending_patches.append(best_patch)

                    # Re-write the accepted patch to disk so compiler/understand can progress in simulation
                    with open(self.file_path, "w") as f:
                        f.write(best_patch.patched_source)
                    if self.on_patch_accepted:
                        try:
                            self.on_patch_accepted(iterations, patch_found, best_verify_res)
                        except Exception:
                            pass
                    break
                else:
                    # All candidates failed for this finding: downgrade to suggestion-only
                    for p in failed_candidates:
                        if p not in self.suggestions:
                            self.suggestions.append(p)
                    unfixable_count += 1
                    continue

            if patch_found is None:
                self._record_trace(
                    tool_called="planner",
                    input_summary=f"{len(actionable)} findings evaluated",
                    output_summary=f"{unfixable_count} unfixable",
                    decision="Stop: no fixable finding found",
                )
                status = "no_fixable_finding"
                break

            # Apply the accepted patch to disk if apply_to_disk is explicitly enabled
            if self.apply_to_disk:
                try:
                    with open(self.file_path, "w") as f:
                        f.write(patch_found.patched_source)
                    self.patches_applied.append(patch_found)
                except Exception:
                    pass

            # Refresh model
            model = understand(self.file_path, log_training=self.log_training)
            self._record_trace(
                tool_called="understand",
                input_summary=self.file_path,
                output_summary=f"Model refreshed: {len(model.diagnostics)} diags remaining",
                decision="Continue loop with refreshed model",
            )

            # Check if refreshed model is clean (both compilation and security)
            remaining_findings = detect(model)
            remaining_errors = [d for d in remaining_findings if d.kind in ("error", "linker_error")]
            remaining_security = [d for d in remaining_findings if d.kind == "security"]
            if not remaining_errors and not remaining_security:
                status = "success"
                gate6_blocked_count = sum(
                    1 for b in self.blocked_attacks if b.get("gate") == "gate6_patch_security"
                )
                if gate6_blocked_count > 0:
                    plural = "attempt" if gate6_blocked_count == 1 else "attempts"
                    decision_text = f"Goal met: compilation clean and secure ({gate6_blocked_count} malicious patch {plural} blocked during this session)"
                else:
                    decision_text = "Goal met: compilation clean and secure"
                self._record_trace(
                    tool_called="planner",
                    input_summary="0 remaining errors and 0 security issues",
                    output_summary="Program healed successfully",
                    decision=decision_text,
                )
                break

        if iterations >= self.max_iterations and status not in ("success", "no_fixable_finding"):
            status = "max_iterations"
            self._record_trace(
                tool_called="planner",
                input_summary=f"{iterations} iterations reached",
                output_summary=f"Limit {self.max_iterations} exceeded",
                decision="Stop: max iterations reached",
            )

        if not self.apply_to_disk and initial_source is not None:
            # Universal Review mode fail-closed: restore original source bytes so the file on disk is untouched
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    f.write(initial_source)
            except Exception:
                pass

        return PlannerResult(
            status=status,
            iterations=iterations,
            model=model,
            trace_log=self.trace_log,
            patches_applied=self.patches_applied if self.apply_to_disk else [],
            suggestions=self.suggestions,
            pending_patches=self.pending_patches,
            blocked_attacks=self.blocked_attacks,
        )


def run_planner(
    file_path: str,
    *,
    max_iterations: Optional[int] = None,
    backup: bool = True,
    log_training: bool = False,
    hint: Optional[str] = None,
    review_mode: bool = False,
    apply_to_disk: bool = False,
    on_attempt_start: Optional[Any] = None,
    on_patch_accepted: Optional[Any] = None,
    on_trace_step: Optional[Any] = None,
) -> PlannerResult:
    """Convenience runner that executes the Planner and returns PlannerResult."""
    planner = Planner(
        file_path,
        max_iterations=max_iterations,
        backup=backup,
        log_training=log_training,
        hint=hint,
        review_mode=review_mode,
        apply_to_disk=apply_to_disk,
        on_attempt_start=on_attempt_start,
        on_patch_accepted=on_patch_accepted,
        on_trace_step=on_trace_step,
    )
    return planner.run()


def plan(config: PlanConfig) -> Generator[PlanStep, None, None]:
    """
    Generator-based planner interface for callers that drive execution step-by-step.
    Yields PlanStep records as it walks through the pipeline.
    """
    attempt = 0
    model = understand(config.source_path, log_training=config.log_training)

    yield PlanStep(
        state=PlanState.UNDERSTAND,
        tool="understand",
        diagnostics=model.diagnostics,
        status="error" if any(d.kind in ("error", "linker_error") for d in model.diagnostics) else "success",
    )

    security_diags = []
    if config.run_security:
        security_diags = [d for d in detect(model) if d.kind == "security"]

    yield PlanStep(
        state=PlanState.DETECT,
        tool="detect",
        diagnostics=model.diagnostics,
        security_diagnostics=security_diags,
        status="clean" if not security_diags else "findings",
    )

    errors_only = [d for d in model.diagnostics if d.kind in ("error", "linker_error")]
    if not errors_only:
        yield PlanStep(
            state=PlanState.REPORT,
            diagnostics=model.diagnostics,
            security_diagnostics=security_diags,
            status="success",
        )
        yield PlanStep(state=PlanState.DONE, status="success")
        return

    # Run repair loop
    if config.backup_before_repair:
        bak = config.source_path + ".bak"
        if not os.path.exists(bak):
            try:
                with open(config.source_path, "r", errors="ignore") as f:
                    orig = f.read()
                with open(bak, "w") as f:
                    f.write(orig)
            except Exception:
                pass

    while attempt < config.max_attempts and errors_only:
        attempt += 1
        target = errors_only[0]

        patch = repair(model, target)
        yield PlanStep(
            state=PlanState.REPAIR,
            tool="repair",
            attempt=attempt,
            max_attempts=config.max_attempts,
            diagnostics=model.diagnostics,
            result={"fixed": patch is not None, "target": target.message},
            status="fixed" if patch else "unfixable",
        )

        if patch is None:
            errors_only = errors_only[1:]
            continue

        if getattr(patch, "suggestion_only", False) or getattr(patch, "safety_level", "") == "S2":
            yield PlanStep(
                state=PlanState.REPAIR,
                tool="repair",
                attempt=attempt,
                max_attempts=config.max_attempts,
                diagnostics=model.diagnostics,
                result={"fixed": False, "target": target.message, "suggestion_only": True, "patch": patch.to_dict()},
                status="suggestion_only",
            )
            errors_only = errors_only[1:]
            continue

        suggestions = optimize(model)
        yield PlanStep(
            state=PlanState.OPTIMIZE,
            tool="optimize",
            attempt=attempt,
            result={"suggestions": len(suggestions)},
            status="accepted",
        )

        v_res = verify(model, patch)
        yield PlanStep(
            state=PlanState.VERIFY,
            tool="verify",
            attempt=attempt,
            diagnostics=v_res.diagnostics,
            security_diagnostics=[],
            result=v_res.to_dict(),
            status="success" if v_res.passed else "error",
        )

        if not v_res.passed:
            patch.suggestion_only = True
            if config.backup_before_repair:
                bak = config.source_path + ".bak"
                if os.path.exists(bak):
                    try:
                        with open(bak, "r", errors="ignore") as f:
                            orig = f.read()
                        with open(config.source_path, "w") as f:
                            f.write(orig)
                    except Exception:
                        pass
            errors_only = errors_only[1:]
            continue

        # Apply patch
        try:
            with open(config.source_path, "w") as f:
                f.write(patch.patched_source)
        except Exception:
            pass

        model = understand(config.source_path, log_training=config.log_training)
        errors_only = [d for d in model.diagnostics if d.kind in ("error", "linker_error")]

        if not errors_only:
            break

    final_status = "success" if not errors_only else "give_up"
    yield PlanStep(
        state=PlanState.REPORT,
        attempt=attempt,
        max_attempts=config.max_attempts,
        diagnostics=model.diagnostics,
        security_diagnostics=security_diags,
        status=final_status,
    )
    yield PlanStep(state=PlanState.DONE, status=final_status)
