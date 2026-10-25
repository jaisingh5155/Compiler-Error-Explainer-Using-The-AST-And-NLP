from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal, Optional
import re

from models import CompilerError


Severity = Literal["Critical", "High", "Medium", "Low"]


VULNERABILITY_CWE_MAP: dict[str, str] = {
    # High-impact Memory / Injection vulnerabilities (Benchmark ground truth)
    "Buffer Overflow": "CWE-120",
    "Unsafe String Function": "CWE-120",
    "Unbounded Input": "CWE-120",
    "Unsafe Memory Copy": "CWE-119",
    "Command Injection": "CWE-78",
    "Format String Vulnerability": "CWE-134",
    "Integer Overflow": "CWE-190",
    "Logic Error / Integer Overflow Risk": "CWE-190",
    "Double Free": "CWE-415",
    "Use After Free": "CWE-416",
    "Null Pointer Dereference": "CWE-476",
    "Uninitialized Memory": "CWE-457",
    "Potential Memory Leak": "CWE-401",
    "Divide By Zero": "CWE-369",
    "Division By Zero": "CWE-369",

    # Secondary static security / hardening checks
    "Weak Randomness": "CWE-338",
    "Disabled Safety Check": "CWE-670",
    "Unresolved Security Debt": "CWE-546",
    "Unsafe Pointer Arithmetic": "CWE-469",
    "Unused Variable / Dead Code": "CWE-563",
    "Unchecked Return Value": "CWE-252",
    "Use of Deprecated API": "CWE-477",
    "Signed/Unsigned Mismatch": "CWE-195",
}


def get_cwe_for_vulnerability(vuln_type: str | None) -> str:
    """Return the canonical CWE ID for a vulnerability type string, or 'CWE-Other' if unknown."""
    if not vuln_type:
        return "CWE-Other"
    return VULNERABILITY_CWE_MAP.get(vuln_type.strip(), "CWE-Other")


@dataclass(frozen=True)
class SecurityFinding:
    file: str
    line: int | None
    column: int | None
    severity: Severity
    vulnerability_type: str
    description: str
    recommendation: str
    source: Literal["compiler_diagnostic", "static_scan"]
    cwe: str | None = None

    def to_dict(self):
        d = asdict(self)
        if not d.get("cwe"):
            d["cwe"] = get_cwe_for_vulnerability(self.vulnerability_type)
        return d


_SEVERITY_ORDER: dict[Severity, int] = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}

_SEVERITY_WEIGHT: dict[Severity, int] = {
    "Critical": 10,
    "High": 5,
    "Medium": 2,
    "Low": 1,
}

_DIAGNOSTIC_RULES = [
    (
        re.compile(r"unused variable|variable .+ set but not used", re.IGNORECASE),
        "Low",
        "Unused Variable / Dead Code",
        "An unused variable can indicate dead code, abandoned checks, or incomplete hardening logic.",
        "Remove the variable or wire it into the intended validation or control flow.",
    ),
    (
        re.compile(r"may be used uninitialized", re.IGNORECASE),
        "High",
        "Uninitialized Memory",
        "The compiler detected a value that may be read before initialization.",
        "Initialize the variable before use and avoid relying on undefined values.",
    ),
    (
        re.compile(r"format not a string literal|format string is not a string literal", re.IGNORECASE),
        "High",
        "Format String Vulnerability",
        "A non-literal format string can allow attacker-controlled format specifiers.",
        "Use a fixed format string and pass user data as separate arguments.",
    ),
    (
        re.compile(r"ignoring return value", re.IGNORECASE),
        "Medium",
        "Unchecked Return Value",
        "A function result is being discarded, which can hide failures.",
        "Check the return value and handle errors explicitly.",
    ),
    (
        re.compile(r"comparison is always (?:true|false)", re.IGNORECASE),
        "Medium",
        "Logic Error / Integer Overflow Risk",
        "The compiler believes the comparison cannot fail, which can indicate a logic bug or overflow condition.",
        "Review the expression, types, and range assumptions around the comparison.",
    ),
    (
        re.compile(r"integer overflow|overflow in expression|wraps around", re.IGNORECASE),
        "High",
        "Integer Overflow",
        "The compiler has reported an overflow-prone arithmetic expression.",
        "Check bounds before arithmetic and use checked multiplication/addition for allocation sizes.",
    ),
    (
        re.compile(r"division by zero|divide by zero|remainder by zero", re.IGNORECASE),
        "High",
        "Divide By Zero",
        "Integer division or modulo by zero leads to undefined behavior or runtime crash.",
        "Ensure the divisor cannot evaluate to zero before performing division or modulo.",
    ),
    (
        re.compile(r"deprecated", re.IGNORECASE),
        "Low",
        "Use of Deprecated API",
        "Deprecated APIs may be removed or behave unsafely in future toolchains.",
        "Replace the deprecated API with a supported alternative.",
    ),
    (
        re.compile(r"conversion from .* may change sign", re.IGNORECASE),
        "Medium",
        "Signed/Unsigned Mismatch",
        "Signed and unsigned types are being mixed in a way that may change values unexpectedly.",
        "Use a single signedness model or cast deliberately after checking bounds.",
    ),
    (
        re.compile(r"array subscript is above array bounds|array subscript is below array bounds", re.IGNORECASE),
        "Critical",
        "Buffer Overflow",
        "An array access is outside the valid bounds of the buffer.",
        "Check index bounds and guard all array accesses before dereferencing.",
    ),
    (
        re.compile(r"null pointer dereference", re.IGNORECASE),
        "High",
        "Null Pointer Dereference",
        "A pointer may be dereferenced without a null check.",
        "Check the pointer for null before dereferencing and fail safely.",
    ),
]

_RAW_STRING_START = re.compile(r'(?:u8|u|U|L)?R"([^\s()\\]{0,16})\(')
_SENSITIVE_WORDS = re.compile(r"\b(key|token|password|secret)\b", re.IGNORECASE)
_SENSITIVE_FUNCTIONS = re.compile(
    r"\b(gets|strcpy|strcat|sprintf|scanf|system|rand|memcpy|memmove|assert|malloc)\s*\(",
    re.IGNORECASE,
)
_DELETE_RE = re.compile(r"\bdelete\s*(?:\[\])?\s*([A-Za-z_]\w*)\s*;")
_RAW_POINTER_USE_RE = re.compile(r"(?:\*|->|\[)\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(?:->|\[)")


