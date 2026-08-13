"""Tests for the agent_resilience public API — __init__.py exports.

Covers: all public names are importable, __version__, __all__ completeness.
"""

from __future__ import annotations

import importlib

import agent_resilience


class TestPublicAPI:
    def test_version(self):
        assert agent_resilience.__version__ == "1.0.0"

    def test_all_exports_importable(self):
        """Every name in __all__ should be importable from the package."""
        for name in agent_resilience.__all__:
            assert hasattr(agent_resilience, name), f"{name} not found in package"

    def test_all_exports_complete(self):
        """__all__ should include all major public classes."""
        expected = {
            "AgentLoop",
            "ConfigManager",
            "RuntimeConfig",
            "SessionIdentityValidator",
            "ValidationResult",
            "ValidationError",
            "CircuitBreaker",
            "CircuitState",
            "CircuitBreakerConfig",
            "CheckpointStore",
            "AgentState",
            "Phase",
            "HealthMonitor",
            "HealthReport",
            "HealthStatus",
            "CheckResult",
            "ModelLifecycle",
            "ModelRecord",
            "LLMBackend",
            "OllamaBackend",
            "FallbackBackend",
            "LLMResponse",
            "Tool",
            "ToolResult",
            "ToolRegistry",
            "MemoryManager",
            "InMemoryProvider",
            "FileMemoryProvider",
            "__version__",
        }
        assert expected.issubset(set(agent_resilience.__all__))

    def test_core_classes_are_classes(self):
        assert isinstance(agent_resilience.AgentLoop, type)
        assert isinstance(agent_resilience.ConfigManager, type)
        assert isinstance(agent_resilience.CircuitBreaker, type)
        assert isinstance(agent_resilience.CheckpointStore, type)
        assert isinstance(agent_resilience.HealthMonitor, type)
        assert isinstance(agent_resilience.ModelLifecycle, type)

    def test_enums_are_enums(self):
        from enum import Enum
        assert issubclass(agent_resilience.CircuitState, Enum)
        assert issubclass(agent_resilience.HealthStatus, Enum)
        assert issubclass(agent_resilience.Phase, Enum)
        assert issubclass(agent_resilience.ValidationResult, Enum)

    def test_tool_classes(self):
        assert isinstance(agent_resilience.Tool, type)
        assert isinstance(agent_resilience.ToolResult, type)
        assert isinstance(agent_resilience.ToolRegistry, type)

    def test_memory_classes(self):
        assert isinstance(agent_resilience.MemoryManager, type)
        assert isinstance(agent_resilience.InMemoryProvider, type)
        assert isinstance(agent_resilience.FileMemoryProvider, type)

    def test_llm_classes(self):
        assert isinstance(agent_resilience.LLMBackend, type)
        assert isinstance(agent_resilience.OllamaBackend, type)
        assert isinstance(agent_resilience.FallbackBackend, type)
        assert isinstance(agent_resilience.LLMResponse, type)

    def test_readme_aliases_import(self):
        from agent_resilience import Agent, Checkpoint, ModelRouter

        assert Agent is agent_resilience.AgentLoop
        assert Checkpoint is agent_resilience.CheckpointStore
        assert ModelRouter is agent_resilience.ModelRouter