"""
src/feedback_store.py
─────────────────────
Storage layer for human feedback signals:
1. Category corrections (confirmed_feedback.json):
   Records human-verified diagnostic categories for classifier retraining.
   Saved atomically (temp-file + os.replace) to prevent corruption.
   Must be explicitly reviewed (reviewed_for_merge: true) before merging into training data.

2. Patch decisions (patch_feedback.jsonl):
   Append-only log of repair quality decisions (accepted, rejected, undone).
   Preserves full history. Never used as classifier training data.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile
from typing import Any, List, Optional, Sequence, Union

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
DEFAULT_FEEDBACK_FILE = os.path.join(_DATA_DIR, "confirmed_feedback.json")
DEFAULT_PATCH_FEEDBACK_FILE = os.path.join(_DATA_DIR, "patch_feedback.jsonl")


# ── Category Corrections Storage (Atomic JSON) ──────────────────────────


def save_feedback_atomic(records: List[dict], feedback_file: str = DEFAULT_FEEDBACK_FILE) -> None:
    """
    Atomically write feedback records to feedback_file using a temp file and os.replace.
    Ensures that process crashes or mid-write interruptions never leave a corrupt or partial file.
    """
    dir_name = os.path.dirname(os.path.abspath(feedback_file))
    os.makedirs(dir_name, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix="feedback_", suffix=".tmp", dir=dir_name)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, feedback_file)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def record_feedback(
    diagnostic: Any,
    confirmed_category: str,
    user_notes: Optional[str] = None,
    feedback_file: str = DEFAULT_FEEDBACK_FILE,
    program_id: Optional[str] = None,
) -> dict:
    """
    Append a human-confirmed diagnostic classification correction to storage atomically.

    Parameters
    ----------
    diagnostic : Diagnostic, CompilerError, or dict
        The diagnostic object or dict containing error details.
    confirmed_category : str
        The human-verified ground-truth category.
    user_notes : Optional[str]
        Optional explanation or rationale provided by the reviewer.
    feedback_file : str
        Target JSON file to append feedback to (default: data/confirmed_feedback.json).
    program_id : Optional[str]
        Optional program/template identifier for program-level train/test split isolation.

    Returns
    -------
    dict
        The newly recorded feedback entry record.
    """
    if not confirmed_category or not str(confirmed_category).strip():
        raise ValueError("confirmed_category must be a non-empty string.")

    # Extract fields from diagnostic object or dict
    if isinstance(diagnostic, dict):
        msg = diagnostic.get("message", "")
        pred_cat = diagnostic.get("category")
        conf = diagnostic.get("confidence", 0.0)
        ast_node = diagnostic.get("ast_node_type") or diagnostic.get("ast_node")
        ast_fb = diagnostic.get("ast_fallback")
        file_path = diagnostic.get("file")
        line = diagnostic.get("line")
        prog_id = (
            program_id
            or diagnostic.get("program_id")
            or diagnostic.get("template_id")
            or file_path
        )
    else:
        msg = getattr(diagnostic, "message", "")
        pred_cat = getattr(diagnostic, "category", None)
        conf = getattr(diagnostic, "confidence", 0.0)
        ast_node = getattr(diagnostic, "ast_node_type", None) or getattr(diagnostic, "ast_node", None)
        ast_fb = getattr(diagnostic, "ast_fallback", None)
        file_path = getattr(diagnostic, "file", None)
        line = getattr(diagnostic, "line", None)
        prog_id = (
            program_id
            or getattr(diagnostic, "program_id", None)
            or getattr(diagnostic, "template_id", None)
            or file_path
        )

    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "message": msg,
        "predicted_category": pred_cat,
        "confirmed_category": confirmed_category.strip().lower(),
        "confidence": float(conf) if conf is not None else 0.0,
        "ast_node": ast_node,
        "ast_fallback": ast_fb,
        "file": file_path,
        "program_id": prog_id,
        "template_id": prog_id,
        "line": line,
        "user_notes": user_notes or "",
        "reviewed_for_merge": False,
    }

    records = load_feedback(feedback_file)
    records.append(record)
    save_feedback_atomic(records, feedback_file)
    return record


def load_feedback(feedback_file: str = DEFAULT_FEEDBACK_FILE) -> List[dict]:
    """Read all recorded category feedback entries from storage."""
    if not os.path.exists(feedback_file):
        return []

    try:
        with open(feedback_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def clear_feedback(feedback_file: str = DEFAULT_FEEDBACK_FILE) -> None:
    """Clear feedback file (primarily for unit testing)."""
    if os.path.exists(feedback_file):
        os.remove(feedback_file)


# ── Patch Decisions Log (Append-Only JSONL) ──────────────────────────────


def compute_file_hash(content: Union[bytes, str]) -> str:
    """Compute SHA-256 hex digest of file bytes or text string."""
    if isinstance(content, str):
        content = content.encode("utf-8", errors="ignore")
    return hashlib.sha256(content).hexdigest()


def log_patch_decision(
    file_path: str,
    patch: Any,
    decision: str,  # "accepted" | "rejected" | "undone"
    pre_patch_bytes: Optional[bytes] = None,
    log_file: str = DEFAULT_PATCH_FEEDBACK_FILE,
    patch_id: Optional[int] = None,
    ref_patch_id: Optional[int] = None,
    ref_timestamp: Optional[str] = None,
) -> dict:
    """
    Append a patch review decision to data/patch_feedback.jsonl.
    Append-only: full history is preserved. Undoing a patch appends a new record
    with decision='undone' referencing the original accept.
    """
    if decision not in ("accepted", "rejected", "undone"):
        raise ValueError(f"Invalid patch decision: '{decision}', must be 'accepted', 'rejected', or 'undone'.")

    # Compute content hash
    if pre_patch_bytes is not None:
        file_hash = compute_file_hash(pre_patch_bytes)
    elif os.path.exists(file_path):
        try:
            with open(file_path, "rb") as f:
                file_hash = compute_file_hash(f.read())
        except Exception:
            file_hash = ""
    else:
        file_hash = ""

    # Diagnostic metadata
    diag = getattr(patch, "diagnostic", None) if patch else None
    if isinstance(diag, dict):
        diag_dict = {
            "message": diag.get("message", ""),
            "line": diag.get("line"),
            "category": diag.get("category"),
        }
    elif diag is not None:
        diag_dict = {
            "message": getattr(diag, "message", ""),
            "line": getattr(diag, "line", None),
            "category": getattr(diag, "category", None),
        }
    else:
        diag_dict = {"message": "", "line": None, "category": None}

    # Safety attributes
    safety_tier = getattr(patch, "safety_tier", 1)
    safety_level = getattr(patch, "safety_level", "S0")
    tier_name = getattr(patch, "tier_name", "Tier 1: Compiler Fix-It")

    # Verification gate results
    gate_results_raw = getattr(patch, "gate_results", [])
    if not gate_results_raw:
        vr = getattr(patch, "verify_result", None)
        if vr:
            gate_results_raw = getattr(vr, "gate_results", [])

    gate_results = []
    for g in gate_results_raw or []:
        if isinstance(g, dict):
            gate_results.append(g)
        elif hasattr(g, "__dict__"):
            gate_results.append({
                "gate": getattr(g, "gate_name", getattr(g, "gate", "gate")),
                "passed": getattr(g, "passed", True),
                "reason": getattr(g, "reason", getattr(g, "output_summary", "")),
            })

    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "file_hash": file_hash,
        "patch_id": patch_id,
        "diagnostic": diag_dict,
        "safety_tier": int(safety_tier) if safety_tier is not None else 1,
        "safety_level": str(safety_level) if safety_level is not None else "S0",
        "tier_name": str(tier_name) if tier_name else "",
        "decision": decision,
        "gate_results": gate_results,
        "ref_patch_id": ref_patch_id,
        "ref_timestamp": ref_timestamp,
    }

    dir_name = os.path.dirname(os.path.abspath(log_file))
    os.makedirs(dir_name, exist_ok=True)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record


def load_patch_feedback(log_file: str = DEFAULT_PATCH_FEEDBACK_FILE) -> List[dict]:
    """Read all patch feedback records from the JSONL log."""
    if not os.path.exists(log_file):
        return []
    records = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


def clear_patch_feedback(log_file: str = DEFAULT_PATCH_FEEDBACK_FILE) -> None:
    """Clear patch feedback log file (for unit testing)."""
    if os.path.exists(log_file):
        os.remove(log_file)


# ── Human Review CLI Helper ─────────────────────────────────────────────


def list_unreviewed_feedback(feedback_file: str = DEFAULT_FEEDBACK_FILE) -> List[tuple[int, dict]]:
    """Return list of (original_index, record) for unreviewed feedback entries."""
    records = load_feedback(feedback_file)
    return [(idx, r) for idx, r in enumerate(records) if not r.get("reviewed_for_merge", False)]


def mark_feedback_reviewed(
    indices: Sequence[int],
    approved: bool = True,
    feedback_file: str = DEFAULT_FEEDBACK_FILE,
) -> int:
    """
    Mark specific feedback records as reviewed_for_merge = approved.
    Returns the count of records updated.
    """
    records = load_feedback(feedback_file)
    updated = 0
    idx_set = set(indices)
    for idx, r in enumerate(records):
        if idx in idx_set:
            r["reviewed_for_merge"] = approved
            r["reviewed_timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            updated += 1
    if updated > 0:
        save_feedback_atomic(records, feedback_file)
    return updated


def approve_all_feedback(feedback_file: str = DEFAULT_FEEDBACK_FILE) -> int:
    """Mark all currently unreviewed feedback records as reviewed_for_merge = True."""
    records = load_feedback(feedback_file)
    updated = 0
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for r in records:
        if not r.get("reviewed_for_merge", False):
            r["reviewed_for_merge"] = True
            r["reviewed_timestamp"] = now
            updated += 1
    if updated > 0:
        save_feedback_atomic(records, feedback_file)
    return updated


def _cli_review():
    parser = argparse.ArgumentParser(
        prog="feedback_store review",
        description="Inspect and review human category corrections before training merge."
    )
    parser.add_argument("--file", default=DEFAULT_FEEDBACK_FILE, help="Path to confirmed_feedback.json")
    subparsers = parser.add_subparsers(dest="command")

    # list
    subparsers.add_parser("list", help="List unreviewed feedback records")

    # approve
    p_app = subparsers.add_parser("approve", help="Approve specific record indices or all")
    p_app.add_argument("indices", nargs="*", type=int, help="Indices of records to approve")
    p_app.add_argument("--all", action="store_true", help="Approve all unreviewed records")

    # reject
    p_rej = subparsers.add_parser("reject", help="Reject specific record indices")
    p_rej.add_argument("indices", nargs="+", type=int, help="Indices of records to reject")

    args = parser.parse_args(sys.argv[2:] if len(sys.argv) > 1 and sys.argv[1] == "review" else sys.argv[1:])

    cmd = args.command or "list"

    if cmd == "list":
        unreviewed = list_unreviewed_feedback(args.file)
        if not unreviewed:
            print(f"No unreviewed feedback entries found in {args.file}")
            return
        print(f"\nUnreviewed Category Corrections in {args.file} ({len(unreviewed)} total):")
        print("=" * 85)
        print(f"{'Idx':<5} | {'Confirmed Cat':<18} | {'Predicted Cat':<18} | {'File:Line':<22} | Message")
        print("-" * 85)
        for idx, r in unreviewed:
            loc = f"{os.path.basename(r.get('file') or '')}:{r.get('line') or '?'}"
            msg = (r.get("message") or "")[:35]
            print(f"{idx:<5} | {r.get('confirmed_category', ''):<18} | {str(r.get('predicted_category') or ''):<18} | {loc:<22} | {msg}")
        print("=" * 85)
        print("To approve: python -m src.feedback_store review approve <idx> ... (or --all)\n")

    elif cmd == "approve":
        if getattr(args, "all", False):
            count = approve_all_feedback(args.file)
            print(f"Approved {count} feedback records for training merge.")
        elif args.indices:
            count = mark_feedback_reviewed(args.indices, approved=True, feedback_file=args.file)
            print(f"Approved {count} feedback records for training merge.")
        else:
            print("Specify record indices or pass --all.")

    elif cmd == "reject":
        count = mark_feedback_reviewed(args.indices, approved=False, feedback_file=args.file)
        print(f"Marked {count} feedback records as unapproved / rejected.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "review":
        _cli_review()
    elif len(sys.argv) > 1:
        _cli_review()
    else:
        # Default behavior when run directly
        _cli_review()
