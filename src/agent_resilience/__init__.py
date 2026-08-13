"""agent_resilience — Local Agent Runtime primitives.

Public surface is intentionally small. Import `lar` for the historical
path used inside this repo; new code should import `agent_resilience`.
"""

from __future__ import annotations

__version__ = "0.2.0"

from agent_resilience.checkpoint import AgentState, CheckpointStore, Phase
from agent_resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from agent_resilience.config import ConfigManager, RuntimeConfig
from agent_resilience.identity import SessionIdentityValidator, ValidationResult

try:
    from agent_resilience.agent import AgentLoop
except Exception:  # pragma: no cover - optional heavy imports
    AgentLoop = None  # type: ignore[misc,assignment]

__all__ = [
    "__version__",
    "AgentState",
    "CheckpointStore",
    "Phase",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "ConfigManager",
    "RuntimeConfig",
    "SessionIdentityValidator",
    "ValidationResult",
    "AgentLoop",
]
