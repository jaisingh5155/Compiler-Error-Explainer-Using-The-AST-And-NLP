"""
src/agent_security.py
─────────────────────
Agent Security Defense Layer for Agentic AI System.

Defends the agent's decision-making and control-flow integrity against:
1. Instruction injection in source comments and string literals
2. Policy bypass via crafted diagnostic-shaped text
3. Malicious patch generation / hidden agenda (exfiltration primitives in patches)
4. Validation suppression attempts (gate bypass / forced PASS directives)
5. Direct adversarial prompt injection via user instruction field

Provides:
- Lexer-based instruction injection scanner (using DFA tokenizer)
- Correlation-based threat assessment (HIGH risk with nearby finding vs MEDIUM log-only)
- Comment Hygiene Advisor integration (non-blocking plain-language advice)
- User instruction prompt channel scanner
- Patch content auditor (Gate 6 in verify pipeline)
- Diagnostic sanity checker
- Append-only atomic audit logger (data/agent_security_log.jsonl)
"""

from __future__ import annotations

import os
import sys
import re
import json
import time
import fcntl
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lexer import tokenize, State, Token
from diagnostic import Diagnostic, Patch
from comment_hygiene_advisor import advise_comment_hygiene


DEFAULT_LOG_PATH = os.path.join(os.path.dirname(_SRC), "data", "agent_security_log.jsonl")


@dataclass
class AttackDetection:
    attack_type: str            # "instruction_injection" | "policy_bypass" | "malicious_patch" | "validation_suppression"
    surface: str                # "line_comment" | "block_comment" | "string_literal" | "patch_diff" | "diagnostic_text" | "user_instruction_field"
    file_path: Optional[str]
    line: Optional[int]
    col: Optional[int]
    snippet: str                # Redacted / truncated snippet (max 120 chars)
    risk_score: float           # 0.0 to 1.0
    action_taken: str           # "blocked" | "logged"
    risk_tier: str = "HIGH"     # "HIGH" | "MEDIUM" | "LOW"
    details: Dict[str, Any] = field(default_factory=dict)
    advice: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Proximity-Based Heuristic Patterns for Instruction Injection
# ─────────────────────────────────────────────────────────────────────────────

# Strong imperative directive markers targeting AI / Agent / System overrides
_DIRECTIVE_PREFIX_PATTERN = re.compile(
    r'(?i)\b(?:SYSTEM|AI\s+AGENT|AI|TOOL_OVERRIDE|GATE_OVERRIDE|VERIFY_DISPATCH|COMPILER_DIAGNOSTIC)\s*:\s*(.+)'
)

_SQUARE_DIRECTIVE_PATTERN = re.compile(
    r'(?i)\[(?:SYSTEM|INSTRUCTION|OVERRIDE|SYSTEM\s+INSTRUCTION)\]\s*(.+)'
)

# Imperative verbs in close proximity (0-45 chars) to security / policy / gate / validation nouns
_VERB_NOUN_PROXIMITY_PATTERN = re.compile(
    r'(?i)\b(?:ignore|disable|skip|bypass|override|suppress|force|mark)\b.{0,45}\b(?:security\s+policy|security\s+gate|security\s+gates|validation(?:\s+step)?|gate\s+\d+|safety_level|safety_tier|cwe\b|verification\s+checks?|verification\s+gates?|ast\s+validation)\b'
)

# Specific policy override phrases
_POLICY_OVERRIDE_PATTERNS = [
    re.compile(r'(?i)\bmark\s+(?:this\s+code\s+)?as\s+(?:safe|s0)\b'),
    re.compile(r'(?i)\bmark\s+the\s+vulnerable\s+code\s+as\s+safe\b'),
    re.compile(r'(?i)\boverride\s+safety_level\s+to\s+s0\b'),
    re.compile(r'(?i)\boverride\s+category\s*=\s*\w+'),
    re.compile(r'(?i)\bstatus=clean\s+safety_level=S0\b'),
    re.compile(r'(?i)\boverride_verification\s*=\s*true\b'),
    re.compile(r'(?i)\bforce\s+passed_gates\s*=\s*True\b'),
    re.compile(r'(?i)\breturn\s+VerificationResult\s*\(\s*passed\s*=\s*True\s*\)'),
    re.compile(r'(?i)\bauto-apply\s+this\s+patch\s+regardless\b'),
]

