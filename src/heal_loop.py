"""
heal_loop.py
------------
Orchestrates the auto-healing pipeline for PyQt6 GUI compatibility.
Refactored to eliminate duplication by delegating directly to Planner and src/tools/.

Flow:
  1. Delegates to Planner (planner.py), driving tools:
     understand() -> detect() -> repair() -> verify()
  2. Emits live PyQt6 signals:
     - attempt_started(attempt_no: int, error: dict)
     - diff_ready(attempt_no: int, diff_html: str)
     - compile_clean()
     - give_up(history: list[dict])
     - error_signal(message: str)
     - lines_fixed(list[int])
     - telemetry_ready(list[dict])
  3. Records identical trace log, patches, and stop conditions as main.py's run_planner().
"""

from __future__ import annotations

import os
import sys
import time
import re
from typing import Optional, Any

try:
    from PyQt6.QtCore import QThread, pyqtSignal
except ImportError:
    class QThread:
        def __init__(self, *args, **kwargs):
            pass
    def pyqtSignal(*args, **kwargs):
        class _Signal:
            def emit(self, *a, **kw): pass
            def connect(self, *a, **kw): pass
        return _Signal()

_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from diagnostic import Diagnostic, Patch, VerifyResult
from tools.understand import understand
from auto_healer import attempt_fix, UNFIXABLE_CATEGORIES
from diff_viewer import compute_diff, format_diff_html, has_changes
from healing_suggester import suggest_failed_heal
from planner import Planner, PlannerResult, run_planner

try:
    from codecarbon import EmissionsTracker
    HAS_CODECARBON = True
except ImportError:
    HAS_CODECARBON = False

try:
    from config_loader import get as cfg_get
    MAX_ATTEMPTS = int(cfg_get("pipeline", "max_heal_attempts", 10))
except Exception:
    MAX_ATTEMPTS = 10

_ERR_PATTERN = re.compile(
    r"^(.+?):(\d+):(\d+):\s*(error|warning):\s*(.*)$"
)


def _compile(file_path: str) -> tuple[list[dict], str]:
    """
    Backward-compatible compile wrapper. Delegates to understand(file_path).
    Returns (error_list, raw_stderr).
    """
    model = understand(file_path)
    return [d.to_dict() for d in model.diagnostics], model.compile_output


def _pre_scan(source: str) -> list[dict]:
    """Backward-compatible stub for legacy callers."""
    return []


def _classify_errors(errors: list[dict], classifier=None) -> list[dict]:
    """Backward-compatible classification stub."""
    return errors


def _pick_fix_target(issues: list[dict]) -> Optional[dict]:
    """Backward-compatible fix target picker."""
    for issue_type in ("error", "warning"):
        for issue in issues:
            if issue.get("type") != issue_type:
                continue
            if issue.get("category") in UNFIXABLE_CATEGORIES:
                continue
            return issue
    return None


