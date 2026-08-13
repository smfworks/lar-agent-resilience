"""agent_resilience — toolkit for agents that survive model death."""

from agent_resilience.agent import Agent, AgentLoop
from agent_resilience.checkpoint import AgentState, Checkpoint, CheckpointStore, Phase
from agent_resilience.circuit_breaker import CircuitBreaker, ModelCircuitBreaker
from agent_resilience.identity import SessionIdentityValidator, ValidationResult
from agent_resilience.llm import FallbackBackend, LLMBackend, LLMResponse, OllamaBackend
from agent_resilience.router import Consolidator, ModelConfig, ModelRouter, SwapEvent
from agent_resilience.tools import Tool, ToolRegistry, ToolResult

__version__ = "0.2.0"

__all__ = [
    "Agent",
    "AgentLoop",
    "AgentState",
    "Checkpoint",
    "CheckpointStore",
    "CircuitBreaker",
    "Consolidator",
    "FallbackBackend",
    "LLMBackend",
    "LLMResponse",
    "ModelCircuitBreaker",
    "ModelConfig",
    "ModelRouter",
    "OllamaBackend",
    "Phase",
    "SessionIdentityValidator",
    "SwapEvent",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "ValidationResult",
    "__version__",
]