def _empty_finding(
    file: str,
    severity: Severity,
    vulnerability_type: str,
    description: str,
    recommendation: str,
    line: int | None = None,
    column: int | None = None,
    source: str = "static_scan",
    cwe: str | None = None,
) -> SecurityFinding:
    return SecurityFinding(
        file=file,
        line=line,
        column=column,
        severity=severity,
        vulnerability_type=vulnerability_type,
        description=description,
        recommendation=recommendation,
        source=source,  # type: ignore[arg-type]
        cwe=cwe or get_cwe_for_vulnerability(vulnerability_type),
    )


def _normalize_path(source_path: str) -> str:
    try:
        return str(Path(source_path).resolve())
    except Exception:
        return source_path


def _make_finding(
    source_path: str,
    line: int | None,
    column: int | None,
    severity: Severity,
    vulnerability_type: str,
    description: str,
    recommendation: str,
    source: Literal["compiler_diagnostic", "static_scan"],
    cwe: str | None = None,
) -> SecurityFinding:
    return SecurityFinding(
        file=_normalize_path(source_path),
        line=line,
        column=column,
        severity=severity,
        vulnerability_type=vulnerability_type,
        description=description,
        recommendation=recommendation,
        source=source,
        cwe=cwe or get_cwe_for_vulnerability(vulnerability_type),
    )


from lexer import strip_code as _dfa_strip_code
try:
    from ast_parser import parse_clang_ast, ASTNode
except ImportError:
    try:
        from src.ast_parser import parse_clang_ast, ASTNode
    except ImportError:
        parse_clang_ast = None
        ASTNode = None


def _strip_code(line: str, state: dict[str, object]) -> str:
    """Strip comments and string contents using formal DFA lexer."""
    return _dfa_strip_code(line, state)


def _split_args(argument_blob: str) -> list[str]:
    args: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote: str | None = None
    escape = False

    for ch in argument_blob:
        if in_quote:
            buf.append(ch)
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
            elif ch == in_quote:
                in_quote = None
            continue

        if ch in ("'", '"'):
            in_quote = ch
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
            continue

        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def _string_literal_value(text: str) -> Optional[str]:
    match = re.match(r'\s*[u8uUL]*"((?:\\.|[^"\\])*)"', text)
    if not match:
        return None
    return match.group(1)


def _diagnostic_findings(error: CompilerError) -> list[SecurityFinding]:
    message = (error.message or "").lower()
    findings: list[SecurityFinding] = []

    for pattern, severity, vuln_type, description, recommendation in _DIAGNOSTIC_RULES:
        if pattern.search(message):
            findings.append(
                _make_finding(
                    error.file or "",
                    error.line,
                    error.column,
                    severity,  # type: ignore[arg-type]
                    vuln_type,
                    description,
                    recommendation,
                    "compiler_diagnostic",
                )
            )

    return findings


def _looks_like_raw_integer_size(size_expr: str) -> bool:
    size_expr = size_expr.strip()
    if "sizeof" in size_expr:
        return False
    if re.search(r"\b\d+\b", size_expr):
        return True
    if any(op in size_expr for op in ("+", "-", "*", "/")):
        return True
    return False


# ── AST-Based Structured Security Detectors (Week 7) ──────────────────────────

def _get_decl_ref_name(node: Optional[ASTNode]) -> Optional[str]:
    if not node:
        return None
    if node.kind == "DeclRefExpr" and node.name:
        return node.name
    for c in node.children:
        res = _get_decl_ref_name(c)
        if res:
            return res
    return None


def _is_null_pointer_expr(expr_node: ASTNode) -> bool:
    """Check if expression evaluates to nullptr/NULL/0 or a pointer-returning call."""
    if expr_node.kind in ("CXXNullPtrLiteralExpr", "GNUNullExpr"):
        return True
    if expr_node.kind == "IntegerLiteral" and expr_node.raw.get("value") == 0:
        return True
    if expr_node.kind == "CallExpr":
        # Functions returning pointers without non-null guarantee (malloc, findValue, etc.)
        return True
    for c in expr_node.children:
        if _is_null_pointer_expr(c):
            return True
    return False


def _is_valid_address_expr(expr_node: ASTNode) -> bool:
    """Check if expression produces a valid address (e.g. &x, new T, string literal)."""
    if expr_node.kind == "CXXNewExpr":
        return True
    if expr_node.kind == "UnaryOperator" and expr_node.raw.get("opcode") == "&":
        return True
    if expr_node.kind == "StringLiteral":
        return True
    return any(_is_valid_address_expr(c) for c in expr_node.children)


def _terminates_control_flow(stmt_node: ASTNode) -> bool:
    """Return True if statement returns, throws, or exits."""
    if stmt_node.kind in ("ReturnStmt", "CXXThrowExpr"):
        return True
    if stmt_node.kind == "CallExpr":
        name = _get_decl_ref_name(stmt_node)
        if name in ("exit", "_exit", "abort", "__builtin_trap"):
            return True
    for c in stmt_node.children:
        if _terminates_control_flow(c):
            return True
    return False


def _extract_null_check_target(cond_node: ASTNode) -> tuple[Optional[str], bool]:
    """
    Analyze condition for null check on a pointer.
    Returns (pointer_name, is_positive_check)
    is_positive_check: True if condition is True when pointer is NON-NULL (e.g. p != nullptr, p)
                       False if condition is True when pointer is NULL (e.g. p == nullptr, !p)
    """
    if cond_node.kind == "BinaryOperator":
        op = cond_node.raw.get("opcode")
        if op in ("!=", "==") and len(cond_node.children) >= 2:
            c0, c1 = cond_node.children[0], cond_node.children[1]
            p_name = _get_decl_ref_name(c0)
            if p_name and _is_null_pointer_expr(c1):
                return (p_name, op == "!=")
            p_name = _get_decl_ref_name(c1)
            if p_name and _is_null_pointer_expr(c0):
                return (p_name, op == "!=")
    if cond_node.kind == "UnaryOperator" and cond_node.raw.get("opcode") == "!":
        if cond_node.children:
            p_name = _get_decl_ref_name(cond_node.children[0])
            if p_name:
                return (p_name, False)
    p_name = _get_decl_ref_name(cond_node)
    if p_name:
        return (p_name, True)
    return (None, False)


