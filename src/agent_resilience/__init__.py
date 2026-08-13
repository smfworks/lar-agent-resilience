"""
agent_resilience — Production-grade reference implementation for resilient agent design.

Provides model failover, circuit breakers, checkpoint/resume, identity validation,
health monitoring, and live observability for autonomous agents on Linux.
"""

from agent_resilience.agent import AgentLoop
from agent_resilience.checkpoint import AgentState, CheckpointStore, Phase
from agent_resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from agent_resilience.config import ConfigManager, RuntimeConfig
from agent_resilience.health import CheckResult, HealthMonitor, HealthReport, HealthStatus
from agent_resilience.identity import SessionIdentityValidator, ValidationError, ValidationResult
from agent_resilience.llm import FallbackBackend, LLMBackend, LLMResponse, OllamaBackend
from agent_resilience.memory import FileMemoryProvider, InMemoryProvider, MemoryManager
from agent_resilience.model_lifecycle import ModelLifecycle, ModelRecord
from agent_resilience.router import ModelRouter
from agent_resilience.tools import Tool, ToolRegistry, ToolResult

# README aliases — documented names must import
Agent = AgentLoop
Checkpoint = CheckpointStore

__version__ = "1.0.0"

__all__ = [
    "Agent",
    "AgentLoop",
    "AgentState",
    "CheckResult",
    "Checkpoint",
    "CheckpointStore",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "ConfigManager",
    "FallbackBackend",
    "FileMemoryProvider",
    "HealthMonitor",
    "HealthReport",
    "HealthStatus",
    "InMemoryProvider",
    "LLMBackend",
    "LLMResponse",
    "MemoryManager",
    "ModelLifecycle",
    "ModelRecord",
    "ModelRouter",
    "OllamaBackend",
    "Phase",
    "RuntimeConfig",
    "SessionIdentityValidator",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "ValidationError",
    "ValidationResult",
    "__version__",
]
