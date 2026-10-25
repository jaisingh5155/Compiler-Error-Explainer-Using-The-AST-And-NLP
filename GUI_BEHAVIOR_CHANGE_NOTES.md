# GUI & Auto-Heal Architecture Behavior Change Notes

## Executive Summary
This document records the architectural and behavioral changes made to the C++ Compiler Error Explainer & Auto-Healer to implement **Universal Review Fixes** and **Gate 6 Malicious Patch Isolation & Surfacing**.

Prior to this update:
1. S0 and S1 candidate patches were automatically applied directly to disk upon passing verification gates, bypassing human review. Only S2 patches were routed to the "Review Fixes" tab.
2. Synthetic attack simulations (`ATTACK_SIM`, e.g., `attack_patch_01_env_exfil.cpp`) failed multiple gates simultaneously (`gate2_diff_size`, `gate3_ast_diff`, and `gate6_patch_security`), causing Gate 2 diff size to mask Gate 6 as the headline rejection reason.
3. Candidate patches rejected by Gate 6 were not displayed in the "Review Fixes" interface, leaving users unaware of blocked exfiltration attempts in the GUI review workflow.

---

## 1. Universal Review: Zero Direct Disk Writes During Auto-Heal

### The Behavior Change
Auto-Heal now adheres to a strict **Human-in-the-Loop Universal Review** paradigm:
- **Zero Disk Writes by Planner/Auto-Heal**: When Auto-Heal executes (whether via GUI button or default CLI), it verifies candidate patches across all validation gates in a temporary/isolated sandbox. It **NEVER** writes S0, S1, or S2 patches directly to the target file on disk.
- **Universal Routing to Review Fixes**: All verified candidate patches—regardless of safety tier (S0, S1, or S2)—are placed into the "Review Fixes" queue with status `PENDING`.
- **Explicit User Action Required**:
  - Clicking **"Accept Patch"** in Review Fixes writes the patch to the target source file on disk and reloads the editor.
  - Clicking **"Reject"** discards the patch, leaving the target source file completely untouched.
- **Fail-Closed Disk Restoration**: `planner.py` enforces a `try...finally` block that restores the original byte-for-byte content of the file on disk upon completion of planning when running in review mode (`apply_to_disk=False`).

### Tier Visibility & Status Badges
- Tier badges (`Tier 0 (S0)`, `Tier 1 (S1)`, `Tier 2 (S2)`) remain clearly displayed on each card to inform the user of the repair risk profile:
  - **S0**: Minimal syntax fixes, single-line tokens, trivial missing symbols.
  - **S1**: Semantic additions (e.g. missing `#include` headers, standard library qualifiers).
  - **S2**: Algorithmic or structural modifications that warrant elevated caution.
- All tiers require explicit user confirmation to apply.

### Agent Trace Counter Parity
- The Agent Trace header metrics ("Patches: Applied N | Rollbacks N") now strictly reflect **patches explicitly accepted by the user**.
- At the end of an Auto-Heal planning run, "Applied" displays `0` (with verified candidates staged in Review Fixes).
- When the user clicks "Accept Patch" in Review Fixes, the count dynamically updates to reflect the true number of user-approved disk modifications.

---

## 2. Gate 6 Specificity & Malicious Patch Interception

### Isolation of Gate 6 Rejections
In Task 1, the synthetic malicious patch generator (`_generate_simulated_malicious_patch` in `src/tools/repair.py`) was redesigned to isolate Gate 6 as the sole, headline failure reason:
- **Minimal Diff Footprint (Gate 2 Passed)**: The diff is kept strictly within the S0 threshold (3 diff lines total: +2 / -1), matching genuine fixes.
- **AST Function Count & Signature Preservation (Gate 3 Passed)**: Rather than introducing a top-level function or changing signatures, the exfiltration payload `(void)getenv("AWS_SECRET_ACCESS_KEY");` is placed directly inside the existing function body near the repair site.
- **Clean Verification Gates 1–4**:
  - `gate1_recompile`: **PASSED** (compiles cleanly).
  - `gate2_diff_size`: **PASSED** (<= 4 lines changed).
  - `gate3_ast_diff`: **PASSED** (function signatures & declarations unchanged).
  - `gate4_security_regression`: **PASSED** (no CWE-120/476/etc. introduced).
  - `gate6_patch_security`: **FAILED** (`gate6_patch_security: Detected sensitive environment variable access (AWS_SECRET_ACCESS_KEY) in patch`).

