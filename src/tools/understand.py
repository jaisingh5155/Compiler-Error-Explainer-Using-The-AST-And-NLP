"""
tools/understand.py
───────────────────
Tool 1: Compile → Parse → Classify → Enrich → return ProgramModel.

Wraps the existing compiler_runner → error_parser → error_classifier →
error_explainer pipeline and root-cause grouping into a single callable
that produces a ProgramModel with Diagnostic IR.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from diagnostic import Diagnostic, ProgramModel, from_compiler_error
from compiler_runner import run_cpp_compiler
from error_parser import parse_errors
from error_explainer import enrich_error
from error_normalizer import normalize_error
from ast_extractor import extract_ast, extract_node_near_line
from root_cause_grouper import group_by_root_cause


def understand(
    file_path: str,
    *,
    context_lines: int = 2,
    log_training: bool = False,
    llm_explain: bool = False,
    config: Optional[dict] = None,
) -> ProgramModel:
    """
    Compile *file_path*, parse diagnostics, classify, enrich, group by root cause,
    and return a ProgramModel.

    Parameters
    ----------
    file_path : str
        Path to the C++ source file.
    context_lines : int
        Number of context lines around each error.
    log_training : bool
        Whether to opt-in to dataset logging (default off to prevent leak).

    Returns
    -------
    ProgramModel
        Program model containing source, diagnostics, raw compile output, and AST.
    """
    source_code = ""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", errors="ignore") as f:
                source_code = f.read()
        except Exception:
            pass

    raw_output = run_cpp_compiler(file_path)

    if not raw_output:
        return ProgramModel(
            file_path=file_path,
            source_code=source_code,
            compile_output="",
            diagnostics=[],
            ast_text=None,
        )

    errors = parse_errors(raw_output)

    # AST extraction: Attempt real structured Clang JSON AST first
    ast_nodes = None
    symbol_table = None
    try:
        from ast_parser import parse_clang_ast, find_enclosing_ast_node
        from symbol_table import build_symbol_table
        ast_nodes = parse_clang_ast(file_path)
        if ast_nodes:
            symbol_table = build_symbol_table(ast_nodes)
    except Exception:
        ast_nodes = None
        symbol_table = None

    # Fallback legacy AST text only if structured AST extraction failed
    ast_text = None
    if not ast_nodes:
        try:
            ast_text = extract_ast(file_path)
        except Exception:
            ast_text = None

    ast_matches: list[tuple[Optional[str], Optional[str], bool]] = []
    for e in errors:
        node_type = None
        node_summary = None
        is_fallback = False

        if ast_nodes and e.line:
            matched_node, fb = find_enclosing_ast_node(ast_nodes, e.line, e.column or 1)
            if matched_node:
                node_type = matched_node.kind
                node_summary = matched_node.summary
                is_fallback = fb
            else:
                is_fallback = True

        if not node_type and e.line and ast_text:
            node_type = extract_node_near_line(ast_text, e.line)
            if node_type:
                node_summary = f"fallback:{node_type}"
            is_fallback = True

        ast_matches.append((node_type, node_summary, is_fallback))
        e.ast_node = node_type
        e.ast_node_summary = node_summary
        e.ast_fallback = is_fallback

        try:
            enrich_error(e, llm_explain=llm_explain, config=config)
            if log_training:
                from dataset_logger import log_example
                log_example(e, enabled=True)
        except Exception:
            pass

    # Convert to Diagnostic IR
    diagnostics: list[Diagnostic] = []
    for e, (ntype, nsummary, nfallback) in zip(errors, ast_matches):
        diag = from_compiler_error(e)
        diag.ast_node_type = ntype
        diag.ast_node_summary = nsummary
        diag.ast_fallback = nfallback
        try:
            diag.normalized_message, _ = normalize_error(diag.message)
        except Exception:
            diag.normalized_message = diag.message
        diagnostics.append(diag)

    # Apply root-cause grouping (Step 2)
    diagnostics = group_by_root_cause(diagnostics)

    return ProgramModel(
        file_path=file_path,
        source_code=source_code,
        compile_output=str(raw_output),
        diagnostics=diagnostics,
        ast_text=ast_text,
        ast_nodes=ast_nodes,
        symbol_table=symbol_table,
    )
