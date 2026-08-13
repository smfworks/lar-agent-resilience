"""Tool protocol and registry for the Local Agent Runtime."""

from abc import ABC, abstractmethod
from typing import Any

import structlog

logger = structlog.get_logger("lar.tools")


class ToolResult:
    """Result of a tool execution."""

    def __init__(self, output: Any, error: str = "", success: bool = True):
        self.output = output
        self.error = error
        self.success = success

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output if self.success else None,
            "error": self.error if not self.success else None,
        }


class Tool(ABC):
    """Base class for agent tools."""

    def __init__(self, name: str, description: str, parameters: dict):
        self.name = name
        self.description = description
        self.parameters = parameters

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters."""

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry of available tools for the agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._logger = structlog.get_logger("lar.tools")

    @property
    def registry(self) -> dict[str, Tool]:
        """Public view of registered tools (used by checkpoint snapshots)."""
        return self._tools

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self._logger.info("tool_registered", name=tool.name)

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found in registry")
        return self._tools[name]

    def list_tools(self) -> list[dict]:
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(self, name: str, **kwargs) -> ToolResult:
        tool = self.get(name)
        self._logger.info("tool_executing", name=name, params=kwargs)
        try:
            result = await tool.execute(**kwargs)
            self._logger.info("tool_executed", name=name, success=result.success)
            return result
        except Exception as e:
            self._logger.error("tool_execution_failed", name=name, error=str(e))
            return ToolResult(output=None, error=str(e), success=False)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


__all__ = ["Tool", "ToolResult", "ToolRegistry"]
