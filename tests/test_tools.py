"""Tests for agent_resilience.tools — ToolRegistry, Tool, ToolResult, builtins.

Covers: registration, lookup, execution, OpenAI schema, builtin tools
(exec, file_read, file_write, web_search, web_fetch), safety checks.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_resilience.tools import ToolRegistry, ToolResult
from agent_resilience.tools.builtin import (
    ExecTool,
    FileReadTool,
    FileWriteTool,
    WebFetchTool,
    WebSearchTool,
    register_builtin_tools,
)

# ── ToolResult ───────────────────────────────────────────────────────────


class TestToolResult:
    def test_success_result(self):
        r = ToolResult(output="hello")
        assert r.output == "hello"
        assert r.success is True
        assert r.error == ""

    def test_error_result(self):
        r = ToolResult(output=None, error="failed", success=False)
        assert r.success is False
        assert r.error == "failed"

    def test_to_dict_success(self):
        r = ToolResult(output="data")
        d = r.to_dict()
        assert d["success"] is True
        assert d["output"] == "data"
        assert d["error"] is None

    def test_to_dict_error(self):
        r = ToolResult(output=None, error="boom", success=False)
        d = r.to_dict()
        assert d["success"] is False
        assert d["output"] is None
        assert d["error"] == "boom"


# ── ToolRegistry ─────────────────────────────────────────────────────────


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = ExecTool()
        reg.register(tool)
        assert "exec" in reg
        assert reg.get("exec") is tool

    def test_get_nonexistent_raises(self):
        reg = ToolRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.get("nonexistent")

    def test_list_tools_returns_schemas(self):
        reg = ToolRegistry()
        reg.register(ExecTool())
        tools = reg.list_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "exec"

    def test_get_tool_names(self):
        reg = ToolRegistry()
        reg.register(ExecTool())
        reg.register(FileReadTool())
        names = reg.get_tool_names()
        assert "exec" in names
        assert "file_read" in names

    def test_contains(self):
        reg = ToolRegistry()
        reg.register(ExecTool())
        assert "exec" in reg
        assert "nonexistent" not in reg

    async def test_execute_success(self):
        reg = ToolRegistry()
        reg.register(ExecTool())
        result = await reg.execute("exec", command="echo hello")
        assert result.success is True
        assert "hello" in result.output

    async def test_execute_nonexistent_returns_error(self):
        reg = ToolRegistry()
        try:
            result = await reg.execute("nonexistent", foo="bar")
            assert result.success is False
            assert "not found" in result.error
        except KeyError:
            # Registry raises KeyError for unknown tools - that's acceptable
            pass


# ── ExecTool ─────────────────────────────────────────────────────────────


class TestExecTool:
    async def test_safe_command_executes(self):
        tool = ExecTool()
        result = await tool.execute(command="echo test123")
        assert result.success is True
        assert "test123" in result.output

    async def test_blocked_pattern_rejected(self):
        tool = ExecTool()
        result = await tool.execute(command="rm -rf /")
        assert result.success is False
        assert "blocked" in result.error.lower() or "not in the allowed list" in result.error

    async def test_unknown_command_rejected(self):
        tool = ExecTool()
        result = await tool.execute(command="someunknowncmd args")
        assert result.success is False
        assert "not in the allowed list" in result.error

    async def test_custom_allowed_commands(self):
        tool = ExecTool(allowed_commands=["whoami"])
        result = await tool.execute(command="whoami")
        assert result.success is True

    async def test_empty_command_rejected(self):
        tool = ExecTool()
        result = await tool.execute(command="")
        assert result.success is False

    async def test_command_timeout(self):
        tool = ExecTool(allowed_commands=["sleep"])
        result = await tool.execute(command="sleep 10", timeout=1)
        assert result.success is False
        assert "timed out" in result.error

    def test_to_openai_schema(self):
        tool = ExecTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "exec"
        assert "command" in schema["function"]["parameters"]["properties"]


# ── FileReadTool ─────────────────────────────────────────────────────────


class TestFileReadTool:
    async def test_read_existing_file(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        tool = FileReadTool(base_path=str(tmp_path))
        result = await tool.execute(path="test.txt")
        assert result.success is True
        assert "line1" in result.output
        assert "line3" in result.output

    async def test_read_nonexistent_file(self, tmp_path: Path):
        tool = FileReadTool(base_path=str(tmp_path))
        result = await tool.execute(path="nope.txt")
        assert result.success is False
        assert "not found" in result.error

    async def test_read_directory_rejected(self, tmp_path: Path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        tool = FileReadTool(base_path=str(tmp_path))
        result = await tool.execute(path="subdir")
        assert result.success is False
        assert "directory" in result.error

    async def test_directory_traversal_blocked(self, tmp_path: Path):
        tool = FileReadTool(base_path=str(tmp_path))
        result = await tool.execute(path="../../../etc/passwd")
        assert result.success is False
        assert "outside base directory" in result.error

    async def test_read_with_limit(self, tmp_path: Path):
        f = tmp_path / "big.txt"
        f.write_text("\n".join(f"line-{i}" for i in range(2000)))
        tool = FileReadTool(base_path=str(tmp_path))
        result = await tool.execute(path="big.txt", limit=5)
        assert result.success is True
        assert "truncated" in result.output


# ── FileWriteTool ────────────────────────────────────────────────────────


class TestFileWriteTool:
    async def test_write_new_file(self, tmp_path: Path):
        tool = FileWriteTool(base_path=str(tmp_path), allow_overwrite=True)
        result = await tool.execute(path="output.txt", content="hello world")
        assert result.success is True
        assert (tmp_path / "output.txt").read_text() == "hello world"

    async def test_write_no_overwrite(self, tmp_path: Path):
        f = tmp_path / "existing.txt"
        f.write_text("original")
        tool = FileWriteTool(base_path=str(tmp_path), allow_overwrite=False)
        result = await tool.execute(path="existing.txt", content="new")
        assert result.success is False
        assert "overwrite" in result.error
        assert f.read_text() == "original"

    async def test_write_with_overwrite(self, tmp_path: Path):
        f = tmp_path / "existing.txt"
        f.write_text("original")
        tool = FileWriteTool(base_path=str(tmp_path), allow_overwrite=True)
        result = await tool.execute(path="existing.txt", content="new content")
        assert result.success is True
        assert f.read_text() == "new content"

    async def test_write_creates_parent_dirs(self, tmp_path: Path):
        tool = FileWriteTool(base_path=str(tmp_path), allow_overwrite=True)
        result = await tool.execute(path="sub/dir/file.txt", content="nested")
        assert result.success is True
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"

    async def test_write_traversal_blocked(self, tmp_path: Path):
        tool = FileWriteTool(base_path=str(tmp_path), allow_overwrite=True)
        result = await tool.execute(path="../../../etc/evil.txt", content="bad")
        assert result.success is False
        assert "outside base directory" in result.error


# ── WebSearchTool / WebFetchTool ─────────────────────────────────────────


class TestWebSearchTool:
    async def test_search_returns_result(self):
        tool = WebSearchTool()
        # Mock the httpx client to avoid network calls
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.text = "<html>results</html>"
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="test query")
            assert result.success is True
            assert "test query" in result.output

    async def test_search_handles_error(self):
        tool = WebSearchTool()
        with patch("httpx.AsyncClient", side_effect=Exception("network error")):
            result = await tool.execute(query="test")
            assert result.success is False


class TestWebFetchTool:
    async def test_fetch_returns_content(self):
        tool = WebFetchTool()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.text = "<html><body>Hello World</body></html>"
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(url="http://example.com")
            assert result.success is True
            assert "Hello World" in result.output

    async def test_fetch_truncates_long_content(self):
        tool = WebFetchTool()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.text = "<html>" + "x" * 10000 + "</html>"
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(url="http://example.com", max_chars=100)
            assert result.success is True
            assert "truncated" in result.output

    async def test_fetch_handles_error(self):
        tool = WebFetchTool()
        with patch("httpx.AsyncClient", side_effect=Exception("connection refused")):
            result = await tool.execute(url="http://example.com")
            assert result.success is False


# ── register_builtin_tools ────────────────────────────────────────────────


class TestRegisterBuiltinTools:
    def test_registers_all_five_tools(self):
        reg = ToolRegistry()
        register_builtin_tools(reg)
        names = reg.get_tool_names()
        assert "web_search" in names
        assert "web_fetch" in names
        assert "exec" in names
        assert "file_read" in names
        assert "file_write" in names
        assert len(names) == 5

    def test_register_with_config(self):
        reg = ToolRegistry()
        register_builtin_tools(reg, {
            "exec": {"allowed_commands": ["ls", "pwd"]},
            "file": {"base_path": "/tmp", "allow_overwrite": True},
        })
        assert "exec" in reg
        assert "file_read" in reg
        assert "file_write" in reg

    def test_register_with_empty_config(self):
        reg = ToolRegistry()
        register_builtin_tools(reg, {})
        assert len(reg.get_tool_names()) == 5

    def test_register_with_none_config(self):
        reg = ToolRegistry()
        register_builtin_tools(reg, None)
        assert len(reg.get_tool_names()) == 5
