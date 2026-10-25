"""
root_cause_grouper.py
─────────────────────
Groups cascading compiler diagnostics by root cause.

Heuristic:  consecutive diagnostics that share the same file and are within
a configurable line window (default 5) are assumed to cascade from the first
diagnostic in the group.  The first diagnostic gets `root_cause_id` equal to
its own identity; subsequent diagnostics in the group are tagged with the
same `root_cause_id`.

This is a purely deterministic grouper — no ML, no AST traversal.  It reduces
noisy cascading errors (e.g.  a single missing semicolon that generates 3-4
follow-on "expected …" messages) into a single actionable group.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Any, Sequence, Union

from diagnostic import Diagnostic


def _make_group_id(diag: Diagnostic) -> str:
    """Deterministic group key from file + line of the root diagnostic."""
    return f"rc-{diag.file or 'unknown'}:{diag.line or 0}"


def group_by_root_cause(
    diagnostics: Sequence[Diagnostic],
    *,
    line_window: int = 5,
) -> list[Diagnostic]:
    """
    Assign ``root_cause_id`` to each diagnostic.

    Parameters
    ----------
    diagnostics : sequence of Diagnostic
        Ordered list (by file, then line) of parsed diagnostics.
    line_window : int
        Maximum distance in lines between two diagnostics to consider
        them part of the same cascade.

    Returns
    -------
    list[Diagnostic]
        Same diagnostics, with ``root_cause_id`` populated.
    """
    if not diagnostics:
        return []

    result: list[Diagnostic] = list(diagnostics)

    # Sort by (file, line) for stable grouping
    result.sort(key=lambda d: (d.file or "", d.line or 0))

    current_group_id: str | None = None
    current_file: str | None = None
    current_line: int = 0

    for diag in result:
        same_file = diag.file == current_file
        within_window = (
            diag.line is not None
            and abs((diag.line or 0) - current_line) <= line_window
        )

        if same_file and within_window and current_group_id is not None:
            diag.root_cause_id = current_group_id
        else:
            # Start a new group
            current_group_id = _make_group_id(diag)
            diag.root_cause_id = current_group_id
            current_file = diag.file
            current_line = diag.line or 0

        # Track the last line in this group for window calculation
        if diag.line is not None:
            current_line = diag.line

    return result


def _severity_rank(diag: Diagnostic) -> int:
    """Return numeric rank (lower = higher severity)."""
    if diag.kind in ("error", "linker_error"):
        return 0
    for sf in getattr(diag, "security_findings", []):
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


def pick_group_representative(members: list[Diagnostic]) -> Diagnostic:
    """
    Select the representative diagnostic for a root-cause cascade group.
    
    1. If the group has only 1 diagnostic, return it.
    2. If the first diagnostic in source order is an error with a specific (non-'other')
       category, it is the true root cause that initiated the cascade.
    3. Otherwise (e.g. first diagnostic was a generic warning or unparsed 'other'),
       select the best candidate by:
       - Severity (error > warning)
       - Specificity (non-'other' > 'other')
       - Higher confidence
       - Source order
    """
    if not members:
        raise ValueError("Cannot select representative from empty group")
    if len(members) == 1:
        return members[0]

    # Ensure members are evaluated in source order
    source_ordered = sorted(members, key=lambda d: (d.line or 0, d.column or 0))
    first = source_ordered[0]
    if _severity_rank(first) == 0 and first.category and first.category != "other":
        return first

    def rep_key(d: Diagnostic) -> tuple:
        return (
            _severity_rank(d),
            1 if d.category == "other" else 0,
            -float(d.confidence or 0.0),
            d.line or 0,
            d.column or 0,
        )

    return sorted(source_ordered, key=rep_key)[0]



def select_group_representatives(
    diagnostics: Sequence[Diagnostic],
) -> list[Diagnostic]:
    """
    Group diagnostics by root_cause_id, select each group's representative
    diagnostic using (severity_rank, specificity, -confidence), and place the
    representative at the front of each group.
    
    Group ordering strictly follows the order of root causes in the source file,
    ensuring downstream diagnostics in one group never outrank a root cause in
    another group.
    """
    if not diagnostics:
        return []

    groups: dict[str, list[Diagnostic]] = {}
    for d in diagnostics:
        gid = d.root_cause_id or _make_group_id(d)
        groups.setdefault(gid, []).append(d)

    # Sort groups strictly by their earliest line number in the source file
    sorted_groups = sorted(
        groups.items(),
        key=lambda item: min(d.line or 0 for d in item[1]),
    )

    result: list[Diagnostic] = []
    for gid, members in sorted_groups:
        rep = pick_group_representative(members)
        result.append(rep)
        for m in members:
            if m is not rep:
                result.append(m)

    return result


def group_summary(diagnostics: Sequence[Diagnostic]) -> dict[str, list[Diagnostic]]:
    """Return diagnostics keyed by root_cause_id for reporting."""
    groups: dict[str, list[Diagnostic]] = {}
    for d in diagnostics:
        key = d.root_cause_id or "ungrouped"
        groups.setdefault(key, []).append(d)
    return groups


@dataclass
class Group:
    """Represents a root-cause cascade group for UI and reporting."""
    root: Any  # Diagnostic or dict
    children: list[Any] = field(default_factory=list)
    count: int = 0
    group_id: str = ""

    def __post_init__(self):
        if not self.count:
            self.count = 1 + len(self.children)


def _dict_severity_rank(d: dict) -> int:
    etype = (d.get("error_type") or d.get("type") or d.get("kind") or "").lower()
    if etype in ("error", "linker_error"):
        return 0
    if etype == "warning":
        return 2
    return 3


def pick_dict_group_representative(members: list[dict]) -> dict:
    """Select representative diagnostic dict for a cascade group."""
    if not members:
        return {}
    if len(members) == 1:
        return members[0]

    source_ordered = sorted(
        members,
        key=lambda d: (
            int(d.get("line") or 0),
            int(d.get("column") or 0) if str(d.get("column", "")).isdigit() else 0,
        ),
    )
    first = source_ordered[0]
    cat = first.get("category")
    if _dict_severity_rank(first) == 0 and cat and cat != "other":
        return first

    def rep_key(d: dict) -> tuple:
        return (
            _dict_severity_rank(d),
            1 if d.get("category") == "other" else 0,
            -float(d.get("confidence") or 0.0),
            int(d.get("line") or 0),
            int(d.get("column") or 0) if str(d.get("column", "")).isdigit() else 0,
        )

    return sorted(source_ordered, key=rep_key)[0]


def group_view_model(diagnostics: Sequence[Any]) -> list[Group]:
    """
    Produce a list of Group objects (root diagnostic + cascading children, counts).
    
    Accepts a sequence of either Diagnostic objects or dictionary representations.
    Groups are ordered by the earliest line occurrence in the source file.
    Within each group, the representative diagnostic is selected as `root`,
    and all follow-on/cascading diagnostics are stored in `children`.
    """
    if not diagnostics:
        return []

    first = diagnostics[0]
    is_dict = isinstance(first, dict)

    if is_dict:
        # Group dicts by root_cause_id (or fallback key)
        groups: dict[str, list[dict]] = {}
        for d in diagnostics:
            gid = d.get("root_cause_id") or f"rc-{d.get('file') or 'unknown'}:{d.get('line') or 0}"
            groups.setdefault(gid, []).append(d)

        sorted_groups = sorted(
            groups.items(),
            key=lambda item: min(int(d.get("line") or 0) for d in item[1]),
        )

        result: list[Group] = []
        for gid, members in sorted_groups:
            rep = pick_dict_group_representative(members)
            children = [m for m in members if m is not rep]
            result.append(Group(root=rep, children=children, count=len(members), group_id=gid))
        return result

    # Sequence of Diagnostic objects
    needs_grouping = any(getattr(d, "root_cause_id", None) is None for d in diagnostics)
    diags = group_by_root_cause(diagnostics) if needs_grouping else list(diagnostics)

    groups_diag: dict[str, list[Diagnostic]] = {}
    for d in diags:
        gid = d.root_cause_id or _make_group_id(d)
        groups_diag.setdefault(gid, []).append(d)

    sorted_diag_groups = sorted(
        groups_diag.items(),
        key=lambda item: min(d.line or 0 for d in item[1]),
    )

    result_diag: list[Group] = []
    for gid, members in sorted_diag_groups:
        rep = pick_group_representative(members)
        children = [m for m in members if m is not rep]
        result_diag.append(Group(root=rep, children=children, count=len(members), group_id=gid))
    return result_diag

