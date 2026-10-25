"""
config_loader.py
────────────────
Loads the centralised config.yaml and provides a typed accessor.
Falls back to hardcoded defaults if the file is missing, so existing
code keeps working without config.yaml present.
"""

from __future__ import annotations

import os
from typing import Any

_CONFIG_CACHE: dict[str, Any] | None = None


def _find_config() -> str | None:
    """Search upward from src/ for config.yaml."""
    start = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(start, "config.yaml")
        if os.path.exists(candidate):
            return candidate
        start = os.path.dirname(start)
    return None


def load_config(*, force_reload: bool = False) -> dict[str, Any]:
    """Load and cache the YAML config. Returns defaults if file is missing."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None and not force_reload:
        return _CONFIG_CACHE

    config_path = _find_config()
    if config_path is None:
        _CONFIG_CACHE = _defaults()
        return _CONFIG_CACHE

    try:
        import yaml
        with open(config_path, "r") as f:
            _CONFIG_CACHE = yaml.safe_load(f) or {}
    except ImportError:
        # PyYAML not installed — fall back to defaults
        _CONFIG_CACHE = _defaults()
    except Exception:
        _CONFIG_CACHE = _defaults()

    return _CONFIG_CACHE


def get(section: str, key: str, default: Any = None) -> Any:
    """Convenience accessor: ``get("pipeline", "max_heal_attempts", 10)``."""
    cfg = load_config()
    return cfg.get(section, {}).get(key, default)


# Alias for backward compatibility
cfg_get = get


def _defaults() -> dict[str, Any]:
    """Hardcoded defaults matching the original source-embedded values."""
    return {
        "pipeline": {
            "max_heal_attempts": 10,
            "context_lines": 2,
            "log_training": False,
            "backup_before_repair": True,
        },
        "compiler": {
            "command": "g++",
            "standard": "c++17",
            "extra_flags": [],
        },
        "security": {
            "dangerous_functions": [
                "gets", "strcpy", "strcat", "sprintf", "scanf",
                "system", "rand", "memcpy", "memmove", "assert", "malloc",
            ],
            "sensitive_keywords": ["key", "token", "password", "secret"],
            "blocked_patterns": {
                "system_calls": [r'\bsystem\s*\(', r'\bexec\s*\(', r'\bpopen\s*\(', r'\bfork\s*\('],
                "assembly": [r'\b__asm__\b', r'\bshellcode\b'],
                "sys_includes": [r'#include\s*[<"]\s*sys/'],
            },
            "overflow_sentinels": ["INT_MAX", "SIZE_MAX", "UINT_MAX", "LONG_MAX", "LLONG_MAX"],
            "size_keywords": ["alloc", "size", "len", "count", "capacity"],
        },
        "classifier": {
            "model_path": "models/error_classifier.pkl",
            "unfixable_categories": ["linker_error", "security_violation"],
        },
        "llm_explainer": {
            "enabled": False,
            "provider": "gemini",
            "model": "gemini-3.1-flash-lite",
            "api_key_env_var": "GEMINI_API_KEY",
            "timeout_seconds": 12.0,
            "max_output_tokens": 150,
        },
    }
