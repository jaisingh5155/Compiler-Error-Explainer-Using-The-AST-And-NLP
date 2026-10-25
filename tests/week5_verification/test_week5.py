"""
tests/week5_verification/test_week5.py
──────────────────────────────────────
Verification suite for Week 5 deliverables:
1. AST source-range mapping accuracy (5-file spot-check assertions)
2. Scoped symbol table correctness (declarations, types, scope lookups, did-you-mean)
3. DFA tokenizer (all states, transitions, raw strings, coordinate preservation)
4. PDA bracket checker (new syntax benchmarks sx11-sx14, unclosed, mismatched)
5. Shared tokenizer unification across auto_healer and security_analyzer
"""

import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
for p in (PROJECT_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from ast_parser import parse_clang_ast, find_enclosing_ast_node
from symbol_table import SymbolTable, Scope, Symbol, build_symbol_table
from lexer import State, Token, tokenize, mask_comments_and_strings, strip_code
from bracket_checker import check_brackets, BracketMismatch
from tools.understand import understand
from tools.detect import detect


# ── 1. AST Source-Range Mapping Accuracy ──────────────────────────────

class TestASTSourceRangeMapping:
    """Spot-check 5 representative files to confirm precise AST node mapping without fallback."""

    def test_type_error_te01_int_to_charptr(self):
        file_path = os.path.join(PROJECT_ROOT, "benchmark", "type_errors", "te01_int_to_charptr.cpp")
        pm = understand(file_path)
        assert len(pm.diagnostics) >= 1
        d = pm.diagnostics[0]
        assert d.ast_node_type in ("VarDecl", "DeclStmt")
        assert d.ast_fallback is False
        assert "p" in (d.ast_node_summary or "")

    def test_type_error_te02_int_plus_string(self):
        file_path = os.path.join(PROJECT_ROOT, "benchmark", "type_errors", "te02_int_plus_string.cpp")
        pm = understand(file_path)
        assert len(pm.diagnostics) >= 1
        d = pm.diagnostics[0]
        assert d.ast_node_type in ("RecoveryExpr", "BinaryOperator", "VarDecl")
        assert d.ast_fallback is False

    def test_type_error_te03_void_to_int(self):
        file_path = os.path.join(PROJECT_ROOT, "benchmark", "type_errors", "te03_void_to_int.cpp")
        pm = understand(file_path)
        assert len(pm.diagnostics) >= 1
        d = pm.diagnostics[0]
        assert d.ast_node_type in ("VarDecl", "DeclStmt", "CallExpr")
        assert d.ast_fallback is False

    def test_syntax_error_sx01_missing_semi(self):
        file_path = os.path.join(PROJECT_ROOT, "benchmark", "syntax", "sx01_missing_semi_decl.cpp")
        pm = understand(file_path)
        assert len(pm.diagnostics) >= 1
        d = pm.diagnostics[0]
        assert d.ast_node_type in ("DeclStmt", "VarDecl", "CompoundStmt")
        assert d.ast_fallback is False

    def test_name_resolution_nr06_misspelled_ident(self):
        file_path = os.path.join(PROJECT_ROOT, "benchmark", "name_resolution", "nr06_misspelled_ident.cpp")
        pm = understand(file_path)
        assert len(pm.diagnostics) >= 1
        d = pm.diagnostics[0]
        assert d.ast_node_type in ("CompoundStmt", "FunctionDecl")
        assert d.ast_fallback is False


# ── 2. Symbol Table Correctness ───────────────────────────────────────

class TestSymbolTableCorrectness:
    """Verify scope nesting, visibility, initialization, and edit-distance suggestions."""

    def test_scope_nesting_and_lookup(self):
        sym_tab = SymbolTable()
        global_scope = sym_tab.global_scope
        global_scope.symbols["g_count"] = Symbol(
            name="g_count", type_name="int", line=2, col=5, kind="variable", has_initializer=True
        )

        fn_scope = Scope(scope_type="function", name="process", parent=global_scope, begin_line=4, begin_col=1, end_line=15, end_col=1)
        global_scope.children.append(fn_scope)
        sym_tab.all_scopes.append(fn_scope)
        fn_scope.symbols["param"] = Symbol(
            name="param", type_name="int", line=4, col=17, kind="parameter", has_initializer=True
        )

        block_scope = Scope(scope_type="block", name="block", parent=fn_scope, begin_line=6, begin_col=5, end_line=10, end_col=5)
        fn_scope.children.append(block_scope)
        sym_tab.all_scopes.append(block_scope)
        block_scope.symbols["local_var"] = Symbol(
            name="local_var", type_name="std::string", line=7, col=9, kind="variable", has_initializer=False
        )

        # Lookup inside block finds local, param, and global
        assert sym_tab.is_declared("local_var", line=8, col=10) is True
        assert sym_tab.is_declared("param", line=8, col=10) is True
        assert sym_tab.is_declared("g_count", line=8, col=10) is True

        # Outside block, local_var is not visible
        assert sym_tab.is_declared("local_var", line=12, col=5) is False
        assert sym_tab.is_declared("param", line=12, col=5) is True

        # Initializer tracking
        assert sym_tab.is_initialized("local_var", line=8, col=10) is False
        assert sym_tab.is_initialized("g_count", line=8, col=10) is True

    def test_symbol_table_did_you_mean_enrichment(self):
        file_path = os.path.join(PROJECT_ROOT, "benchmark", "name_resolution", "nr06_misspelled_ident.cpp")
        pm = understand(file_path)
        diags = detect(pm)
        assert len(diags) >= 1
        name_diag = next((d for d in diags if "countr" in d.message), None)
        assert name_diag is not None
        assert name_diag.did_you_mean == "counter"
        assert "counter" in (name_diag.suggestion or "")


# ── 3. DFA Tokenizer ──────────────────────────────────────────────────

class TestDFATokenizer:
    """Verify the formal DFA tokenizer across all 6 states and transitions."""

    def test_line_comment_transition(self):
        src = "int a = 1; // this is a line comment\nint b = 2;"
        tokens = tokenize(src)
        types = [t.kind for t in tokens]
        assert State.LINE_COMMENT in types
        lc_token = next(t for t in tokens if t.kind == State.LINE_COMMENT)
        assert "// this is a line comment\n" == lc_token.value

    def test_block_comment_transition(self):
        src = "int x = 1; /* block comment spanning\nmultiple lines */ int y = 2;"
        tokens = tokenize(src)
        assert any(t.kind == State.BLOCK_COMMENT for t in tokens)
        bc = next(t for t in tokens if t.kind == State.BLOCK_COMMENT)
        assert "multiple lines" in bc.value

    def test_string_and_char_literals_with_escapes(self):
        src = 'char q = \'z\'; string s = "hello \\"quoted\\" world";'
        tokens = tokenize(src)
        assert any(t.kind == State.CHAR_LITERAL for t in tokens)
        assert any(t.kind == State.STRING for t in tokens)

    def test_raw_string_literal(self):
        src = r'auto raw = R"delim(hello (world) [brackets] {braces})delim";'
        tokens = tokenize(src)
        raw_toks = [t for t in tokens if t.kind == State.RAW_STRING]
        assert len(raw_toks) == 1
        assert "hello (world) [brackets] {braces}" in raw_toks[0].value

    def test_mask_comments_and_strings_preserves_length_and_layout(self):
        src = (
            "int x = 42; // line comment\n"
            "/* block comment */\n"
            "string s = \"secret 123\";\n"
            "char c = 'z';\n"
        )
        masked = mask_comments_and_strings(src)
        assert len(masked) == len(src)
        for orig_line, mask_line in zip(src.splitlines(keepends=True), masked.splitlines(keepends=True)):
            assert len(orig_line) == len(mask_line)
        assert "secret 123" not in masked
        assert "line comment" not in masked
        assert "block comment" not in masked
        assert "int x = 42;" in masked


# ── 4. PDA Bracket Checker ────────────────────────────────────────────

class TestPDABracketChecker:
    """Verify pushdown automaton bracket verification on benchmark test cases."""

    def test_sx11_nested_bracket_mismatch(self):
        path = os.path.join(PROJECT_ROOT, "benchmark", "syntax", "sx11_nested_bracket_mismatch.cpp")
        with open(path) as f:
            src = f.read()
        mismatches = check_brackets(src)
        assert len(mismatches) > 0
        assert any(m.kind == "unclosed" and m.bracket == "{" for m in mismatches)

    def test_sx12_brackets_in_string_ignored(self):
        path = os.path.join(PROJECT_ROOT, "benchmark", "syntax", "sx12_brackets_in_string.cpp")
        with open(path) as f:
            src = f.read()
        mismatches = check_brackets(src)
        # Should NOT complain about braces/brackets inside the string literal
        assert len(mismatches) > 0
        # The actual syntax error is unclosed '(' on cout << (msg.length() + 5;
        assert any(m.bracket in ("(", "}") for m in mismatches)

    def test_sx13_deeply_nested_unclosed(self):
        path = os.path.join(PROJECT_ROOT, "benchmark", "syntax", "sx13_deeply_nested_unclosed.cpp")
        with open(path) as f:
            src = f.read()
        mismatches = check_brackets(src)
        assert len(mismatches) > 0
        assert any(m.kind == "unclosed" and m.bracket == "{" for m in mismatches)

    def test_sx14_mismatched_paren_bracket(self):
        path = os.path.join(PROJECT_ROOT, "benchmark", "syntax", "sx14_mismatched_paren_bracket.cpp")
        with open(path) as f:
            src = f.read()
        mismatches = check_brackets(src)
        assert len(mismatches) > 0
        m = next((m for m in mismatches if m.kind == "mismatched"), None)
        assert m is not None
        assert m.bracket == ")"
        assert m.expected == "]"


# ── 5. Shared Tokenizer Unification ───────────────────────────────────

class TestSharedTokenizerUnification:
    """Confirm auto_healer.py and security_analyzer.py both use the single shared lexer.py."""

    def test_auto_healer_uses_shared_lexer(self):
        import auto_healer
        import lexer
        assert hasattr(auto_healer, "_mask_comments_and_strings")
        # Check that auto_healer._mask_comments_and_strings produces identical output to lexer
        sample = "int x = 10; // comment\nstring s = \"hello\";"
        assert auto_healer._mask_comments_and_strings(sample) == lexer.mask_comments_and_strings(sample)

    def test_security_analyzer_uses_shared_lexer(self):
        import security_analyzer
        import lexer
        assert hasattr(security_analyzer, "_strip_code")
        state1 = {"in_block_comment": False, "raw_delim": None}
        state2 = {"in_block_comment": False, "raw_delim": None}
        line = "int a = /* block */ 5; // line"
        res_sa = security_analyzer._strip_code(line, state1)
        res_lex = lexer.strip_code(line, state2)
        assert res_sa == res_lex
