"""
agent_resilience — Production-grade reference implementation for resilient agent design.

Provides model failover, circuit breakers, checkpoint/resume, identity validation,
health monitoring, and live observability for autonomous agents on Linux.

Public API:
    AgentLoop            — Core autonomous agent execution loop (OATA cycle)
    ConfigManager        — YAML + env-var configuration management
    RuntimeConfig        — Pydantic configuration model
    SessionIdentityValidator — HMAC-based payload identity validation
    CircuitBreaker       — Foreign-payload contamination protection
    CheckpointStore      — SQLite-backed durable agent state persistence
    HealthMonitor        — Structured health checks and reporting
    ModelLifecycle       — Model availability and deprecation tracking
    ModelRouter          — Pluggable model selection with fallback chain
    Consolidator         — Post-swap consolidation phase (async awakening)
    Observatory          — WebSocket live agent visualizer
    LLMBackend           — Abstract LLM backend interface
    OllamaBackend        — Ollama API backend
    FallbackBackend      — Multi-backend sequential fallback
    ToolRegistry         — Agent tool registry
    Tool                 — Abstract tool base class
    ToolResult           — Tool execution result
"""

from agent_resilience.config import ConfigManager, RuntimeConfig
from agent_resilience.identity import SessionIdentityValidator, ValidationResult, ValidationError
from agent_resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerConfig
from agent_resilience.checkpoint import CheckpointStore, AgentState, Phase
from agent_resilience.health import HealthMonitor, HealthReport, HealthStatus, CheckResult
from agent_resilience.model_lifecycle import ModelLifecycle, ModelRecord
from agent_resilience.llm import LLMBackend, OllamaBackend, FallbackBackend, LLMResponse
from agent_resilience.tools import Tool, ToolResult, ToolRegistry
from agent_resilience.agent import AgentLoop
from agent_resilience.memory import MemoryManager, InMemoryProvider, FileMemoryProvider

__version__ = "1.0.0"

__all__ = [
    # Core
    "AgentLoop",
    "ConfigManager",
    "RuntimeConfig",
    # Identity
    "SessionIdentityValidator",
    "ValidationResult",
    "ValidationError",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerConfig",
    # Checkpoint
    "CheckpointStore",
    "AgentState",
    "Phase",
    # Health
    "HealthMonitor",
    "HealthReport",
    "HealthStatus",
    "CheckResult",
    # Model lifecycle
    "ModelLifecycle",
    "ModelRecord",
    # LLM
    "LLMBackend",
    "OllamaBackend",
    "FallbackBackend",
    "LLMResponse",
    # Tools
    "Tool",
    "ToolResult",
    "ToolRegistry",
    # Memory
    "MemoryManager",
    "InMemoryProvider",
    "FileMemoryProvider",
    # Version
    "__version__",
]