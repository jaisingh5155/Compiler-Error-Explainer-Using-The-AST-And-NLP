"""
src/ast_parser.py
─────────────────
Structured Clang JSON AST extractor and source-range containment mapper.

Replaces regex/text scraping with clang++ -Xclang -ast-dump=json -fsyntax-only.
Extracts user-defined AST subtrees, resolves exact source ranges (line/col),
and maps diagnostics to their innermost enclosing AST node.
"""

from __future__ import annotations

import json
try:
    import ujson as json_lib
except ImportError:
    import json as json_lib
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ASTNode:
    kind: str
    name: Optional[str] = None
    type_name: Optional[str] = None
    begin_line: int = 0
    begin_col: int = 0
    end_line: int = 0
    end_col: int = 0
    file: Optional[str] = None
    children: list[ASTNode] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def contains(self, line: int, col: int) -> bool:
        """Check if (line, col) falls within this node's source range."""
        if not (self.begin_line and self.end_line):
            return False
        if line < self.begin_line or line > self.end_line:
            return False
        if self.begin_line == self.end_line:
            return self.begin_col <= col <= self.end_col
        if line == self.begin_line:
            return col >= self.begin_col
        if line == self.end_line:
            return col <= self.end_col
        return True

    def contains_line(self, line: int) -> bool:
        """Check if line falls within this node's line range."""
        if not (self.begin_line and self.end_line):
            return False
        return self.begin_line <= line <= self.end_line

    @property
    def summary(self) -> str:
        parts = [self.kind]
        if self.name:
            parts.append(self.name)
        if self.type_name:
            parts.append(f":{self.type_name}")
        return " ".join(parts)


def _is_external_path(path: Optional[str]) -> bool:
    if not path:
        return False
    return (
        path.startswith("/Applications")
        or path.startswith("/usr")
        or path.startswith("/Library")
        or path.startswith("<")
    )


def _is_user_top_node(node: dict[str, Any], file_path: str) -> bool:
    if node.get("isImplicit", False):
        return False

    abs_path = os.path.abspath(file_path)
    base = os.path.basename(file_path)

    loc = node.get("loc", {})
    r = node.get("range", {})
    b = r.get("begin", {})

    # Check for includedFrom anywhere in loc or begin
    for d in (
        loc,
        b,
        loc.get("spellingLoc", {}),
        loc.get("expansionLoc", {}),
        b.get("spellingLoc", {}),
        b.get("expansionLoc", {}),
    ):
        if "includedFrom" in d:
            return False

    # Extract all file annotations
    files = [
        loc.get("file"),
        loc.get("spellingLoc", {}).get("file"),
        loc.get("expansionLoc", {}).get("file"),
        b.get("file"),
        b.get("spellingLoc", {}).get("file"),
        b.get("expansionLoc", {}).get("file"),
    ]
    files = [f for f in files if f]

    if any(
        f in (file_path, abs_path, base)
        or f.endswith("/" + base)
        or f.endswith("\\" + base)
        for f in files
    ):
        return True

    if any(_is_external_path(f) for f in files):
        return False

    # If no file is specified and not external, it belongs to the primary TU file
    if not files:
        return True

    return False


def _build_ast_node(
    raw: dict[str, Any],
    parent_file: Optional[str] = None,
    parent_line: Optional[int] = None,
) -> ASTNode:
    kind = raw.get("kind", "Unknown")
    name = raw.get("name") or raw.get("referencedDecl", {}).get("name")
    type_info = raw.get("type", {})
    type_name = type_info.get("qualType")

    loc = raw.get("loc", {})
    r = raw.get("range", {})
    b = r.get("begin", {})
    e = r.get("end", {})

    node_file = (
        b.get("file")
        or loc.get("file")
        or b.get("spellingLoc", {}).get("file")
        or loc.get("spellingLoc", {}).get("file")
        or parent_file
    )

    b_line = (
        b.get("line")
        or loc.get("line")
        or b.get("spellingLoc", {}).get("line")
        or loc.get("spellingLoc", {}).get("line")
        or parent_line
        or 1
    )

    e_line = (
        e.get("line")
        or e.get("spellingLoc", {}).get("line")
        or b_line
    )

    b_col = b.get("col") or loc.get("col") or b.get("spellingLoc", {}).get("col") or 1
    e_col = (
        e.get("col")
        or e.get("spellingLoc", {}).get("col")
        or b_col
    ) + e.get("tokLen", 1) - 1

    children: list[ASTNode] = []
    for c in raw.get("inner", []):
        if not c.get("isImplicit", False):
            c_node = _build_ast_node(c, parent_file=node_file, parent_line=b_line)
            children.append(c_node)

    return ASTNode(
        kind=kind,
        name=name,
        type_name=type_name,
        begin_line=b_line,
        begin_col=b_col,
        end_line=e_line,
        end_col=max(e_col, b_col),
        file=node_file,
        children=children,
        raw=raw,
    )


def parse_clang_ast(file_path: str, timeout: float = 10.0) -> Optional[list[ASTNode]]:
    """
    Run `clang++ -Xclang -ast-dump=json -fsyntax-only` on file_path and parse
    the user's AST nodes with precise source ranges.
    """
    if not os.path.exists(file_path):
        return None

    cmd = [
        "clang++",
        "-Xclang",
        "-ast-dump=json",
        "-fsyntax-only",
        file_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None

    if not proc.stdout or not proc.stdout.strip():
        return None

    try:
        data = json_lib.loads(proc.stdout)
    except Exception:
        return None

    top_inner = data.get("inner", [])
    user_nodes: list[ASTNode] = []

    for raw_node in top_inner:
        if _is_user_top_node(raw_node, file_path):
            user_nodes.append(_build_ast_node(raw_node, parent_file=file_path))

    return user_nodes if user_nodes else None


def find_enclosing_ast_node(
    nodes: Optional[list[ASTNode]],
    line: int,
    col: int,
) -> tuple[Optional[ASTNode], bool]:
    """
    Find the innermost enclosing AST node for (line, col).

    Returns
    -------
    (matched_node, is_fallback)
    is_fallback is False if matched via strict source-range containment,
    or True if matched via relaxed line containment or fallback.
    """
    if not nodes:
        return None, True

    def _search_containment(node: ASTNode) -> Optional[ASTNode]:
        if not node.contains(line, col):
            return None
        # Check children first for more specific match
        for child in node.children:
            matched = _search_containment(child)
            if matched:
                return matched
        return node

    # 1. Exact range containment
    for root in nodes:
        matched = _search_containment(root)
        if matched:
            return matched, False

    # 2. Relaxed line containment within AST
    def _search_line(node: ASTNode) -> Optional[ASTNode]:
        if not node.contains_line(line):
            return None
        for child in node.children:
            matched = _search_line(child)
            if matched:
                return matched
        return node

    for root in nodes:
        matched = _search_line(root)
        if matched:
            return matched, True

    return None, True