def _extract_assert_guard_target(stmt_node: ASTNode, ptr_state: dict[str, str]) -> Optional[str]:
    """Check if statement is an assertion that validates a pointer non-null."""
    has_assert_call = False
    literals: list[str] = []

    def _traverse(node: ASTNode):
        nonlocal has_assert_call
        if node.kind == "CallExpr":
            callee = _get_decl_ref_name(node)
            if callee in ("__assert_rtn", "__assert_fail", "_assert", "_wassert", "abort", "__builtin_trap"):
                has_assert_call = True
        if node.kind == "StringLiteral" and node.raw.get("value"):
            literals.append(str(node.raw.get("value")))
        for c in node.children:
            _traverse(c)

    _traverse(stmt_node)
    if has_assert_call:
        for lit in literals:
            val = lit.strip('"').strip()
            m = re.match(r"^([a-zA-Z_]\w*)\s*!=\s*(?:nullptr|NULL|0)$", val)
            if m and m.group(1) in ptr_state:
                return m.group(1)
            m = re.match(r"^(?:nullptr|NULL|0)\s*!=\s*([a-zA-Z_]\w*)$", val)
            if m and m.group(1) in ptr_state:
                return m.group(1)
            if val in ptr_state:
                return val
    return None


def _scan_null_pointer_dereference(ast_nodes: list[ASTNode], source_path: str) -> list[SecurityFinding]:
    """CWE-476: Linear AST scan detecting pointer dereferences without prior null check."""
    findings: list[SecurityFinding] = []

    source_lines: list[str] = []
    try:
        with open(source_path) as f:
            source_lines = f.readlines()
    except Exception:
        pass

    for func in ast_nodes:
        if func.kind not in ("FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl"):
            continue
        body = next((c for c in func.children if c.kind == "CompoundStmt"), None)
        if not body:
            continue

        ptr_state: dict[str, str] = {}  # ptr_name -> "NULL_OR_UNCHECKED" | "VALID"
        ptr_origin_line: dict[str, int] = {}
        reported_ptrs: set[str] = set()

        def _find_dereferences(node: ASTNode, current_ptrs: dict[str, str], guarded_ptrs: set[str]):
            # 1. UnaryOperator *
            if node.kind == "UnaryOperator" and node.raw.get("opcode") == "*":
                if node.children:
                    p_name = _get_decl_ref_name(node.children[0])
                    if p_name and p_name in current_ptrs and current_ptrs[p_name] == "NULL_OR_UNCHECKED":
                        if p_name not in guarded_ptrs and p_name not in reported_ptrs:
                            findings.append(_make_finding(
                                source_path,
                                node.begin_line,
                                node.begin_col,
                                "High",
                                "Null Pointer Dereference",
                                f"Pointer '{p_name}' is dereferenced (*{p_name}) without prior null check after being set to null/uninitialized (line {ptr_origin_line.get(p_name, node.begin_line)}).",
                                f"Verify that '{p_name}' is not null (e.g. 'if ({p_name} != nullptr)') before dereferencing.",
                                "static_scan"
                            ))
                            reported_ptrs.add(p_name)
                            return
            # 2. MemberExpr with isArrow == True (ptr->member)
            if node.kind == "MemberExpr" and node.raw.get("isArrow") is True:
                if node.children:
                    p_name = _get_decl_ref_name(node.children[0])
                    if p_name and p_name in current_ptrs and current_ptrs[p_name] == "NULL_OR_UNCHECKED":
                        if p_name not in guarded_ptrs and p_name not in reported_ptrs:
                            findings.append(_make_finding(
                                source_path,
                                node.begin_line,
                                node.begin_col,
                                "High",
                                "Null Pointer Dereference",
                                f"Pointer '{p_name}' is dereferenced via member access ('{p_name}->{node.name}') without prior null check (line {ptr_origin_line.get(p_name, node.begin_line)}).",
                                f"Verify that '{p_name}' is not null before accessing its members.",
                                "static_scan"
                            ))
                            reported_ptrs.add(p_name)
                            return
            # 3. ArraySubscriptExpr (ptr[i])
            if node.kind == "ArraySubscriptExpr":
                if node.children:
                    p_name = _get_decl_ref_name(node.children[0])
                    if p_name and p_name in current_ptrs and current_ptrs[p_name] == "NULL_OR_UNCHECKED":
                        if p_name not in guarded_ptrs and p_name not in reported_ptrs:
                            findings.append(_make_finding(
                                source_path,
                                node.begin_line,
                                node.begin_col,
                                "High",
                                "Null Pointer Dereference",
                                f"Pointer '{p_name}' is indexed as an array ('{p_name}[...]') without prior null check (line {ptr_origin_line.get(p_name, node.begin_line)}).",
                                f"Verify that '{p_name}' is not null before indexing.",
                                "static_scan"
                            ))
                            reported_ptrs.add(p_name)
                            return

            for c in node.children:
                _find_dereferences(c, current_ptrs, guarded_ptrs)

        for stmt in body.children:
            # Loops are out-of-scope for linear AST pointer tracking
            if stmt.kind in ("ForStmt", "WhileStmt", "DoStmt", "CXXForRangeStmt"):
                continue

            # Pointer declaration
            if stmt.kind == "DeclStmt":
                for var_node in stmt.children:
                    if var_node.kind == "VarDecl" and var_node.name:
                        tname = var_node.type_name or ""
                        if "*" in tname:
                            if not var_node.children:
                                ptr_state[var_node.name] = "NULL_OR_UNCHECKED"
                                ptr_origin_line[var_node.name] = var_node.begin_line
                            elif any(_is_null_pointer_expr(c) for c in var_node.children):
                                ptr_state[var_node.name] = "NULL_OR_UNCHECKED"
                                ptr_origin_line[var_node.name] = var_node.begin_line
                            elif any(_is_valid_address_expr(c) for c in var_node.children):
                                ptr_state[var_node.name] = "VALID"
                continue

            # Pointer assignment (p = ...)
            if stmt.kind == "BinaryOperator" and stmt.raw.get("opcode") == "=":
                if len(stmt.children) >= 2:
                    p_name = _get_decl_ref_name(stmt.children[0])
                    if p_name and p_name in ptr_state:
                        if _is_valid_address_expr(stmt.children[1]):
                            ptr_state[p_name] = "VALID"
                        elif _is_null_pointer_expr(stmt.children[1]):
                            ptr_state[p_name] = "NULL_OR_UNCHECKED"
                            ptr_origin_line[p_name] = stmt.begin_line

            # Assert statement checking null
            assert_p = _extract_assert_guard_target(stmt, ptr_state)
            if not assert_p and source_lines:
                exp_loc = stmt.raw.get("range", {}).get("begin", {}).get("expansionLoc", {})
                line_no = exp_loc.get("line") or getattr(stmt, "begin_line", None)
                if line_no and 1 <= line_no <= len(source_lines):
                    sline = source_lines[line_no - 1]
                    m = re.search(r'\bassert\s*\(\s*(?:([a-zA-Z_]\w*)\s*!=\s*(?:nullptr|NULL|0)|(?:nullptr|NULL|0)\s*!=\s*([a-zA-Z_]\w*)|([a-zA-Z_]\w*))\s*\)', sline)
                    if m:
                        matched = m.group(1) or m.group(2) or m.group(3)
                        if matched in ptr_state:
                            assert_p = matched
            if assert_p and assert_p in ptr_state:
                ptr_state[assert_p] = "VALID"
                continue

            # If statement checking null
            if stmt.kind == "IfStmt":
                cond = stmt.children[0] if len(stmt.children) >= 1 else None
                then_branch = stmt.children[1] if len(stmt.children) >= 2 else None
                else_branch = stmt.children[2] if len(stmt.children) >= 3 else None

                if cond:
                    p_name, is_positive = _extract_null_check_target(cond)
                    if p_name and p_name in ptr_state:
                        if is_positive:
                            if then_branch:
                                _find_dereferences(then_branch, ptr_state, guarded_ptrs={p_name})
                            if else_branch:
                                _find_dereferences(else_branch, ptr_state, guarded_ptrs=set())
                            continue
                        else:
                            if then_branch:
                                if _terminates_control_flow(then_branch):
                                    ptr_state[p_name] = "VALID"
                                _find_dereferences(then_branch, ptr_state, guarded_ptrs=set())
                            if else_branch:
                                _find_dereferences(else_branch, ptr_state, guarded_ptrs={p_name})
                            continue

            _find_dereferences(stmt, ptr_state, guarded_ptrs=set())

    return findings


