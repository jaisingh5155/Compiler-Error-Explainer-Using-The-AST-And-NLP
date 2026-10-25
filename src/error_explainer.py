"""
src/error_explainer.py
──────────────────────
Dynamic explanation engine for compiler diagnostics.
Fills explanations from the diagnostic's actual content, entities,
and AST context rather than fixed per-category templates:
- Includes actual identifier, type, and function names involved
- References AST node type in plain language (e.g. "while declaring variable `x`" for VarDecl)
- Incorporates symbol-table "did you mean" suggestions directly in explanation text
- Supports Beginner (plain language What/Why/How) and Detailed (adds AST node, source range, confidence)
"""

import os
import re
from typing import Dict, Any, Optional, Tuple
from error_classifier import get_default_classifier
from error_normalizer import normalize_error
from common_errors import COMMON_ERRORS
from security_analyzer import analyze
from config_loader import load_config


# ── Standard Library Symbol to Required Header Mapping ────────────────────────

STD_SYMBOL_TO_HEADER: Dict[str, str] = {
    # <iostream>
    "cout": "iostream",
    "cin": "iostream",
    "cerr": "iostream",
    "clog": "iostream",
    "endl": "iostream",
    # <vector>
    "vector": "vector",
    # <string>
    "string": "string",
    "wstring": "string",
    # <map>
    "map": "map",
    "multimap": "map",
    # <set>
    "set": "set",
    "multiset": "set",
    # <utility>
    "pair": "utility",
    "make_pair": "utility",
    # <algorithm>
    "sort": "algorithm",
    "find": "algorithm",
    "reverse": "algorithm",
    "max": "algorithm",
    "min": "algorithm",
    "count": "algorithm",
    # <memory>
    "unique_ptr": "memory",
    "shared_ptr": "memory",
    "make_unique": "memory",
    "make_shared": "memory",
    # <fstream>
    "ifstream": "fstream",
    "ofstream": "fstream",
    "fstream": "fstream",
    # <sstream>
    "stringstream": "sstream",
    "istringstream": "sstream",
    "ostringstream": "sstream",
    # <cmath>
    "sqrt": "cmath",
    "pow": "cmath",
}


def is_header_included(file_path: Optional[str], header: str) -> bool:
    """Check if header is already included in file_path."""
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        with open(file_path, "r", errors="ignore") as f:
            content = f.read()
        return bool(re.search(rf"#\s*include\s*[<\"]\s*(?:{re.escape(header)}|bits/stdc\+\+\.h)\s*[>\"]", content))
    except Exception:
        return False


# ── Entity Extraction from Diagnostic Messages ────────────────────────────────

