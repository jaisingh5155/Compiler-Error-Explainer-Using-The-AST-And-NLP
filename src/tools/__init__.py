"""
src/tools/__init__.py
─────────────────────
Tool interface package.  Exposes five pipeline tools:
  understand, detect, repair, optimize, verify
And their data contracts:
  ProgramModel, Patch, Suggestion, VerifyResult
"""

from diagnostic import ProgramModel, Patch, Suggestion, VerifyResult, Diagnostic
from tools.understand import understand
from tools.detect import detect
from tools.repair import repair
from tools.optimize import optimize
from tools.verify import verify

__all__ = [
    "understand",
    "detect",
    "repair",
    "optimize",
    "verify",
    "ProgramModel",
    "Patch",
    "Suggestion",
    "VerifyResult",
    "Diagnostic",
]
