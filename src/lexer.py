"""
src/lexer.py
────────────
Formal Deterministic Finite Automaton (DFA) Tokenizer for C++.

Replaces ad hoc string and comment stripping across auto_healer.py and
security_analyzer.py with a formalized state machine.

States:
  - CODE: Normal source code (statements, expressions, keywords)
  - LINE_COMMENT: C++ line comment (// ...)
  - BLOCK_COMMENT: C-style block comment (/* ... */)
  - STRING: Double-quoted string literal ("...") with escape tracking
  - CHAR_LITERAL: Single-quoted character literal ('...') with escape tracking
  - RAW_STRING: C++11 raw string literal (R"delim(...)delim")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class State(Enum):
    CODE = auto()
    LINE_COMMENT = auto()
    BLOCK_COMMENT = auto()
    STRING = auto()
    CHAR_LITERAL = auto()
    RAW_STRING = auto()


@dataclass
class Token:
    kind: State
    value: str
    line: int
    col: int
    end_line: int
    end_col: int


_RAW_STRING_START = re.compile(r'R"([A-Za-z0-9_{}\[\]#<>%:;.?*+\-/\^&|~!=,"\s]*)\(')


def tokenize(source: str) -> list[Token]:
    """
    Run the DFA on source code and return a list of typed Tokens.
    """
    tokens: list[Token] = []
    n = len(source)
    i = 0
    line = 1
    col = 1

    state = State.CODE
    buf: list[str] = []
    tok_start_line = 1
    tok_start_col = 1
    raw_delim: Optional[str] = None
    escape = False

    def emit_token(end_l: int, end_c: int) -> None:
        nonlocal buf, state, tok_start_line, tok_start_col
        if buf:
            tokens.append(
                Token(
                    kind=state,
                    value="".join(buf),
                    line=tok_start_line,
                    col=tok_start_col,
                    end_line=end_l,
                    end_col=end_c,
                )
            )
            buf = []

    while i < n:
        ch = source[i]
        curr_line = line
        curr_col = col

        if state == State.CODE:
            # Check for line comment //
            if ch == "/" and i + 1 < n and source[i + 1] == "/":
                emit_token(curr_line, curr_col)
                state = State.LINE_COMMENT
                tok_start_line = curr_line
                tok_start_col = curr_col
                buf.append("//")
                i += 2
                col += 2
                continue

            # Check for block comment /*
            if ch == "/" and i + 1 < n and source[i + 1] == "*":
                emit_token(curr_line, curr_col)
                state = State.BLOCK_COMMENT
                tok_start_line = curr_line
                tok_start_col = curr_col
                buf.append("/*")
                i += 2
                col += 2
                continue

            # Check for C++11 raw string literal R"delim(
            raw_match = _RAW_STRING_START.match(source, i)
            if raw_match:
                emit_token(curr_line, curr_col)
                state = State.RAW_STRING
                raw_delim = raw_match.group(1)
                matched_str = raw_match.group(0)
                tok_start_line = curr_line
                tok_start_col = curr_col
                buf.append(matched_str)
                advance = len(matched_str)
                i += advance
                col += advance
                continue

            # Check for string literal "
            if ch == '"':
                emit_token(curr_line, curr_col)
                state = State.STRING
                tok_start_line = curr_line
                tok_start_col = curr_col
                buf.append(ch)
                escape = False
                i += 1
                col += 1
                continue

            # Check for char literal '
            if ch == "'":
                emit_token(curr_line, curr_col)
                state = State.CHAR_LITERAL
                tok_start_line = curr_line
                tok_start_col = curr_col
                buf.append(ch)
                escape = False
                i += 1
                col += 1
                continue

            # Accumulate normal code character
            if not buf:
                tok_start_line = curr_line
                tok_start_col = curr_col
            buf.append(ch)
            i += 1
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1

        elif state == State.LINE_COMMENT:
            buf.append(ch)
            i += 1
            if ch == "\n":
                line += 1
                col = 1
                emit_token(curr_line, curr_col)
                state = State.CODE
            else:
                col += 1

        elif state == State.BLOCK_COMMENT:
            buf.append(ch)
            if ch == "*" and i + 1 < n and source[i + 1] == "/":
                buf.append("/")
                i += 2
                col += 2
                emit_token(line, col)
                state = State.CODE
                continue

            i += 1
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1

        elif state == State.STRING:
            buf.append(ch)
            i += 1
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1

            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                emit_token(line, col)
                state = State.CODE

        elif state == State.CHAR_LITERAL:
            buf.append(ch)
            i += 1
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1

            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                emit_token(line, col)
                state = State.CODE

        elif state == State.RAW_STRING:
            closing_pattern = f"){raw_delim}\""
            if source.startswith(closing_pattern, i):
                buf.append(closing_pattern)
                advance = len(closing_pattern)
                i += advance
                col += advance
                emit_token(line, col)
                state = State.CODE
                raw_delim = None
                continue

            buf.append(ch)
            i += 1
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1

    # End of input
    if buf:
        emit_token(line, col)

    return tokens


def mask_comments_and_strings(
    source: str,
    mask_char: str = " ",
    preserve_newlines: bool = True,
) -> str:
    """
    Mask comments, string literals, char literals, and raw string literals
    with mask_char, preserving character length, offsets, and line/column positions.
    """
    tokens = tokenize(source)
    out: list[str] = []

    for tok in tokens:
        if tok.kind == State.CODE:
            out.append(tok.value)
        else:
            # Mask every char except newlines
            chars: list[str] = []
            for c in tok.value:
                if preserve_newlines and c in ("\n", "\r"):
                    chars.append(c)
                else:
                    chars.append(mask_char)
            out.append("".join(chars))

    return "".join(out)


def strip_code(line: str, state: Optional[dict[str, object]] = None) -> str:
    """
    Line-by-line code stripper compatible with security_analyzer's streaming interface.
    Removes comments, string contents, and raw string contents, preserving syntax structure.
    """
    if state is None:
        state = {}

    in_block_comment = bool(state.get("in_block_comment"))
    raw_delim = state.get("raw_delim")
    out: list[str] = []
    i = 0
    n = len(line)

    while i < n:
        if raw_delim is not None:
            raw_end = line.find(f"){raw_delim}\"", i)
            if raw_end == -1:
                state["raw_delim"] = raw_delim
                return "".join(out)
            i = raw_end + len(str(raw_delim)) + 2
            raw_delim = None
            continue

        if in_block_comment:
            comment_end = line.find("*/", i)
            if comment_end == -1:
                state["in_block_comment"] = True
                return "".join(out)
            i = comment_end + 2
            in_block_comment = False
            continue

        if line.startswith("//", i):
            break

        if line.startswith("/*", i):
            in_block_comment = True
            i += 2
            continue

        raw_match = _RAW_STRING_START.match(line, i)
        if raw_match:
            raw_delim = raw_match.group(1)
            i = raw_match.end()
            continue

        ch = line[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == quote:
                    i += 1
                    break
                i += 1
            continue

        out.append(ch)
        i += 1

    state["in_block_comment"] = in_block_comment
    state["raw_delim"] = raw_delim
    return "".join(out)