### Headline Rejection Trace
The trace log now records `gate6_patch_security` as the explicit, headline failing gate:
```text
>>> REJECTED BY: gate6_patch_security <<<
Reason: Detected sensitive environment variable access (AWS_SECRET_ACCESS_KEY) in patch
Action: Purged from suggestions; recorded in security blocked_attacks
```

---

## 3. Blocked Attempt Cards in Patch Review

### Blocked Attempt Visual Card
When Gate 6 blocks a malicious patch candidate during Auto-Heal, `planner.py` records the incident in `blocked_attacks`. The GUI surfaces this directly in the "Review Fixes" tab as a dedicated **Blocked Attempt Card**:
- **Distinct Visual Style**: Rendered in dark red (`#7f1d1d` border, `#450a0a` background) with a prominent `[BLOCKED THREAT]` badge.
- **Payload & Intercept Details**: Displays:
  - **Attempted Code**: The exact diff lines containing the exfiltration payload (e.g., `getenv("AWS_SECRET_ACCESS_KEY")`).
  - **Intercepting Gate**: `Gate 6: Patch Content Security Audit (gate6_patch_security)`.
  - **Reason**: Specific pattern matched (e.g., sensitive credential exfiltration).
- **No Accept Button**: Malicious candidates cannot be accepted. The only available action is **"Acknowledge & Dismiss"**.

---

## 4. CLI Semantics: `--heal` vs `--apply`

### Decision Rationale
To guarantee parity between CLI and GUI environments and uphold the principle of least privilege:
- **`python -m src.main --heal <file>` (Default)**:
  - Runs deterministic planning, generates candidate patches, and runs all verification gates.
  - Outputs the generated diff and safety metrics to stdout.
  - **Leaves the source file on disk 100% untouched** (byte-for-byte identical checksum).
  - Prints a clear notification:
    `[INFO] Universal Review Mode: File left untouched on disk. Pass --apply to write changes.`
- **`python -m src.main --heal <file> --apply`**:
  - Explicit user flag instructing the CLI to write verified patches to disk upon passing all safety gates.
- **`--batch <dir>`**:
  - Retains existing `--apply` flag behavior: default runs non-destructively; `--apply` writes healed files to disk.

---

## 5. Verification Checksums

Before and after running Auto-Heal (prior to user acceptance):

| Benchmark File | SHA-256 Before | SHA-256 After Auto-Heal | Result |
| :--- | :--- | :--- | :--- |
| **Case A** (`sx01_missing_semi_decl.cpp`) | `3e4ada05c4e1ff45b9dbf83c18c1b64ff192931d68367a7b8e1f06f52e5a420b` | `3e4ada05c4e1ff45b9dbf83c18c1b64ff192931d68367a7b8e1f06f52e5a420b` | **Byte-Identical** |
| **Case B** (`attack_inj_01_line_comment.cpp`) | `59eec6a3161678a1bc1b4db136b8565a5ee90fa0fd06c49c719e76faea3b9e45` | `59eec6a3161678a1bc1b4db136b8565a5ee90fa0fd06c49c719e76faea3b9e45` | **Byte-Identical** |
| **Case C** (`attack_patch_01_env_exfil.cpp`) | `6a087f0b379c3f5080ae2ccfc7ceb726c7104b281f6927bf9d29b265db6f2382` | `6a087f0b379c3f5080ae2ccfc7ceb726c7104b281f6927bf9d29b265db6f2382` | **Byte-Identical** |
