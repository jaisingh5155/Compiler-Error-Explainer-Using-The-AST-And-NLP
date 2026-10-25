"""
src/bracket_checker.py
──────────────────────
Pushdown Automaton (PDA) Bracket Checker for C++.

Validates balanced brackets: {}, (), [] across C++ source files.
Reuses the DFA tokenizer from src/lexer.py to skip comments and string literals.
Reports precise mismatch origins (unclosed, unexpected closing, mismatched pairs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    from lexer import State, tokenize
except ImportError:
    from src.lexer import State, tokenize

_MATCHING_PAIRS = {
    "}": "{",
    ")": "(",
    "]": "[",
}

_EXPECTED_CLOSING = {
    "{": "}",
    "(": ")",
    "[": "]",
}


@dataclass
class BracketMismatch:
    kind: str  # 'unclosed', 'unexpected_closing', 'mismatched'
    bracket: str
    line: int
    col: int
    expected: Optional[str] = None
    open_line: Optional[int] = None
    open_col: Optional[int] = None
    message: str = ""

    def __str__(self) -> str:
        return self.message


@dataclass
class StackFrame:
    bracket: str
    line: int
    col: int
    indent: str = ""


def check_brackets(source: str) -> list[BracketMismatch]:
    """
    Run PDA bracket verification over the source code.
    Skips string literals and comments via DFA lexer.
    Returns list of BracketMismatch objects.
    """
    tokens = tokenize(source)
    stack: list[StackFrame] = []
    mismatches: list[BracketMismatch] = []

    for tok in tokens:
        if tok.kind != State.CODE:
            continue

        tok_line = tok.line
        tok_col = tok.col

        for ch in tok.value:
            if ch in ("{", "(", "["):
                stack.append(
                    StackFrame(
                        bracket=ch,
                        line=tok_line,
                        col=tok_col,
                    )
                )
            elif ch in ("}", ")", "]"):
                expected_open = _MATCHING_PAIRS[ch]
                if not stack:
                    # Unexpected closing bracket without opener
                    mismatches.append(
                        BracketMismatch(
                            kind="unexpected_closing",
                            bracket=ch,
                            line=tok_line,
                            col=tok_col,
                            message=f"unexpected '{ch}' at line {tok_line}:{tok_col} with no matching opener",
                        )
                    )
                else:
                    top = stack[-1]
                    if top.bracket == expected_open:
                        stack.pop()
                    else:
                        # Mismatched bracket pair: e.g. '{' closed with ')'
                        expected_close = _EXPECTED_CLOSING.get(top.bracket, "")
                        mismatches.append(
                            BracketMismatch(
                                kind="mismatched",
                                bracket=ch,
                                expected=expected_close,
                                line=tok_line,
                                col=tok_col,
                                open_line=top.line,
                                open_col=top.col,
                                message=(
                                    f"mismatched '{ch}' at line {tok_line}:{tok_col}; "
                                    f"expected '{expected_close}' matching '{top.bracket}' "
                                    f"opened at line {top.line}:{top.col}"
                                ),
                            )
                        )
                        stack.pop()

            if ch == "\n":
                tok_line += 1
                tok_col = 1
            else:
                tok_col += 1

    # End of file: any remaining brackets on stack are unclosed
    while stack:
        frame = stack.pop()
        expected_close = _EXPECTED_CLOSING.get(frame.bracket, "")
        mismatches.append(
            BracketMismatch(
                kind="unclosed",
                bracket=frame.bracket,
                expected=expected_close,
                line=frame.line,
                col=frame.col,
                open_line=frame.line,
                open_col=frame.col,
                message=(
                    f"unclosed '{frame.bracket}' opened at line {frame.line}:{frame.col}, "
                    f"expected '{expected_close}' before end of file"
                ),
            )
        )

    return mismatches


def find_unclosed_braces(source: str) -> list[StackFrame]:
    """
    Return all unclosed '{' frames in LIFO order for auto-healing.
    """
    tokens = tokenize(source)
    stack: list[StackFrame] = []

    for tok in tokens:
        if tok.kind != State.CODE:
            continue

        tok_line = tok.line
        tok_col = tok.col

        for ch in tok.value:
            if ch == "{":
                stack.append(
                    StackFrame(
                        bracket=ch,
                        line=tok_line,
                        col=tok_col,
                    )
                )
            elif ch == "}":
                if stack:
                    stack.pop()

            if ch == "\n":
                tok_line += 1
                tok_col = 1
            else:
                tok_col += 1

    return stack