class HealWorker(QThread):
    """
    QThread that drives auto-healing via Planner, emitting live GUI signals.
    Guarantees identical patches, stop conditions, and trace structure to run_planner().
    """
    attempt_started = pyqtSignal(int, dict)          # (attempt_no, error)
    diff_ready      = pyqtSignal(int, str)            # (attempt_no, diff_html)
    compile_clean   = pyqtSignal()
    give_up         = pyqtSignal(list)                # history list
    error_signal    = pyqtSignal(str)                 # fatal/internal errors
    hint_required   = pyqtSignal(int, dict, list)     # (attempt_no, error, history)
    lines_fixed     = pyqtSignal(list)                # [line_no, ...]
    telemetry_ready = pyqtSignal(list)                # list[dict]
    trace_step      = pyqtSignal(dict)                # live step emitted from planner trace
    patches_for_review = pyqtSignal(list)             # list[Patch] for review mode

    def __init__(self, file_path: str, classifier=None, hint: Optional[str] = None, review_mode: bool = False):
        super().__init__()
        self.file_path  = file_path
        self.classifier = classifier
        self.hint       = hint          # optional user guidance from previous round
        self.review_mode = review_mode
        self.trace_log: list[dict[str, Any]] = []
        self.patches_applied: list[Patch] = []
        self.pending_patches: list[Patch] = []
        self.suggestions: list[Patch] = []
        self.blocked_attacks: list[dict[str, Any]] = []
        self.status: str = ""

    def run(self):
        project_dir = os.path.dirname(os.path.abspath(self.file_path))
        main_tracker = None
        if HAS_CODECARBON:
            try:
                main_tracker = EmissionsTracker(
                    project_name="self_healing_compiler",
                    measure_power_secs=1,
                    log_level="error",
                    save_to_file=True,
                    output_dir=project_dir,
                    output_file="emissions.csv"
                )
                main_tracker.start()
            except Exception:
                main_tracker = None

        try:
            telemetry = self._heal()
            self.telemetry_ready.emit(telemetry)
        except Exception as exc:
            self.error_signal.emit(str(exc))
        finally:
            if main_tracker:
                try:
                    main_tracker.stop()
                except Exception:
                    pass

    def _attach_failure_suggestion(self, history: list[dict], error: dict, source: str) -> None:
        if not error:
            return
        error["suggestion"] = suggest_failed_heal(error, source, history)

    def _heal(self) -> list[dict]:
        history = []
        telemetry = []
        project_dir = os.path.dirname(os.path.abspath(self.file_path))

        with open(self.file_path, "r", encoding="utf-8") as f:
            source = f.read()

        if self.hint:
            history.append({"type": "hint", "text": self.hint})

        attempt_tracker = [None]
        attempt_start_time = [time.time()]

        def on_attempt_start(attempt: int, candidate: Diagnostic):
            attempt_start_time[0] = time.time()
            if HAS_CODECARBON:
                try:
                    attempt_tracker[0] = EmissionsTracker(
                        project_name="self_healing_compiler",
                        measure_power_secs=1,
                        log_level="error",
                        save_to_file=True,
                        output_dir=project_dir,
                        output_file="emissions.csv"
                    )
                    attempt_tracker[0].start()
                except Exception:
                    attempt_tracker[0] = None

            target = candidate.to_dict()
            # P1 seen_errors key tracking invariant:
            error_key = (target.get("message"), target.get("line"))
            self.attempt_started.emit(attempt, target)

        def on_patch_accepted(attempt: int, patch: Patch, verify_res: VerifyResult):
            diff_html = format_diff_html(patch.diff) if has_changes(patch.diff) else "<i>No visible changes.</i>"
            self.diff_ready.emit(attempt, diff_html)

            fixed_line_nos = [
                d.line_no_new for d in patch.diff
                if getattr(d, 'kind', '') == "+" and getattr(d, 'line_no_new', None) is not None
            ]
            self.lines_fixed.emit(fixed_line_nos)

            diag_dict = patch.diagnostic.to_dict() if patch.diagnostic else {}
            history.append({
                "attempt": attempt,
                "error": diag_dict,
                "patch": patch.patched_source,
                "diff_html": diff_html,
            })

            # Telemetry computation
            attempt_duration = time.time() - attempt_start_time[0]
            attempt_emissions = 0.0
            if attempt_tracker[0]:
                try:
                    attempt_emissions = attempt_tracker[0].stop()
                except Exception:
                    pass

            cat = patch.diagnostic.category if patch.diagnostic else "unknown"
            telemetry.append({
                "attempt": attempt,
                "category": cat or "unknown",
                "success": True,
                "duration": round(attempt_duration, 3),
                "emissions": attempt_emissions,
            })

        def on_trace_step(step_entry: dict):
            try:
                self.trace_step.emit(step_entry)
            except Exception:
                pass

        planner = Planner(
            self.file_path,
            max_iterations=MAX_ATTEMPTS,
            backup=True,
            hint=self.hint,
            review_mode=self.review_mode,
            on_attempt_start=on_attempt_start,
            on_patch_accepted=on_patch_accepted,
            on_trace_step=on_trace_step,
        )

        res = planner.run()
        self.trace_log = res.trace_log
        self.patches_applied = res.patches_applied
        self.pending_patches = getattr(res, "pending_patches", [])
        self.suggestions = getattr(res, "suggestions", [])
        self.blocked_attacks = getattr(res, "blocked_attacks", [])
        self.status = res.status

        all_review = list(self.pending_patches) + [p for p in self.suggestions if p not in self.pending_patches]
        self.patches_for_review.emit(all_review)

        # Read latest source (untouched on disk in universal review mode)
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception:
            pass

        if res.clean or res.status in ("clean", "success"):
            self.compile_clean.emit()
            return telemetry

        # On failure or exhaustion, prepare history & suggestion
        last_error = next((item.get("error") for item in reversed(history) if item.get("error")), None)
        if not last_error and res.model and res.model.diagnostics:
            last_error = res.model.diagnostics[0].to_dict()
        if not last_error:
            last_error = {}

        history.append({
            "attempt": res.iterations,
            "error": last_error,
            "patch": None,
            "reason": res.status,
        })
        self._attach_failure_suggestion(history, last_error, source)
        self.give_up.emit(history)
        return telemetry