def extract_entities(message: str) -> Dict[str, str]:
    """
    Extract identifiers, types, member names, and function names
    from a compiler diagnostic message.
    """
    entities: Dict[str, str] = {}
    if not message:
        return entities

    # 1. Undeclared identifier / unknown type
    m = re.search(r"use of undeclared identifier ['‘\"](\w+)['’\"]", message)
    if not m:
        m = re.search(r"['‘\"](\w+)['’\"]\s+(?:was not declared|has not been declared)", message)
    if not m:
        m = re.search(r"no template named ['‘\"](\w+)['’\"]", message)
    if not m:
        m = re.search(r"unknown type name ['‘\"](\w+)['’\"]", message)
    if not m:
        m = re.search(r"no member named ['‘\"](\w+)['’\"]\s+in\s+namespace\s+['‘\"]std['‘\"]", message)
    if m:
        entities["identifier"] = m.group(1)


    # 2. Member not found
    m = re.search(r"no member named ['‘\"](\w+)['’\"]\s+in\s+['‘\"]([^'’\"]+)['’\"]", message)
    if m:
        entities["member"] = m.group(1)
        entities["scope"] = m.group(2)
    else:
        m = re.search(r"['‘\"](?:class|struct)\s+([^'’\"]+)['’\"]\s+has no member named\s+['‘\"](\w+)['’\"]", message)
        if m:
            entities["scope"] = m.group(1)
            entities["member"] = m.group(2)

    # 3. Type conversion / mismatch
    m = re.search(r"cannot initialize (?:a variable of )?type ['‘\"]([^'’\"]+)['’\"]\s+with an? (?:lvalue|rvalue) of type ['‘\"]([^'’\"]+)['’\"]", message)
    if m:
        entities["target_type"] = m.group(1)
        entities["source_type"] = m.group(2)
    else:
        m = re.search(r"invalid conversion from ['‘\"]([^'’\"]+)['’\"]\s+to\s+['‘\"]([^'’\"]+)['’\"]", message)
        if m:
            entities["source_type"] = m.group(1)
            entities["target_type"] = m.group(2)
        else:
            m = re.search(r"cannot convert ['‘\"]([^'’\"]+)['’\"]\s+to\s+['‘\"]([^'’\"]+)['’\"]", message)
            if m:
                entities["source_type"] = m.group(1)
                entities["target_type"] = m.group(2)

    # 4. Binary operator mismatch
    m = re.search(r"invalid operands to binary expression \(['‘\"]([^'’\"]+)['’\"]\s+and\s+['‘\"]([^'’\"]+)['’\"]\)", message)
    if m:
        entities["source_type"] = m.group(1)
        entities["target_type"] = m.group(2)
    else:
        m = re.search(r"no match for (?:operator\S*)\s+with types\s+['‘\"]([^'’\"]+)['’\"]\s+and\s+['‘\"]([^'’\"]+)['’\"]", message)
        if m:
            entities["source_type"] = m.group(1)
            entities["target_type"] = m.group(2)

    # 5. Missing header
    m = re.search(r"['‘\"]([^'’\"]+)['’\"]\s+file not found", message)
    if not m:
        m = re.search(r"cannot open include file ['‘\"]([^'’\"]+)['’\"]", message)
    if m:
        entities["header"] = m.group(1)

    # 6. Function return issues
    m = re.search(r"non-void function ['‘\"](\w+)['’\"]\s+should return a value", message)
    if not m:
        m = re.search(r"void function ['‘\"](\w+)['’\"]\s+should not return a value", message)
    if m:
        entities["function"] = m.group(1)

    # 7. Redefinition
    m = re.search(r"redefinition of ['‘\"](\w+)['’\"]", message)
    if not m:
        m = re.search(r"['‘\"](\w+)['’\"]\s+has a previous declaration", message)
    if m and "identifier" not in entities:
        entities["identifier"] = m.group(1)

    return entities


# ── Plain-Language AST Context Translation ────────────────────────────────────

def format_ast_context(ast_node: Optional[str], entities: Dict[str, str]) -> str:
    """
    Translate an AST node type into a natural, plain-language description
    incorporating identified entities.
    """
    if not ast_node or ast_node in ("Unknown", "None", ""):
        return ""

    ident = entities.get("identifier") or entities.get("member") or ""

    node_map = {
        "VarDecl": f"while declaring the variable `{ident}`" if ident else "while declaring a variable",
        "FieldDecl": f"while declaring member field `{ident}`" if ident else "while declaring a struct/class field",
        "FunctionDecl": f"in the definition of function `{ident}`" if ident else "in the function declaration",
        "CXXMethodDecl": f"in the method `{ident}`" if ident else "in the method definition",
        "CXXRecordDecl": f"in the definition of class/struct `{ident}`" if ident else "in the class/struct definition",
        "BinaryOperator": "during an operation between two expressions",
        "UnaryOperator": "during a unary operation",
        "CallExpr": f"while calling function `{ident}`" if ident else "while calling a function",
        "DeclRefExpr": f"while referencing identifier `{ident}`" if ident else "while referencing a variable",
        "MemberExpr": f"while accessing member `{ident}`" if ident else "while accessing a member",
        "ReturnStmt": "in the return statement of this function",
        "DeclStmt": f"while declaring variable `{ident}`" if ident else "in a variable declaration statement",
        "CompoundStmt": "inside a statement block",
        "RecoveryExpr": "inside an unparsed or ill-formed expression",
        "UnresolvedLookupExpr": f"while resolving name `{ident}`" if ident else "while looking up an identifier",
        "IfStmt": "inside an if condition or branch",
        "ForStmt": "inside a for loop",
        "WhileStmt": "inside a while loop",
    }
    return node_map.get(ast_node, f"inside a {ast_node}")


# ── Format Helpers ────────────────────────────────────────────────────────────

def format_error(what: str, why: str, how: str) -> str:
    return (
        f"What happened:\n"
        f" {what}\n\n"
        f"Why it happened:\n"
        f" {why}\n\n"
        f"How to fix it:\n"
        f" {how}"
    )


