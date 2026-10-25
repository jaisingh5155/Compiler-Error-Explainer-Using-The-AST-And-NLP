"""
src/symbol_table.py
───────────────────
Hierarchical scoped symbol table built from Clang AST.

Tracks declarations, types, lines, scopes (global, function, block),
and initialization status. Supports visibility queries and Levenshtein
distance "did you mean?" suggestion enrichment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    try:
        from ast_parser import ASTNode
    except ImportError:
        from src.ast_parser import ASTNode


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Standard dynamic programming Levenshtein distance."""
    if s1 == s2:
        return 0
    if len(s1) == 0:
        return len(s2)
    if len(s2) == 0:
        return len(s1)

    v0 = list(range(len(s2) + 1))
    v1 = [0] * (len(s2) + 1)

    for i in range(len(s1)):
        v1[0] = i + 1
        for j in range(len(s2)):
            cost = 0 if s1[i] == s2[j] else 1
            v1[j + 1] = min(v1[j] + 1, v0[j + 1] + 1, v0[j] + cost)
        v0[:] = v1[:]

    return v0[len(s2)]


@dataclass
class Symbol:
    name: str
    type_name: str = "unknown"
    line: int = 0
    col: int = 0
    kind: str = "variable"  # 'variable', 'parameter', 'function', 'class'
    has_initializer: bool = False
    scope_name: str = "block"


@dataclass
class Scope:
    scope_type: str  # 'global', 'function', 'block'
    name: Optional[str] = None
    parent: Optional[Scope] = None
    begin_line: int = 0
    begin_col: int = 0
    end_line: int = 0
    end_col: int = 0
    symbols: dict[str, Symbol] = field(default_factory=dict)
    children: list[Scope] = field(default_factory=list)

    def contains(self, line: int, col: int) -> bool:
        """Check if (line, col) is within this scope's source range."""
        if self.scope_type == "global":
            return True
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

    def lookup(self, name: str) -> Optional[Symbol]:
        """Look up identifier in this scope and enclosing scopes."""
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def get_visible_symbols(self) -> dict[str, Symbol]:
        """Collect all symbols visible in this scope (parent shadowed by child)."""
        visible: dict[str, Symbol] = {}
        if self.parent:
            visible.update(self.parent.get_visible_symbols())
        visible.update(self.symbols)
        return visible


class SymbolTable:
    def __init__(self, global_scope: Optional[Scope] = None) -> None:
        self.global_scope = global_scope or Scope(scope_type="global", name="<global>")
        self.all_scopes: list[Scope] = [self.global_scope]

    def find_scope_at(self, line: int, col: int) -> Scope:
        """Find the innermost scope enclosing (line, col)."""
        def _search(scope: Scope) -> Optional[Scope]:
            if not scope.contains(line, col):
                return None
            for child in scope.children:
                inner = _search(child)
                if inner:
                    return inner
            return scope

        found = _search(self.global_scope)
        return found or self.global_scope

    def lookup(self, name: str, line: int, col: int) -> Optional[Symbol]:
        """Look up identifier name visible at (line, col)."""
        scope = self.find_scope_at(line, col)
        return scope.lookup(name)

    def is_declared(self, name: str, line: int, col: int) -> bool:
        """Return True if name is declared in visible scope at (line, col)."""
        return self.lookup(name, line, col) is not None

    def get_type(self, name: str, line: int, col: int) -> Optional[str]:
        """Return the declared type of name at (line, col), if found."""
        sym = self.lookup(name, line, col)
        return sym.type_name if sym else None

    def is_initialized(self, name: str, line: int, col: int) -> Optional[bool]:
        """Return True if symbol was declared with an initializer."""
        sym = self.lookup(name, line, col)
        return sym.has_initializer if sym else None

    def find_closest_match(
        self,
        name: str,
        line: int,
        col: int,
        max_distance: int = 2,
    ) -> Optional[str]:
        """
        Find the closest in-scope identifier within edit distance max_distance.
        Ignores exact matches and very short noise (len <= 1).
        """
        if not name or len(name) <= 1:
            return None

        scope = self.find_scope_at(line, col)
        visible = scope.get_visible_symbols()

        best_match: Optional[str] = None
        best_dist = max_distance + 1

        for candidate_name, sym in visible.items():
            if candidate_name == name:
                continue
            # Avoid matching standard built-in single letter boilerplate unless candidate is close
            dist = _levenshtein_distance(name, candidate_name)
            if dist <= max_distance and dist < best_dist:
                best_dist = dist
                best_match = candidate_name

        return best_match


def build_symbol_table(nodes: Optional[list[ASTNode]]) -> SymbolTable:
    """
    Construct a SymbolTable by traversing the parsed AST node tree.
    """
    sym_tab = SymbolTable()
    if not nodes:
        return sym_tab

    def _traverse(node: ASTNode, current_scope: Scope) -> None:
        raw = node.raw
        kind = node.kind

        # Function declarations introduce function scopes
        if kind in ("FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl"):
            fn_name = node.name or "<anonymous>"
            fn_type = node.type_name or "void ()"
            fn_scope = Scope(
                scope_type="function",
                name=fn_name,
                parent=current_scope,
                begin_line=node.begin_line,
                begin_col=node.begin_col,
                end_line=node.end_line,
                end_col=node.end_col,
            )
            current_scope.children.append(fn_scope)
            sym_tab.all_scopes.append(fn_scope)

            # Register function symbol in parent scope
            if node.name:
                current_scope.symbols[node.name] = Symbol(
                    name=node.name,
                    type_name=fn_type,
                    line=node.begin_line,
                    col=node.begin_col,
                    kind="function",
                    has_initializer=True,
                    scope_name=current_scope.name or current_scope.scope_type,
                )

            # Process parameters into function scope
            for child in node.children:
                if child.kind == "ParmVarDecl" and child.name:
                    fn_scope.symbols[child.name] = Symbol(
                        name=child.name,
                        type_name=child.type_name or "unknown",
                        line=child.begin_line,
                        col=child.begin_col,
                        kind="parameter",
                        has_initializer=True,  # parameters receive caller args
                        scope_name=fn_name,
                    )
                else:
                    _traverse(child, fn_scope)
            return

        # Compound statement (block) introduces block scope
        if kind == "CompoundStmt":
            block_scope = Scope(
                scope_type="block",
                name="block",
                parent=current_scope,
                begin_line=node.begin_line,
                begin_col=node.begin_col,
                end_line=node.end_line,
                end_col=node.end_col,
            )
            current_scope.children.append(block_scope)
            sym_tab.all_scopes.append(block_scope)

            for child in node.children:
                _traverse(child, block_scope)
            return

        # Variable declaration
        if kind == "VarDecl" and node.name:
            has_init = bool(raw.get("init")) or any(
                c.get("kind") not in ("ParmVarDecl",) for c in raw.get("inner", [])
            )
            current_scope.symbols[node.name] = Symbol(
                name=node.name,
                type_name=node.type_name or "unknown",
                line=node.begin_line,
                col=node.begin_col,
                kind="variable",
                has_initializer=has_init,
                scope_name=current_scope.name or current_scope.scope_type,
            )

        # For / While / If statement can also contain variable declarations
        for child in node.children:
            _traverse(child, current_scope)

    for root in nodes:
        _traverse(root, sym_tab.global_scope)

    return sym_tab
