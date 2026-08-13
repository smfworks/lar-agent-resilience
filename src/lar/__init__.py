"""Compatibility package: `import lar` resolves to `agent_resilience`.

Historical modules imported `lar.config`, `lar.identity`, etc. The
installable package name is `agent_resilience`. This shim keeps both
import paths working after `pip install -e .`.
"""

from __future__ import annotations

import sys

import agent_resilience as _ar
from agent_resilience import *  # noqa: F401,F403

_SUBMODULES = (
    "config",
    "identity",
    "checkpoint",
    "agent",
    "health",
    "circuit_breaker",
    "llm",
    "memory",
    "observatory",
    "observatory_server",
    "model_lifecycle",
    "benchmark",
    "tui",
    "tools",
    "tools.builtin",
)

for _name in _SUBMODULES:
    try:
        _mod = __import__(f"agent_resilience.{_name}", fromlist=["_"])
        sys.modules[f"{__name__}.{_name}"] = _mod
    except Exception:
        continue

__all__ = getattr(_ar, "__all__", [])
__version__ = getattr(_ar, "__version__", "0.0.0")