def lookup_common_error(message: str) -> Optional[Dict[str, Any]]:
    lowered_msg = message.lower()
    for common in COMMON_ERRORS:
        template_msg = common["message"].lower().strip("'\"")
        if template_msg in lowered_msg:
            return common
    return None


# ── Dynamic Category Explanations ─────────────────────────────────────────────

def build_dynamic_explanation(
    category: str,
    message: str,
    entities: Dict[str, str],
    ast_phrase: str,
    did_you_mean: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    """
    Constructs dynamic (what, why, how, suggestion) tuples incorporating
    real names, AST context, and Levenshtein suggestions.
    """
    ident = entities.get("identifier")
    member = entities.get("member")
    scope = entities.get("scope")
    t1 = entities.get("source_type")
    t2 = entities.get("target_type")
    header = entities.get("header")
    fn = entities.get("function")

    ast_suffix = f" {ast_phrase}" if ast_phrase else ""

    if category == "name_resolution":
        target_name = member or ident or "identifier"
        if did_you_mean:
            what = f"The compiler encountered `{target_name}`, which is not declared in this scope."
            why = (
                f"In C++, every variable, function, or member must be declared before use{ast_suffix}. "
                f"The symbol table found a close match `{did_you_mean}` in scope."
            )
            how = f"Did you mean `{did_you_mean}`? Change `{target_name}` to `{did_you_mean}`, or declare `{target_name}` before this line."
            suggestion = f"Did you mean '{did_you_mean}'? (Rename or declare '{target_name}')"
        elif member and scope:
            what = f"Class or struct `{scope}` has no member named `{member}`."
            why = f"The member `{member}` does not exist in `{scope}`{ast_suffix}."
            how = f"Check the definition of `{scope}` to ensure `{member}` is declared and spelled correctly, or add it to `{scope}`."
            suggestion = f"Declare '{member}' inside '{scope}' or verify spelling."
        elif ident:
            what = f"The identifier `{ident}` is used but has not been declared."
            why = f"In C++, names must be declared with a type before they are used{ast_suffix}."
            how = f"Declare `{ident}` before this line, check for typos, or include the appropriate namespace / header."
            suggestion = f"Declare '{ident}' before use or check spelling."
        else:
            what = "The compiler encountered an identifier that has not been declared."
            why = f"Every variable, function, or class must be declared before use{ast_suffix}."
            how = "Declare the identifier before use, check spelling, or add missing includes."
            suggestion = "Declare the identifier before use or add missing includes."

    elif category == "type_error":
        if t1 and t2:
            what = f"Cannot convert from `{t1}` to incompatible type `{t2}`."
            why = f"C++ is strongly typed and disallows assigning or passing `{t1}` where `{t2}` is expected{ast_suffix}."
            how = f"Use an explicit cast `static_cast<{t2}>(...)` if the conversion is safe, or change the variable's declared type to `{t1}`."
            suggestion = f"Convert '{t1}' to '{t2}' using explicit cast or adjust types."
        else:
            what = "A value of one type is being used where an incompatible type is expected."
            why = f"C++ prevents operations between incompatible types without an explicit cast{ast_suffix}."
            how = "Check the types of the values involved, adjust variable declarations, or use an explicit cast."
            suggestion = "Ensure compatible operand types or use an explicit cast."

    elif category == "missing_include":
        hdr_display = f"<{header}>" if header else "header file"
        what = f"The required header {hdr_display} could not be found or was omitted."
        why = f"Types and functions provided by {hdr_display} are inaccessible until the header is included."
        how = f"Add `#include {hdr_display}` at the top of your source file."
        suggestion = f"Add missing `#include {hdr_display}` directive."

    elif category == "return_type_error":
        if fn:
            what = f"Function `{fn}` has an invalid or missing return statement."
            why = f"Non-void functions in C++ must return a value matching their declared type{ast_suffix}."
            how = f"Ensure all execution paths in `{fn}` end with a valid return statement, or set return type to `void`."
            suggestion = f"Add or fix return statement in function '{fn}'."
        else:
            what = "A function has a missing return statement or returns an incompatible type."
            why = f"In C++, non-void functions must return a value matching their declared signature{ast_suffix}."
            how = "Add a return statement matching the function's declared return type, or change the function return type to void."
            suggestion = "Add a return statement matching the function's declared return type."

    elif category == "redefinition":
        target = ident or "identifier"
        what = f"The identifier `{target}` is defined more than once in the same scope."
        why = f"C++ enforces the One Definition Rule (ODR); multiple definitions cause ambiguity{ast_suffix}."
        how = f"Remove or rename the duplicate definition of `{target}`. If defined in a header, add `#pragma once`."
        suggestion = f"Remove duplicate definition of '{target}'."

    elif category == "access_error":
        if member:
            what = f"Cannot access private or protected member `{member}` from this context."
            why = f"Encapsulation rules restrict access to `{member}` to member functions and friend classes{ast_suffix}."
            how = f"Provide a public getter/setter method for `{member}`, declare the caller as a friend, or change its access specifier."
            suggestion = f"Use a public accessor for '{member}' or change its visibility."
        else:
            what = "A private or protected member is being accessed, or a const variable is being modified."
            why = f"C++ enforces access control specifiers and const-correctness{ast_suffix}."
            how = "Use public member methods to access the data, or ensure you are not modifying a const value."
            suggestion = "Use a public accessor method or check const-correctness."

    elif category == "syntax_error":
        _, specific_what = normalize_error(message)
        what = specific_what if specific_what else f"Unexpected syntax: {message}"
        why = f"C++ grammar rules were violated{ast_suffix}. The parser could not parse the token sequence."
        how = "Check the reported line and preceding line for missing semicolons (`;`), unclosed braces/parentheses, or stray tokens."
        suggestion = "Fix syntax error near the reported location."

    elif category == "linker_error":
        what = f"Linker error: {message}"
        why = "A function or variable was declared, but its compiled definition was not found by the linker."
        how = "Ensure the source file implementing the symbol is compiled and linked, and check for signature mismatches."
        suggestion = "Ensure the function is defined and all source files are compiled."

    else: # other
        what = f"Compiler diagnostic: {message}"
        why = f"An issue was encountered{ast_suffix} that does not fit a standard error category."
        how = "Read the compiler output carefully and verify the syntax and types around this line."
        suggestion = "Examine compiler message and correct highlighted code."

    return what, why, how, suggestion


# ── Security Rules ────────────────────────────────────────────────────────────

SECURITY_RULES = [
    {
        "pattern": r"unused variable|variable .+ set but not used",
        "risk": "Low",
        "reason": "Unused variables can indicate dead code, abandoned checks, or incomplete security logic."
    },
    {
        "pattern": r"may be used uninitialized",
        "risk": "High",
        "reason": "Uninitialized variables may cause undefined behavior or memory corruption."
    },
    {
        "pattern": r"division by zero",
        "risk": "High",
        "reason": "Division by zero can crash the program or cause undefined behavior."
    },
    {
        "pattern": r"invalid conversion",
        "risk": "Medium",
        "reason": "Incorrect type conversion may lead to memory or logic errors."
    },
    {
        "pattern": r"assignment of read-only location",
        "risk": "Medium",
        "reason": "Modifying const-qualified data may indicate unsafe design."
    },
    {
        "pattern": r"undefined reference",
        "risk": "Low",
        "reason": "Linker errors typically do not introduce runtime vulnerabilities."
    }
]


def analyze_security_risk(error):
    if not error or not error.message:
        return "None", None

    for rule in SECURITY_RULES:
        if re.search(rule["pattern"], error.message, re.IGNORECASE):
            return rule["risk"], rule["reason"]
    return "Low", "No immediate security risk detected."


# ── Main Explainer API ────────────────────────────────────────────────────────

def explain_error(
    error,
    mode: str = "beginner",
    llm_explain: bool = False,
    config: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Generate dynamic Beginner and Detailed explanations for an error.
    
    Parameters
    ----------
    error : CompilerError or Diagnostic
        The error to explain.
    mode : "beginner" | "detailed"
        Controls the verbosity returned in the primary 'explanation' field.
        Both modes are always available in 'explanation_beginner' and 'explanation_detailed'.
    llm_explain : bool
        Opt-in flag requesting LLM explanation enhancement. Double-gated by config.yaml.
    config : dict | None
        Optional config override dict.
    """
    if not error or not getattr(error, "message", None):
        empty_expl = "No error message provided."
        return {
            "explanation": empty_expl,
            "explanation_beginner": empty_expl,
            "explanation_detailed": empty_expl,
            "suggestion": "Check the compilation command and input files.",
            "category": "other",
            "confidence": 0.0,
            "explanation_source": "template",
        }

    message = error.message
    ast_node = getattr(error, "ast_node", None) or getattr(error, "ast_node_type", None) or ""
    ast_summary = getattr(error, "ast_node_summary", None)
    ast_fallback = getattr(error, "ast_fallback", False)
    did_you_mean = getattr(error, "did_you_mean", None)

    def _finalize(cat_val: str, conf_val: float, sugg_val: str, beg_text: str, det_text: str) -> Dict[str, Any]:
        cfg = config if config is not None else load_config()
        llm_cfg = cfg.get("llm_explainer", {})
        llm_enabled = bool(llm_cfg.get("enabled", False))

        source = "template"
        fallback_reason = None
        final_beg = beg_text
        final_det = det_text

        # Double-gating: MUST be enabled in config AND opted-in via flag
        if llm_enabled and llm_explain:
            try:
                from llm_explainer import enhance_explanation
                template_expl = beg_text if mode == "beginner" else det_text
                diag_input = {
                    "category": cat_val,
                    "message": message,
                    "ast_node_type": ast_node or None,
                    "confidence": float(conf_val),
                    "suggestion": sugg_val or None,
                    "cwe": getattr(error, "cwe", None),
                    "existing_template_explanation": template_expl,
                }
                res_llm = enhance_explanation(diag_input, llm_cfg)
                source = res_llm.get("source", "template_fallback")
                fallback_reason = res_llm.get("fallback_reason")
                llm_text = res_llm.get("text", "")
                if llm_text:
                    if mode == "beginner":
                        final_beg = llm_text
                    else:
                        # In detailed mode, replace top narrative explanation while preserving details
                        detail_suffix = det_text[len(beg_text):] if det_text.startswith(beg_text) else f"\n\n{det_text}"
                        final_det = llm_text + detail_suffix
            except Exception as e:
                source = "template_fallback"
                fallback_reason = f"exception:{type(e).__name__}"

        return {
            "explanation": final_det if mode == "detailed" else final_beg,
            "explanation_beginner": final_beg,
            "explanation_detailed": final_det,
            "suggestion": sugg_val,
            "category": cat_val,
            "confidence": conf_val,
            "explanation_source": source,
            "fallback_reason": fallback_reason,
        }

    # 0. Check for linker error
    if getattr(error, "category", None) == "linker_error" or re.search(r"undefined reference|undefined symbols|symbol\(s\) not found|linker command failed", message, re.IGNORECASE):
        cat = "linker_error"
        conf = 0.95
        what, why, how, sugg = build_dynamic_explanation(cat, message, {}, "", did_you_mean)
        beg = format_error(what, why, how)
        det = beg + f"\n\n--- Detailed Context ---\nCategory: {cat} (Confidence: {conf:.1%})\nLocation: {getattr(error, 'file', '')}"
        return _finalize(cat, conf, sugg, beg, det)

    # 1. Check Common Errors Glossary
    common = lookup_common_error(message)
    if common:
        cat = common["category"]
        conf = common["confidence"]
        sugg = common["suggestion"]
        entities = extract_entities(message)
        ast_phrase = format_ast_context(ast_node, entities)
        what = common["explanation"]
        why = f"A standard language violation occurred{f' {ast_phrase}' if ast_phrase else ''}."
        if did_you_mean:
            why += f" Did you mean '{did_you_mean}'?"
            how = f"Use '{did_you_mean}' instead, or {sugg.lower()}"
        else:
            how = sugg
        beg = format_error(what, why, how)
        det = beg + f"\n\n--- Detailed Context ---\nCategory: {cat} (Confidence: {conf:.1%})\nLocation: {getattr(error, 'file', '')}:{getattr(error, 'line', '')}:{getattr(error, 'column', '')}\nAST Node: {ast_node or 'None'}"
        return _finalize(cat, conf, sugg, beg, det)

    # 2. ML Classification with AST and Symbol Table features
    classifier = get_default_classifier()
    
    # Coarse symbol signal
    sym_signal = "unknown"
    if did_you_mean:
        sym_signal = "typo_near_miss"
    elif cat_attr := getattr(error, "category", None):
        if cat_attr == "name_resolution":
            sym_signal = "completely_undeclared"

    cat, conf = classifier.predict(
        message,
        ast_node=ast_node,
        ast_fallback=ast_fallback,
        symbol_signal=sym_signal,
    )
    cat = cat or "other"

    # Regex fallbacks for edge cases
    if conf < 0.45:
        if re.search(r"expected\s+['`;]", message, re.IGNORECASE):
            cat, conf = "syntax_error", 0.95
        elif re.search(r"was not declared in this scope|use of undeclared identifier", message, re.IGNORECASE):
            cat, conf = "name_resolution", 0.95
        elif re.search(r"cannot convert|invalid conversion", message, re.IGNORECASE):
            cat, conf = "type_error", 0.90

    # 3. Dynamic explanation synthesis
    entities = extract_entities(message)

    # Deterministic standard-library missing_include override:
    # When an undeclared-identifier/type exactly matches a known standard library symbol
    # and the corresponding header is not included, override category to missing_include.
    ident = entities.get("identifier") or entities.get("member")
    if not ident:
        for pat in (
            r"use of undeclared identifier ['‘\"](\w+)['’\"]",
            r"['‘\"](\w+)['’\"]\s+(?:was not declared|has not been declared)",
            r"no template named ['‘\"](\w+)['’\"]",
            r"unknown type name ['‘\"](\w+)['’\"]",
            r"no member named ['‘\"](\w+)['’\"]\s+in\s+namespace\s+['‘\"]std['‘\"]",
        ):
            if m_ident := re.search(pat, message):
                ident = m_ident.group(1)
                break

    if ident and ident in STD_SYMBOL_TO_HEADER:
        req_header = STD_SYMBOL_TO_HEADER[ident]
        source_file = getattr(error, "file", None)
        if not source_file or not is_header_included(source_file, req_header):
            cat = "missing_include"
            conf = 1.0
            entities["header"] = req_header

    ast_phrase = format_ast_context(ast_node, entities)
    what, why, how, suggestion = build_dynamic_explanation(cat, message, entities, ast_phrase, did_you_mean)

    beg = format_error(what, why, how)

    # Build Detailed explanation
    loc_str = f"{getattr(error, 'file', '') or 'unknown'}"
    if getattr(error, "line", None) is not None:
        loc_str += f":line {error.line}"
        if getattr(error, "column", None) is not None:
            loc_str += f", col {error.column}"

    ast_detail = ast_node if ast_node else "Unknown"
    if ast_summary:
        ast_detail += f" ({ast_summary})"
    if ast_fallback:
        ast_detail += " [AST fallback: line proximity]"

    det_lines = [
        beg,
        "",
        "--- Detailed Diagnostic Context ---",
        f"Category: {cat} (Classifier Confidence: {conf:.1%})",
        f"Location: {loc_str}",
        f"AST Node: {ast_detail}",
    ]
    if did_you_mean:
        det_lines.append(f"Symbol Table Suggestion: '{did_you_mean}' (Levenshtein distance <= 2)")
    det = "\n".join(det_lines)

    return _finalize(cat, conf, suggestion, beg, det)


def enrich_error(
    error: Any,
    llm_explain: bool = False,
    config: Optional[dict] = None,
) -> None:
    """Enrich CompilerError or Diagnostic with classification and explanations."""
    if not error:
        return
    res = explain_error(error, mode="beginner", llm_explain=llm_explain, config=config)

    error.explanation = res["explanation"]
    error.explanation_beginner = res["explanation_beginner"]
    error.explanation_detailed = res["explanation_detailed"]
    error.suggestion = res["suggestion"]
    error.category = res["category"]
    error.confidence = res["confidence"]
    error.explanation_source = res.get("explanation_source", "template")
    error.fallback_reason = res.get("fallback_reason")

    risk, reason = analyze_security_risk(error)
    try:
        error.security_risk = risk
        error.risk_reason = reason
    except Exception:
        pass

    if getattr(error, "file", None) and getattr(error, "line", None) and not getattr(error, "context", None):
        try:
            from error_parser import get_source_context
            error.context = get_source_context(error.file, error.line)
        except Exception:
            pass

    error.security_findings = []
    if getattr(error, "file", None):
        try:
            findings = analyze(error.file, [error])
            error.security_findings = [
                finding for finding in findings
                if finding.source == "compiler_diagnostic" or finding.line == error.line
            ]
        except Exception:
            error.security_findings = []