def _is_primitive_type(tname: Optional[str]) -> bool:
    if not tname:
        return True
    if any(cls in tname for cls in ("string", "vector", "map", "set", "deque", "list", "unique_ptr", "shared_ptr", "ifstream", "ofstream", "stringstream")):
        return False
    return True


def _is_operator_rshift(node: ASTNode) -> bool:
    if node.kind != "CXXOperatorCallExpr":
        return False
    if node.children:
        first = node.children[0]
        if first.name == "operator>>":
            return True
        for gc in first.children:
            if gc.name == "operator>>":
                return True
    return False


def _collect_stream_extracted_vars(node: ASTNode) -> set[str]:
    extracted = set()
    if _is_operator_rshift(node) and len(node.children) >= 3:
        rhs = node.children[2]
        v = _get_decl_ref_name(rhs)
        if v:
            extracted.add(v)
        extracted.update(_collect_stream_extracted_vars(node.children[1]))
    return extracted


def _is_scanf_call(node: ASTNode) -> bool:
    if node.kind != "CallExpr" or not node.children:
        return False
    callee = _get_decl_ref_name(node.children[0])
    return callee in ("scanf", "fscanf", "sscanf", "std::scanf", "std::fscanf", "std::sscanf")


def _collect_scanf_vars(node: ASTNode) -> set[str]:
    extracted = set()
    if _is_scanf_call(node):
        for arg in node.children[1:]:
            if arg.kind == "UnaryOperator" and arg.raw.get("opcode") == "&":
                v = _get_decl_ref_name(arg)
                if v:
                    extracted.add(v)
            else:
                for c in arg.children:
                    if c.kind == "UnaryOperator" and c.raw.get("opcode") == "&":
                        v = _get_decl_ref_name(c)
                        if v:
                            extracted.add(v)
    return extracted


def _is_getline_call(node: ASTNode) -> bool:
    if node.kind != "CallExpr" or not node.children:
        return False
    callee = _get_decl_ref_name(node.children[0])
    return callee in ("getline", "std::getline")


def _collect_getline_vars(node: ASTNode) -> set[str]:
    extracted = set()
    if _is_getline_call(node) and len(node.children) >= 3:
        v = _get_decl_ref_name(node.children[2])
        if v:
            extracted.add(v)
    return extracted


