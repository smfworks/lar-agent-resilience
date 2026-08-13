"""Tool jail: exec argv allowlist, path jail, fetch SSRF denials."""

from pathlib import Path

import pytest

from agent_resilience.tools.builtin import (
    ExecTool,
    FileReadTool,
    FileWriteTool,
    WebFetchTool,
    is_blocked_fetch_url,
    path_is_inside,
)


def test_exec_rejects_python_dash_c():
    tool = ExecTool()
    ok, reason, argv = tool.parse_command("python -c importos")
    assert ok is False
    assert "python" in reason.lower() or "not in the allowed" in reason
    assert argv == []

    quoted = tool.parse_command("python -c 'print(1)'")
    assert quoted[0] is False


def test_exec_rejects_pipes_and_semicolons():
    tool = ExecTool()
    ok_pipe, reason_pipe, _ = tool.parse_command("ls | cat")
    ok_semi, reason_semi, _ = tool.parse_command("ls; rm -rf /")
    assert ok_pipe is False
    assert "metacharacter" in reason_pipe
    assert ok_semi is False
    assert "metacharacter" in reason_semi


def test_exec_rejects_git_and_curl_by_default():
    tool = ExecTool()
    ok_git, _, _ = tool.parse_command("git status")
    ok_curl, _, _ = tool.parse_command("curl https://example.com")
    assert ok_git is False
    assert ok_curl is False


def test_exec_allows_echo_parse():
    tool = ExecTool()
    ok, reason, argv = tool.parse_command("echo hello")
    assert ok is True, reason
    assert argv == ["echo", "hello"]


@pytest.mark.asyncio
async def test_exec_does_not_use_shell():
    tool = ExecTool()
    result = await tool.execute("echo hello; echo pwned")
    assert result.success is False
    assert "Safety check failed" in (result.error or "")


def test_path_jail_rejects_parent_and_prefix_sibling(tmp_path: Path):
    base = tmp_path / "data"
    base.mkdir()
    sibling = tmp_path / "data-evil"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("nope", encoding="utf-8")
    (base / "ok.txt").write_text("yes", encoding="utf-8")

    assert path_is_inside((base / "ok.txt").resolve(), base.resolve())
    assert not path_is_inside((base / ".." / "data-evil" / "secret.txt").resolve(), base.resolve())
    assert not path_is_inside(sibling.resolve(), base.resolve())


@pytest.mark.asyncio
async def test_file_read_rejects_traversal(tmp_path: Path):
    base = tmp_path / "data"
    base.mkdir()
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    tool = FileReadTool(base_path=str(base))
    result = await tool.execute("../outside.txt")
    assert result.success is False
    assert "Access denied" in (result.error or "")


@pytest.mark.asyncio
async def test_file_write_rejects_prefix_sibling(tmp_path: Path):
    base = tmp_path / "data"
    base.mkdir()
    tool = FileWriteTool(base_path=str(base), allow_overwrite=True)
    result = await tool.execute(str(tmp_path / "data-evil" / "x.txt"), "x")
    # Absolute path that resolves outside base is denied.
    if result.success:
        # If the platform joined oddly, still assert the file is not outside.
        written = tmp_path / "data-evil" / "x.txt"
        assert not written.exists()
    else:
        assert "Access denied" in (result.error or "")


@pytest.mark.asyncio
async def test_fetch_rejects_file_and_loopback():
    tool = WebFetchTool()
    file_result = await tool.execute("file:///etc/passwd")
    loop_result = await tool.execute("https://127.0.0.1/")
    http_result = await tool.execute("http://example.com/")
    assert file_result.success is False
    assert loop_result.success is False
    assert http_result.success is False
    blocked, _ = is_blocked_fetch_url("https://127.0.0.1/secret")
    assert blocked is True