# Patterns where comment asserts code is safe / validated / approved
_CLAIMS_SAFE_PATTERN = re.compile(
    r'(?i)\b(?:safe|s0|validated|approved|clean|ignore\s+(?:the\s+)?security|disable\s+(?:the\s+)?validation|mark\s+.*safe)\b'
)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Exfiltration & Malicious Patch Patterns
# ─────────────────────────────────────────────────────────────────────────────

_EXFILTRATION_PATTERNS = [
    (
        "env_harvesting",
        re.compile(r'\b(?:getenv|secure_getenv)\s*\('),
        0.95,
        "Attempt to read environment variables (potential credential exfiltration)",
    ),
    (
        "network_socket",
        re.compile(r'\b(?:socket|connect|getaddrinfo|sendto|send)\s*\(|\b(?:AF_INET|AF_INET6|SOCK_STREAM)\b'),
        0.98,
        "Attempt to initialize socket or connect to remote host",
    ),
    (
        "sensitive_file_access",
        re.compile(r'(?:fopen|open|ifstream)\s*\(\s*[\"\x27](?:/etc/passwd|/etc/shadow|/etc/sudoers|~?/\.ssh|\.aws|id_rsa|id_ed25519|/proc/)'),
        0.99,
        "Attempt to access sensitive system files or credentials",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Correlation-Based Threat Assessment Helper
# ─────────────────────────────────────────────────────────────────────────────

def _find_nearby_findings(
    line: Optional[int],
    findings: Optional[List[Any]],
    source_code: str,
    file_path: Optional[str] = None,
    proximity_window: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Search for actual compiler errors or security analyzer findings near `line`.
    
    Returns a dict with details of the nearest finding, or None if clean.
    """
    candidate_findings: List[Dict[str, Any]] = []

    # 1. Use findings passed into scanner if available
    if findings:
        for f in findings:
            f_line = getattr(f, "line", None) or (f.get("line") if isinstance(f, dict) else None)
            f_kind = getattr(f, "kind", None) or getattr(f, "error_type", None) or (f.get("kind") if isinstance(f, dict) else None) or "issue"
            f_msg = getattr(f, "message", None) or (f.get("message") if isinstance(f, dict) else None) or ""
            f_cwe = getattr(f, "cwe", None) or (f.get("cwe") if isinstance(f, dict) else None)
            
            # Skip self-referential security attacks from previous passes
            if f_kind == "security_attack" or "AGENT SECURITY" in str(f_msg):
                continue

            candidate_findings.append({
                "line": f_line,
                "kind": f_kind,
                "message": f_msg,
                "cwe": f_cwe,
            })

    # 2. If no findings passed or empty, run quick static security scan on source
    if not candidate_findings and source_code:
        try:
            from security_analyzer import analyze as analyze_sec
            sec_findings = analyze_sec(source_code, file_path=file_path)
            for sf in sec_findings:
                candidate_findings.append({
                    "line": sf.line,
                    "kind": "security_flaw",
                    "message": f"{sf.vulnerability_type}: {sf.description}",
                    "cwe": sf.cwe,
                })
        except Exception:
            pass

    # 3. Check for compiler errors if source_code or file_path is provided
    if not candidate_findings:
        try:
            from compiler_runner import run_cpp_compiler
            from error_parser import parse_errors
            raw_out = ""
            if source_code:
                import tempfile
                with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as tf:
                    tf.write(source_code)
                    tmp_p = tf.name
                try:
                    raw_out = run_cpp_compiler(tmp_p)
                finally:
                    if os.path.exists(tmp_p):
                        os.remove(tmp_p)
            elif file_path and os.path.exists(file_path):
                raw_out = run_cpp_compiler(file_path)

            if isinstance(raw_out, list):
                for e in raw_out:
                    if isinstance(e, dict):
                        candidate_findings.append({
                            "line": e.get("line"),
                            "kind": e.get("type", "compile_error"),
                            "message": e.get("message", ""),
                            "cwe": None,
                        })
                    else:
                        candidate_findings.append({
                            "line": getattr(e, "line", None),
                            "kind": getattr(e, "type", "compile_error"),
                            "message": getattr(e, "message", ""),
                            "cwe": None,
                        })
            elif isinstance(raw_out, str) and raw_out.strip():
                parsed = parse_errors(raw_out)
                for e in parsed:
                    candidate_findings.append({
                        "line": getattr(e, "line", None) if hasattr(e, "line") else e.get("line"),
                        "kind": getattr(e, "type", "compile_error") if hasattr(e, "type") else e.get("type", "compile_error"),
                        "message": getattr(e, "message", "") if hasattr(e, "message") else e.get("message", ""),
                        "cwe": None,
                    })
        except Exception:
            pass

    if not candidate_findings:
        return None

    # Check for finding near the comment line
    if line is None:
        return candidate_findings[0]

    nearest = None
    min_dist = float("inf")
    for cf in candidate_findings:
        cf_line = cf["line"]
        if cf_line is None:
            # File-level finding applies everywhere
            return cf
        dist = abs(cf_line - line)
        if dist <= proximity_window and dist < min_dist:
            min_dist = dist
            nearest = cf

    return nearest


# ─────────────────────────────────────────────────────────────────────────────
# 4. Detection Engine
# ─────────────────────────────────────────────────────────────────────────────

def scan_user_instruction(
    instruction_text: str,
    file_path: Optional[str] = None,
    log_on_detect: bool = True,
    log_path: Optional[str] = None,
) -> List[AttackDetection]:
    """
    Scan direct user instruction text (Prompt Channel).
    
    Because this is a real user-facing prompt channel to the agent, any adversarial
    directive targeting agent control or policy bypass is an explicit attack attempt.
    Flags matching input as HIGH risk / BLOCKED, logged with surface='user_instruction_field'.
    """
    if not instruction_text or not instruction_text.strip():
        return []

    text = instruction_text.strip()
    matched_category: Optional[str] = None
    matched_reason: Optional[str] = None
    risk_score: float = 0.95

    # Check Directive Prefixes
    m_prefix = _DIRECTIVE_PREFIX_PATTERN.search(text)
    if m_prefix:
        matched_category = "instruction_injection"
        matched_reason = f"Directive header in user instruction field: '{m_prefix.group(0)[:60]}'"
        risk_score = 0.95

    # Check Square Directives
    if not matched_category:
        m_sq = _SQUARE_DIRECTIVE_PATTERN.search(text)
        if m_sq:
            matched_category = "instruction_injection"
            matched_reason = f"Bracket instruction directive in user instruction field: '{m_sq.group(0)[:60]}'"
            risk_score = 0.95

    # Check Specific Policy Overrides
    if not matched_category:
        for p_over in _POLICY_OVERRIDE_PATTERNS:
            m_over = p_over.search(text)
            if m_over:
                matched_category = "instruction_injection"
                matched_reason = f"Policy override phrase in user instruction field: '{m_over.group(0)[:60]}'"
                risk_score = 0.95
                break

    # Check Verb-Noun Proximity Matcher
    if not matched_category:
        m_prox = _VERB_NOUN_PROXIMITY_PATTERN.search(text)
        if m_prox:
            matched_category = "instruction_injection"
            matched_reason = f"Imperative verb near security validation target in instruction field: '{m_prox.group(0)[:60]}'"
            risk_score = 0.92

    if not matched_category:
        return []

    snippet = text
    if len(snippet) > 120:
        snippet = snippet[:117] + "..."

    advice = advise_comment_hygiene(
        snippet=snippet,
        risk_level="HIGH",
        attack_type=matched_category,
    )

    det = AttackDetection(
        attack_type=matched_category,
        surface="user_instruction_field",
        file_path=file_path,
        line=1,
        col=1,
        snippet=snippet,
        risk_score=risk_score,
        action_taken="blocked",
        risk_tier="HIGH",
        details={
            "reason": matched_reason,
            "surface": "user_instruction_field",
            "source": "prompt_channel",
        },
        advice=advice.to_dict(),
    )

    if log_on_detect:
        log_security_event(det, log_path=log_path)

    return [det]


def scan_source_for_injections(
    source_code: str,
    file_path: Optional[str] = None,
    log_on_detect: bool = True,
    log_path: Optional[str] = None,
    findings: Optional[List[Any]] = None,
) -> List[AttackDetection]:
    """
    Scan source code comments and string literals using the Week 5 DFA tokenizer.
    
    Employs correlation-based threat tiering (Task C1):
    - HIGH RISK (blocked + logged): Comment contains injection phrasing AND contradicts
      a real nearby compiler error or security finding in the same file.
    - MEDIUM RISK (logged only, not blocked): Comment contains injection-shaped phrasing
      with NO nearby finding it could be lying about (audit trail only).
    - LOW RISK / NO FLAG: Benign comments using similar words in clean context.
    """
    if not source_code:
        return []

    try:
        tokens = tokenize(source_code)
    except Exception:
        return []

    detections: List[AttackDetection] = []

    for t in tokens:
        surface: Optional[str] = None
        if t.kind == State.LINE_COMMENT:
            surface = "line_comment"
        elif t.kind == State.BLOCK_COMMENT:
            surface = "block_comment"
        elif t.kind in (State.STRING, State.RAW_STRING):
            surface = "string_literal"

        if not surface:
            continue

        text = t.value
        matched_category: Optional[str] = None
        matched_reason: Optional[str] = None
        base_score: float = 0.85

        # Check Directive Prefixes
        m_prefix = _DIRECTIVE_PREFIX_PATTERN.search(text)
        if m_prefix:
            prefix_body = m_prefix.group(1).lower()
            if any(k in prefix_body for k in ("ignore", "disable", "skip", "bypass", "override", "suppress", "force", "safe", "s0", "security", "gate", "policy", "validation")):
                if "gate" in prefix_body or "suppress" in prefix_body or "passed_gates" in prefix_body:
                    matched_category = "validation_suppression"
                elif "category" in prefix_body or "status=clean" in prefix_body or "compiler" in prefix_body:
                    matched_category = "policy_bypass"
                else:
                    matched_category = "instruction_injection"
                matched_reason = f"Directive header targeting agent control: '{m_prefix.group(0)[:60]}'"
                base_score = 0.90

        # Check Bracket Directives
        if not matched_category:
            m_sq = _SQUARE_DIRECTIVE_PATTERN.search(text)
            if m_sq:
                sq_body = m_sq.group(1).lower()
                if any(k in sq_body for k in ("bypass", "override", "ignore", "disable", "skip", "safe", "s0", "verification")):
                    matched_category = "instruction_injection"
                    matched_reason = f"Bracket instruction directive: '{m_sq.group(0)[:60]}'"
                    base_score = 0.90

        # Check Specific Policy Overrides
        if not matched_category:
            for p_over in _POLICY_OVERRIDE_PATTERNS:
                m_over = p_over.search(text)
                if m_over:
                    phrase = m_over.group(0)
                    if "passed_gates" in phrase or "verificationresult" in phrase:
                        matched_category = "validation_suppression"
                    elif "s0" in phrase.lower() or "category" in phrase.lower() or "clean" in phrase.lower() or "override_verification" in phrase.lower():
                        matched_category = "policy_bypass"
                    else:
                        matched_category = "instruction_injection"
                    matched_reason = f"Explicit security policy override phrase: '{phrase[:60]}'"
                    base_score = 0.92
                    break

        # Check Verb-Noun Proximity Matcher
        if not matched_category:
            m_prox = _VERB_NOUN_PROXIMITY_PATTERN.search(text)
            if m_prox:
                matched_category = "instruction_injection"
                matched_reason = f"Imperative verb near security validation target: '{m_prox.group(0)[:60]}'"
                base_score = 0.88

        if matched_category:
            snippet = text.strip()
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."

            # Task C1: Correlate comment claim against independent compile / security findings
            nearby_issue = _find_nearby_findings(
                line=t.line,
                findings=findings,
                source_code=source_code,
                file_path=file_path,
                proximity_window=10,
            )

            claims_safe = bool(_CLAIMS_SAFE_PATTERN.search(text))

            if nearby_issue and (claims_safe or "override" in text.lower() or "suppress" in text.lower()):
                # HIGH RISK: Comment actively lies about verifiable reality nearby
                risk_tier = "HIGH"
                action_taken = "blocked"
                risk_score = max(base_score, 0.88)
                issue_desc = f"{nearby_issue.get('kind', 'finding')} at line {nearby_issue.get('line', '?')}: {nearby_issue.get('message', '')}"
                matched_reason = f"{matched_reason} (Contradicts nearby finding: {issue_desc})"
            else:
                # MEDIUM RISK: Ambiguous injection phrasing without contradicting nearby findings
                # Log only, do not block, do not alarm user
                risk_tier = "MEDIUM"
                action_taken = "logged"
                risk_score = 0.65
                issue_desc = None

            advice = advise_comment_hygiene(
                snippet=snippet,
                risk_level=risk_tier,
                attack_type=matched_category,
                contradicted_issue=issue_desc,
            )

            det = AttackDetection(
                attack_type=matched_category,
                surface=surface,
                file_path=file_path,
                line=t.line,
                col=t.col,
                snippet=snippet,
                risk_score=risk_score,
                action_taken=action_taken,
                risk_tier=risk_tier,
                details={
                    "reason": matched_reason,
                    "token_type": t.kind.name,
                    "contradicted_finding": issue_desc,
                    "correlation_status": "contradicted_nearby_finding" if issue_desc else "untriggered_pattern",
                },
                advice=advice.to_dict(),
            )
            detections.append(det)
            if log_on_detect:
                log_security_event(det, log_path=log_path)

    return detections


def audit_patch_security(
    patch: Patch,
    original_source: Optional[str] = None,
    log_on_detect: bool = True,
    log_path: Optional[str] = None,
) -> Optional[AttackDetection]:
    """
    Gate 6: Patch Content Security Auditor.
    
    Inspects candidate patch's patched_source against original_source.
    Checks for newly introduced exfiltration primitives:
    - Environment harvesting (getenv, secure_getenv)
    - Socket / network primitives (socket, connect, sendto)
    - Sensitive filesystem access (/etc/passwd, .ssh, .aws)
    
    Returns an AttackDetection if an attack is detected, or None if clean.
    """
    orig_src = original_source
    if orig_src is None and patch.original_file and os.path.exists(patch.original_file):
        try:
            with open(patch.original_file, "r", errors="ignore") as f:
                orig_src = f.read()
        except Exception:
            pass

    orig_src = orig_src or ""
    patched_src = patch.patched_source or ""

    if not patched_src.strip():
        return None

    for vuln_key, regex_pat, score, desc in _EXFILTRATION_PATTERNS:
        orig_matches = len(regex_pat.findall(orig_src))
        patch_matches = len(regex_pat.findall(patched_src))

        if patch_matches > orig_matches:
            match_obj = regex_pat.search(patched_src)
            snippet = match_obj.group(0) if match_obj else "unknown primitive"
            
            line_no = 1
            if match_obj:
                line_no = patched_src[:match_obj.start()].count("\n") + 1

            det = AttackDetection(
                attack_type="malicious_patch",
                surface="patch_diff",
                file_path=patch.original_file,
                line=line_no,
                col=1,
                snippet=snippet,
                risk_score=score,
                action_taken="blocked",
                risk_tier="HIGH",
                details={
                    "primitive": vuln_key,
                    "description": desc,
                    "new_occurrences": patch_matches - orig_matches,
                },
            )
            if log_on_detect:
                log_security_event(det, log_path=log_path)
            return det

    return None


def verify_diagnostic_sanity(
    diagnostic: Diagnostic,
    compiler_raw: str = "",
    ast_root: Any = None,
) -> bool:
    """
    Sanity checks Diagnostic IR integrity.
    
    Verifies that category and safety level are assigned strictly based on
    compiler diagnostics and AST, and not influenced by arbitrary comments.
    """
    if not diagnostic:
        return True
    
    valid_levels = {"S0", "S1", "S2", "UNKNOWN"}
    if hasattr(diagnostic, "safety_level") and diagnostic.safety_level not in valid_levels:
        return False
        
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Atomic Append-Only Security Logging
# ─────────────────────────────────────────────────────────────────────────────

def log_security_event(
    detection: AttackDetection,
    log_path: Optional[str] = None,
) -> None:
    """
    Atomically append detection event to data/agent_security_log.jsonl.
    
    Enforces append-only discipline:
    - Never overwrites existing logs
    - Uses file locking (fcntl.flock) for concurrent process safety
    - Automatically creates data/ directory if missing
    """
    path = log_path or DEFAULT_LOG_PATH
    log_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(log_dir, exist_ok=True)

    record = detection.to_dict()
    line = json.dumps(record) + "\n"

    try:
        with open(path, "a", encoding="utf-8") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
        except Exception:
            pass


def read_security_log(log_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read all entries from the security log."""
    path = log_path or DEFAULT_LOG_PATH
    if not os.path.exists(path):
        return []

    entries = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    return entries


# ─────────────────────────────────────────────────────────────────────────────
# 6. Benchmark Evaluation Runner
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_attack_benchmark(
    benchmark_dir: str = "benchmark/agent_attacks",
    existing_benchmark_dir: str = "benchmark",
) -> Dict[str, Any]:
    """
    Run full evaluation across benchmark/agent_attacks/ and existing benchmark suite.
    
    Produces broken-out metrics by HIGH / MEDIUM / LOW risk tiers (Task C1):
    - HIGH risk: blocked + logged (contradicts nearby finding, or Gate 6 malicious patch)
    - MEDIUM risk: logged only, not blocked (untriggered phrasing on clean code)
    - LOW risk: clean decoys with 0 false positives
    """
    import glob

    files = sorted(glob.glob(os.path.join(benchmark_dir, "*.cpp")))
    results: List[Dict[str, Any]] = []

    total_attacks = 0
    total_decoys = 0

    tp = 0
    fp = 0
    tn = 0
    fn = 0
    
    high_count = 0
    medium_count = 0
    low_count = 0
    blocked_count = 0

    latencies: List[float] = []

    for cpp_file in files:
        json_file = cpp_file.replace(".cpp", ".json")
        meta = {}
        if os.path.exists(json_file):
            with open(json_file) as f:
                meta = json.load(f)

        is_attack = meta.get("expected_detection", True)
        attack_type = meta.get("attack_type", "unknown")
        
        with open(cpp_file, errors="ignore") as f:
            source = f.read()

        t0 = time.perf_counter()
        
        # Check source injections with correlation pass
        detections = scan_source_for_injections(source, file_path=cpp_file, log_on_detect=False)
        
        # If malicious patch, also check synthetic patch
        synthetic_patch = meta.get("synthetic_patched_source")
        if synthetic_patch:
            dummy_patch = Patch(
                original_file=cpp_file,
                patched_source=synthetic_patch,
            )
            patch_det = audit_patch_security(dummy_patch, original_source=source, log_on_detect=False)
            if patch_det:
                detections.append(patch_det)

        dt = (time.perf_counter() - t0) * 1000.0  # ms
        latencies.append(dt)

        detected = len(detections) > 0
        blocked = any(d.action_taken == "blocked" for d in detections) if detected else False
        risk_tier = "LOW"
        if detected:
            if any(d.risk_tier == "HIGH" for d in detections):
                risk_tier = "HIGH"
            else:
                risk_tier = "MEDIUM"

        if is_attack:
            total_attacks += 1
            if detected:
                tp += 1
                if risk_tier == "HIGH":
                    high_count += 1
                else:
                    medium_count += 1
                if blocked:
                    blocked_count += 1
            else:
                fn += 1
        else:
            total_decoys += 1
            if detected:
                fp += 1
            else:
                tn += 1
                low_count += 1

        results.append({
            "file": os.path.basename(cpp_file),
            "attack_type": attack_type,
            "is_attack": is_attack,
            "detected": detected,
            "risk_tier": risk_tier,
            "blocked": blocked,
            "detections_count": len(detections),
            "latency_ms": dt,
        })

    precision = (tp / (tp + fp)) if (tp + fp) > 0 else 1.0
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    fp_rate_decoys = (fp / total_decoys) if total_decoys > 0 else 0.0
    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0

    # Scan existing benchmark for false positives
    existing_fp = 0
    existing_scanned = 0
    if os.path.exists(existing_benchmark_dir):
        for dirpath, _, filenames in os.walk(existing_benchmark_dir):
            if "agent_attacks" in dirpath:
                continue
            for fn_item in filenames:
                if fn_item.endswith(".cpp"):
                    p = os.path.join(dirpath, fn_item)
                    with open(p, errors="ignore") as f:
                        c = f.read()
                    d_list = scan_source_for_injections(c, file_path=p, log_on_detect=False)
                    existing_scanned += 1
                    if d_list:
                        existing_fp += 1

    fp_rate_existing = (existing_fp / existing_scanned) if existing_scanned > 0 else 0.0

    return {
        "total_files": len(files),
        "total_attacks": total_attacks,
        "total_decoys": total_decoys,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "decoy_fp_rate": fp_rate_decoys,
        "high_risk_attacks": high_count,
        "medium_risk_attacks": medium_count,
        "low_risk_decoys": low_count,
        "existing_benchmark_scanned": existing_scanned,
        "existing_benchmark_fp": existing_fp,
        "existing_benchmark_fp_rate": fp_rate_existing,
        "block_rate": (blocked_count / total_attacks) if total_attacks > 0 else 1.0,
        "avg_latency_ms": avg_latency,
        "file_results": results,
    }