def _scan_uninitialized_variable_use(ast_nodes: list[ASTNode], source_path: str) -> list[SecurityFinding]:
    """CWE-457: Linear AST scan tracking local variables read before being written."""
    findings: list[SecurityFinding] = []

    try:
        source_lines = Path(source_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        source_lines = []

    for func in ast_nodes:
        if func.kind not in ("FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl"):
            continue
        body = next((c for c in func.children if c.kind == "CompoundStmt"), None)
        if not body:
            continue

        var_state: dict[str, str] = {}  # var_name -> "UNINITIALIZED" | "INITIALIZED"
        var_decl_line: dict[str, int] = {}
        reported_vars: set[str] = set()

        def _collect_writes(node: ASTNode) -> set[str]:
            """Return set of variables written/assigned in this subtree."""
            written = set()
            if node.kind in ("BinaryOperator", "CompoundAssignOperator") and node.raw.get("opcode") in ("=", "+=", "-=", "*=", "/="):
                if node.children:
                    v = _get_decl_ref_name(node.children[0])
                    if v:
                        written.add(v)
            if node.kind == "UnaryOperator" and node.raw.get("opcode") in ("&", "++", "--"):
                if node.children:
                    v = _get_decl_ref_name(node.children[0])
                    if v:
                        written.add(v)
            if node.kind == "CXXOperatorCallExpr":
                if _is_operator_rshift(node):
                    written.update(_collect_stream_extracted_vars(node))
                else:
                    for c in node.children:
                        if c.kind == "DeclRefExpr" and c.name in var_state:
                            written.add(c.name)
            if node.kind == "CallExpr":
                written.update(_collect_scanf_vars(node))
                written.update(_collect_getline_vars(node))
            if node.kind == "RecoveryExpr":
                names = [c.name for c in node.children if c.kind == "DeclRefExpr"]
                if "cin" in names:
                    for n in names:
                        if n != "cin" and n in var_state:
                            written.add(n)
            for c in node.children:
                if not (_is_operator_rshift(node) or (node.kind == "CallExpr" and (_is_scanf_call(node) or _is_getline_call(node)))):
                    written.update(_collect_writes(c))
            return written

        def _check_reads(node: ASTNode, in_lhs_of_assign: bool = False, in_address_of: bool = False):
            if node.kind in ("BinaryOperator", "CompoundAssignOperator") and node.raw.get("opcode") in ("=", "+=", "-=", "*=", "/="):
                if len(node.children) >= 2:
                    _check_reads(node.children[0], in_lhs_of_assign=True, in_address_of=False)
                    _check_reads(node.children[1], in_lhs_of_assign=False, in_address_of=False)
                return

            if node.kind == "UnaryOperator" and node.raw.get("opcode") == "&":
                for c in node.children:
                    _check_reads(c, in_lhs_of_assign=False, in_address_of=True)
                return

            # operator>>: right operands are stream extraction targets (writes), not reads
            if _is_operator_rshift(node):
                if len(node.children) >= 2:
                    lhs = node.children[1]
                    _check_reads(lhs, in_lhs_of_assign=False, in_address_of=False)
                return

            # scanf/fscanf/sscanf: &x args are destination targets, not uninitialized reads
            if node.kind == "CallExpr" and _is_scanf_call(node):
                for arg in node.children[1:]:
                    if not (arg.kind == "UnaryOperator" and arg.raw.get("opcode") == "&"):
                        has_addr = any(c.kind == "UnaryOperator" and c.raw.get("opcode") == "&" for c in arg.children)
                        if not has_addr:
                            _check_reads(arg, in_lhs_of_assign=False, in_address_of=False)
                return

            # getline: second argument is string destination, not uninitialized read
            if node.kind == "CallExpr" and _is_getline_call(node):
                if len(node.children) >= 2:
                    _check_reads(node.children[1], in_lhs_of_assign=False, in_address_of=False)
                return

            if node.kind == "RecoveryExpr":
                names = [c.name for c in node.children if c.kind == "DeclRefExpr"]
                if "cin" in names:
                    return

            if node.kind == "DeclRefExpr" and node.name and not in_lhs_of_assign and not in_address_of:
                vname = node.name
                if vname in var_state and var_state[vname] == "UNINITIALIZED":
                    if vname not in reported_vars:
                        findings.append(_make_finding(
                            source_path,
                            node.begin_line,
                            node.begin_col,
                            "High",
                            "Uninitialized Memory",
                            f"Variable '{vname}' is read before being initialized (declared uninitialized at line {var_decl_line.get(vname, node.begin_line)}).",
                            f"Initialize '{vname}' at its point of declaration (e.g. 'int {vname} = 0;').",
                            "static_scan"
                        ))
                        reported_vars.add(vname)
                        return

            for c in node.children:
                _check_reads(c, in_lhs_of_assign, in_address_of)

        for stmt in body.children:
            if stmt.kind == "DeclStmt":
                for var_node in stmt.children:
                    if var_node.kind == "VarDecl" and var_node.name:
                        tname = var_node.type_name
                        if _is_primitive_type(tname):
                            has_init = bool(var_node.children) or bool(var_node.raw.get("init"))
                            if not has_init and source_lines and var_node.begin_line and 1 <= var_node.begin_line <= len(source_lines):
                                src_line = source_lines[var_node.begin_line - 1]
                                if re.search(rf"\b{re.escape(var_node.name)}\s*=", src_line):
                                    has_init = True
                            if not has_init:
                                var_state[var_node.name] = "UNINITIALIZED"
                                var_decl_line[var_node.name] = var_node.begin_line
                            else:
                                var_state[var_node.name] = "INITIALIZED"
                continue

            # Fallback source-line check for stream extraction, scanf, and getline
            if source_lines and stmt.begin_line and 1 <= stmt.begin_line <= len(source_lines):
                line_text = source_lines[stmt.begin_line - 1]
                for vname in list(var_state.keys()):
                    if var_state[vname] == "UNINITIALIZED":
                        if re.search(rf">>\s*{re.escape(vname)}\b(?!\s*>)(?!\s*=)", line_text):
                            var_state[vname] = "INITIALIZED"
                        elif re.search(rf"\b(?:std::)?f?s?scanf\s*\([^;]*&\s*{re.escape(vname)}\b", line_text):
                            var_state[vname] = "INITIALIZED"
                        elif re.search(rf"\b(?:std::)?getline\s*\([^,]+,\s*{re.escape(vname)}\s*\)", line_text):
                            var_state[vname] = "INITIALIZED"

            if stmt.kind == "IfStmt":
                cond = stmt.children[0] if len(stmt.children) >= 1 else None
                then_branch = stmt.children[1] if len(stmt.children) >= 2 else None
                else_branch = stmt.children[2] if len(stmt.children) >= 3 else None

                if cond:
                    _check_reads(cond)

                then_writes = set()
                if then_branch:
                    _check_reads(then_branch)
                    then_writes = _collect_writes(then_branch)

                else_writes = set()
                if else_branch:
                    _check_reads(else_branch)
                    else_writes = _collect_writes(else_branch)

                if else_branch is not None:
                    both_assigned = then_writes.intersection(else_writes)
                    for v in both_assigned:
                        var_state[v] = "INITIALIZED"
                continue

            _check_reads(stmt)

            writes = _collect_writes(stmt)
            for v in writes:
                var_state[v] = "INITIALIZED"

    return findings


def _scan_divide_by_zero(ast_nodes: list[ASTNode], source_path: str) -> list[SecurityFinding]:
    """
    CWE-369: AST scan detecting integer division/modulo by zero:
      1. Divisor is a literal zero (e.g. x / 0, x % 0).
      2. Divisor is a variable provably assigned/initialized to zero without subsequent reassignment before use.
    """
    findings: list[SecurityFinding] = []
    reported_locations: set[tuple[int, int]] = set()

    def _unwrap_expr(node: ASTNode) -> ASTNode:
        curr = node
        while curr.children and curr.kind in ("ImplicitCastExpr", "ParenExpr", "MaterializeTemporaryExpr"):
            curr = curr.children[0]
        return curr

    def _get_int_literal_val(node: ASTNode) -> Optional[int]:
        unwrapped = _unwrap_expr(node)
        if unwrapped.kind == "IntegerLiteral":
            try:
                raw_val = unwrapped.raw.get("value")
                if raw_val is not None:
                    return int(raw_val)
            except Exception:
                pass
        elif unwrapped.kind == "UnaryOperator" and unwrapped.raw.get("opcode") == "-" and unwrapped.children:
            child_val = _get_int_literal_val(unwrapped.children[0])
            if child_val is not None:
                return -child_val
        return None

    for func in ast_nodes:
        if func.kind not in ("FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl"):
            continue
        body = next((c for c in func.children if c.kind == "CompoundStmt"), None)
        if not body:
            continue

        var_values: dict[str, Optional[int]] = {}

        def _check_expression(node: ASTNode):
            if node.kind in ("BinaryOperator", "CompoundAssignOperator"):
                opcode = node.raw.get("opcode")
                # Check division or modulo operators
                if opcode in ("/", "%", "/=", "%=") and len(node.children) >= 2:
                    # Recursively check LHS and RHS expressions first
                    _check_expression(node.children[0])
                    _check_expression(node.children[1])

                    rhs = _unwrap_expr(node.children[1])
                    loc_line = rhs.begin_line or node.begin_line
                    loc_col = rhs.begin_col or node.begin_col
                    loc_key = (loc_line, loc_col)

                    # Case 1: Divisor is literal 0
                    rhs_val = _get_int_literal_val(rhs)
                    if rhs_val == 0:
                        if loc_key not in reported_locations:
                            reported_locations.add(loc_key)
                            findings.append(_make_finding(
                                source_path,
                                loc_line,
                                loc_col,
                                "High",
                                "Divide By Zero",
                                f"Division by zero: literal 0 used as divisor at line {loc_line}.",
                                "Ensure the divisor cannot evaluate to zero before division.",
                                "static_scan",
                            ))
                        return

                    # Case 2: Divisor is variable provably 0
                    if rhs.kind == "DeclRefExpr" and rhs.name:
                        vname = rhs.name
                        if var_values.get(vname) == 0:
                            if loc_key not in reported_locations:
                                reported_locations.add(loc_key)
                                findings.append(_make_finding(
                                    source_path,
                                    loc_line,
                                    loc_col,
                                    "High",
                                    "Divide By Zero",
                                    f"Division by zero: variable '{vname}' is 0 at line {loc_line}.",
                                    f"Ensure '{vname}' is non-zero before division, or inject a runtime zero check.",
                                    "static_scan",
                                ))
                            return
                    return

                if opcode == "=" and len(node.children) >= 2:
                    # Assignment: first check RHS expression for any divide by zero
                    _check_expression(node.children[1])
                    lhs = _unwrap_expr(node.children[0])
                    rhs = _unwrap_expr(node.children[1])
                    if lhs.kind == "DeclRefExpr" and lhs.name:
                        val = _get_int_literal_val(rhs)
                        var_values[lhs.name] = val
                    return

                if opcode in ("+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="):
                    if node.children:
                        _check_expression(node.children[0])
                        if len(node.children) >= 2:
                            _check_expression(node.children[1])
                        lhs = _unwrap_expr(node.children[0])
                        if lhs.kind == "DeclRefExpr" and lhs.name:
                            var_values[lhs.name] = None
                    return

            if node.kind == "UnaryOperator":
                opcode = node.raw.get("opcode")
                if opcode in ("++", "--") and node.children:
                    operand = _unwrap_expr(node.children[0])
                    if operand.kind == "DeclRefExpr" and operand.name:
                        var_values[operand.name] = None
                elif opcode == "&" and node.children:
                    # Taking address might mutate variable via pointer/reference
                    operand = _unwrap_expr(node.children[0])
                    if operand.kind == "DeclRefExpr" and operand.name:
                        var_values[operand.name] = None

            if node.kind == "CallExpr":
                for arg in node.children:
                    _check_expression(arg)
                return

            if node.kind == "CXXOperatorCallExpr":
                # operator>> stream extraction
                for arg in node.children:
                    v = _get_decl_ref_name(arg)
                    if v and v != "cin":
                        var_values[v] = None
                    _check_expression(arg)
                return

            for c in node.children:
                _check_expression(c)

        for stmt in body.children:
            if stmt.kind == "DeclStmt":
                for child in stmt.children:
                    if child.kind == "VarDecl" and child.name:
                        if child.children:
                            init_expr = _unwrap_expr(child.children[0])
                            _check_expression(init_expr)
                            val = _get_int_literal_val(init_expr)
                            var_values[child.name] = val
                        else:
                            var_values[child.name] = None
                continue

            _check_expression(stmt)

    return findings


def _scan_source_findings(source_path: str) -> list[SecurityFinding]:
    path = Path(source_path)
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []

    findings: list[SecurityFinding] = []

    # Week 7 & Week 10: Run structured AST scanners for CWE-476, CWE-457, and CWE-369
    if parse_clang_ast:
        try:
            ast_nodes = parse_clang_ast(source_path)
            if ast_nodes:
                findings.extend(_scan_null_pointer_dereference(ast_nodes, source_path))
                findings.extend(_scan_uninitialized_variable_use(ast_nodes, source_path))
                findings.extend(_scan_divide_by_zero(ast_nodes, source_path))
        except Exception:
            pass

    state: dict[str, object] = {"in_block_comment": False, "raw_delim": None}
    scope_stack: list[dict[str, object]] = [
        {"start_line": 1, "malloc_lines": [], "free_seen": False}
    ]
    recent_sensitive_lines: list[int] = []
    freed_vars: dict[str, int] = {}
    overflow_risk_vars: dict[str, int] = {}
    debug_guard_present = any(
        re.search(r"#\s*(?:if|ifdef|ifndef)\s+.*NDEBUG", line, re.IGNORECASE)
        for line in lines
    )

    def current_scope() -> dict[str, object]:
        return scope_stack[-1]

    def emit(line_no: int | None, vuln_type: str, severity: Severity, description: str, recommendation: str):
        findings.append(
            _make_finding(
                source_path,
                line_no,
                None,
                severity,
                vuln_type,
                description,
                recommendation,
                "static_scan",
            )
        )

    def emit_location(line_no: int | None, column: int | None, vuln_type: str, severity: Severity, description: str, recommendation: str):
        findings.append(
            _make_finding(
                source_path,
                line_no,
                column,
                severity,
                vuln_type,
                description,
                recommendation,
                "static_scan",
            )
        )

    for line_no, raw_line in enumerate(lines, start=1):
        code_line = _strip_code(raw_line, state).strip()
        raw_lower = raw_line.lower()
        code_lower = code_line.lower()

        sensitive_here = bool(_SENSITIVE_FUNCTIONS.search(code_line))
        if sensitive_here:
            recent_sensitive_lines.append(line_no)
            recent_sensitive_lines = recent_sensitive_lines[-3:]

        if re.search(r"\bgets\s*\(", code_line):
            emit(
                line_no,
                "Buffer Overflow",
                "Critical",
                "gets() reads input without any bounds checking.",
                "Replace gets() with fgets(), std::getline, or another bounded input routine.",
            )

        if re.search(r"\b(?:strcpy|strcat|sprintf)\s*\(", code_line):
            emit(
                line_no,
                "Unsafe String Function",
                "High",
                "A classic C string routine is being used without explicit bounds control.",
                "Use bounded alternatives such as strncpy/strncat/snprintf or switch to std::string.",
            )

        scanf_match = re.search(r"\bscanf\s*\((.+)\)\s*;?\s*$", code_line)
        if scanf_match:
            args = _split_args(scanf_match.group(1))
            if args:
                fmt = _string_literal_value(args[0])
                if fmt and re.search(r"%\s*s", fmt) and not re.search(r"%\d+s", fmt):
                    emit(
                        line_no,
                        "Unbounded Input",
                        "High",
                        "scanf() is reading a string with %s and no width limit.",
                        "Add an explicit width specifier or use std::string with bounded parsing.",
                    )

        mem_match = re.search(r"\b(memcpy|memmove)\s*\((.+)\)\s*;?\s*$", code_line)
        if mem_match:
            args = _split_args(mem_match.group(2))
            if len(args) >= 3 and _looks_like_raw_integer_size(args[2]):
                emit(
                    line_no,
                    "Unsafe Memory Copy",
                    "Medium",
                    f"{mem_match.group(1)}() is using a raw size expression instead of a verified sizeof-based bound.",
                    "Validate the copy length and prefer sizeof-driven limits or safer container-aware copying.",
                )

        if re.search(r"\bsystem\s*\(", code_line):
            emit(
                line_no,
                "Command Injection",
                "High",
                "system() executes a shell command and can be influenced by attacker-controlled input.",
                "Avoid shell execution. Use exec-style APIs or strict argument validation and escaping.",
            )

        if re.search(r"\brand\s*\(", code_line) and (
            _SENSITIVE_WORDS.search(raw_line) or _SENSITIVE_WORDS.search(code_line)
            or any(abs(line_no - prev) <= 1 for prev in recent_sensitive_lines)
        ):
            emit(
                line_no,
                "Weak Randomness",
                "High",
                "rand() is being used in a security-sensitive context.",
                "Use a cryptographically secure random source for keys, tokens, passwords, and secrets.",
            )

        if re.search(r"\bassert\s*\(", code_line) and not debug_guard_present:
            emit(
                line_no,
                "Disabled Safety Check",
                "Low",
                "assert() is being used as a safety boundary outside a clearly debug-only context.",
                "Keep runtime checks explicit and do not rely on assert() for production validation.",
            )

        if re.search(r"\b(TODO|FIXME)\b", raw_line, re.IGNORECASE) and (
            sensitive_here or any(abs(line_no - prev) <= 1 for prev in recent_sensitive_lines)
        ):
            emit(
                line_no,
                "Unresolved Security Debt",
                "Low",
                "A TODO/FIXME is sitting next to security-sensitive code.",
                "Resolve the security follow-up before shipping the code path.",
            )

        if re.search(r"\*\s*\(\s*[A-Za-z_]\w*\s*\+\s*[^)]+\)", code_line) or re.search(r"\b(?:[A-Za-z_]\w*(?:ptr|buf|data|cursor|p))\s*\+\+", code_line):
            emit(
                line_no,
                "Unsafe Pointer Arithmetic",
                "Medium",
                "Raw pointer arithmetic is present and may escape bounds checks.",
                "Prefer indexing with explicit bounds checks or use standard container iterators.",
            )

        # Bug 4.3 Fix: Track variables assigned INT_MAX/SIZE_MAX across lines
        intmax_assign = re.search(r"\b([A-Za-z_]\w*)\s*=\s*(?:INT_MAX|SIZE_MAX|UINT_MAX|LONG_MAX|LLONG_MAX)\b", code_line)
        if intmax_assign:
            overflow_risk_vars[intmax_assign.group(1)] = line_no

        # Original same-line check: arithmetic on INT_MAX/SIZE_MAX or size variables
        # Note: Bounded compile-time constant sizeof multiplications (e.g. sizeof(int)*10) are safe and NOT flagged.
        if re.search(r"\b(?:[A-Za-z_]\w*\s*[\+\-\*/]\s*[A-Za-z_0-9()]+)\b", code_line) and (
            "INT_MAX" in code_line or "SIZE_MAX" in code_line or "sizeof" in code_line or re.search(r"\b(?:alloc|size|len|count|capacity)\b", code_line)
        ):
            is_safe_alloc = False
            if "sizeof" in code_line and "INT_MAX" not in code_line and "SIZE_MAX" not in code_line:
                m_alloc = re.search(r"sizeof\s*\([^)]+\)\s*\*\s*(\d+)", code_line) or re.search(r"(\d+)\s*\*\s*sizeof\s*\([^)]+\)", code_line)
                if m_alloc:
                    count_val = int(m_alloc.group(1))
                    if count_val < 1000000:
                        is_safe_alloc = True
            if not is_safe_alloc:
                emit(
                    line_no,
                    "Integer Overflow",
                    "High",
                    "Arithmetic on size-like values may overflow before allocation or indexing.",
                    "Validate operands before arithmetic and use checked addition/multiplication for allocation sizes.",
                )
        # Cross-line check: arithmetic on a variable previously assigned a max sentinel
        elif overflow_risk_vars:
            for var_name in list(overflow_risk_vars):
                if re.search(rf"\b{re.escape(var_name)}\s*=\s*{re.escape(var_name)}\s*[\+\-\*/]", code_line) or \
                   re.search(rf"\b{re.escape(var_name)}\s*[\+\-\*/]=\s*", code_line) or \
                   re.search(rf"\b{re.escape(var_name)}\s*\+\+", code_line):
                    emit(
                        line_no,
                        "Integer Overflow",
                        "High",
                        f"Arithmetic on '{var_name}' which was assigned a max-boundary value (line {overflow_risk_vars[var_name]}); this will overflow.",
                        "Validate operands before arithmetic and use checked addition/multiplication for allocation sizes.",
                    )

        if "malloc(" in code_line:
            current_scope()["malloc_lines"].append(line_no)

        if "free(" in code_line:
            for scope in scope_stack:
                scope["free_seen"] = True

        # Bug 4.2 Fix: Check for double-free BEFORE updating freed_vars,
        # so consecutive `delete p; delete p;` isn't masked by self-overwrite.

        # First, check existing freed_vars for double-free and use-after-free
        for freed_name, freed_line in list(freed_vars.items()):
            if re.search(rf"\bdelete\s*(?:\[\])?\s*{re.escape(freed_name)}\s*;", code_line) and line_no != freed_line:
                emit(
                    line_no,
                    "Double Free",
                    "High",
                    "The same pointer appears to be deleted more than once.",
                    "Set the pointer to nullptr immediately after delete or switch to smart pointers.",
                )
            elif re.search(rf"\bfree\s*\(\s*{re.escape(freed_name)}\s*\)", code_line) and line_no != freed_line:
                emit(
                    line_no,
                    "Double Free",
                    "High",
                    "The same pointer appears to be freed more than once.",
                    "Set the pointer to nullptr immediately after free or switch to smart pointers.",
                )
            if re.search(rf"\*\s*{re.escape(freed_name)}\b|{re.escape(freed_name)}\s*->|{re.escape(freed_name)}\s*\[", code_line):
                emit(
                    line_no,
                    "Use After Free",
                    "High",
                    "Memory appears to be accessed after it was freed.",
                    "Do not use the pointer after delete; prefer unique_ptr or reset the pointer to nullptr.",
                )

        # NOW update freed_vars after checks have run
        delete_match = _DELETE_RE.search(code_line)
        if delete_match:
            freed_vars[delete_match.group(1)] = line_no

        # Also track free() calls for double-free detection
        free_match = re.search(r"\bfree\s*\(\s*([A-Za-z_]\w*)\s*\)", code_line)
        if free_match:
            freed_vars[free_match.group(1)] = line_no

        open_braces = code_line.count("{")
        close_braces = code_line.count("}")
        for _ in range(open_braces):
            scope_stack.append({"start_line": line_no, "malloc_lines": [], "free_seen": False})
        for _ in range(close_braces):
            if len(scope_stack) <= 1:
                continue
            finished = scope_stack.pop()
            if finished["malloc_lines"] and not finished["free_seen"]:
                for malloc_line in finished["malloc_lines"]:
                    emit(
                        malloc_line,
                        "Potential Memory Leak",
                        "Medium",
                        "malloc() allocates memory in this scope without a matching free() before the scope closes.",
                        "Release the allocation with free() in the same scope or replace manual ownership with RAII/smart pointers.",
                    )

    while len(scope_stack) > 1:
        finished = scope_stack.pop()
        if finished["malloc_lines"] and not finished["free_seen"]:
            for malloc_line in finished["malloc_lines"]:
                findings.append(
                    _make_finding(
                        source_path,
                        malloc_line,
                        None,
                        "Medium",
                        "Potential Memory Leak",
                        "malloc() allocates memory in this scope without a matching free() before the scope closes.",
                        "Release the allocation with free() in the same scope or replace manual ownership with RAII/smart pointers.",
                        "static_scan",
                    )
                )

    return findings


def _dedupe_findings(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    deduped: list[SecurityFinding] = []
    seen: set[tuple] = set()
    for finding in findings:
        key = (
            finding.file,
            finding.line,
            finding.column,
            finding.severity,
            finding.vulnerability_type,
            finding.description,
            finding.recommendation,
            finding.source,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)

    deduped.sort(
        key=lambda f: (
            _SEVERITY_ORDER[f.severity],
            f.file or "",
            f.line if f.line is not None else 10**9,
            f.column if f.column is not None else 10**9,
            f.vulnerability_type,
        )
    )
    return deduped


def analyze(source_path: str, compiler_errors: list[CompilerError]) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []

    for error in compiler_errors or []:
        findings.extend(_diagnostic_findings(error))

    findings.extend(_scan_source_findings(source_path))
    return _dedupe_findings(findings)


def _severity_counts(findings: list[SecurityFinding]) -> dict[Severity, int]:
    counts: dict[Severity, int] = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def _risk_label(score: int) -> str:
    if score == 0:
        return "Clean"
    if score <= 10:
        return "Low Risk"
    if score <= 30:
        return "Moderate"
    return "High Risk"


def format_security_report(findings: list[SecurityFinding]) -> str:
    findings = _dedupe_findings(findings)
    counts = _severity_counts(findings)
    score = sum(_SEVERITY_WEIGHT[f.severity] for f in findings)

    lines: list[str] = [
        f"{counts['Critical']} critical, {counts['High']} high, {counts['Medium']} medium, {counts['Low']} low findings",
        "",
    ]

    for severity in ("Critical", "High", "Medium", "Low"):
        group = [f for f in findings if f.severity == severity]
        if not group:
            continue
        lines.append(f"{severity.upper()}")
        for finding in group:
            location = finding.file
            if finding.line is not None:
                location += f":{finding.line}"
            badge = f"[{finding.severity.upper()}]"
            lines.append(f"{badge} {finding.vulnerability_type} - {location}")
            lines.append(f"  Description: {finding.description}")
            lines.append(f"  Recommendation: {finding.recommendation}")
            lines.append("")

    lines.append(f"Risk score: {score} ({_risk_label(score)})")
    return "\n".join(lines).strip() + "\n"
