"""Oppositional hardening tests — leftovers that survived v1.0.0.

Covers: tools module collision, identity snake_case + ISO, circuit default
path, path-prefix/symlink/absolute sandbox, exec injection, checkpoint
delete_old, sync CLI entrypoint.
"""

from __future__ import annotations

import inspect
import os
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_resilience.checkpoint import AgentState, CheckpointStore
from agent_resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    default_state_file,
)
from agent_resilience.identity import SessionIdentityValidator, ValidationResult
from agent_resilience.tools import ToolRegistry
from agent_resilience.tools.builtin import (
    ExecTool,
    FileReadTool,
    FileWriteTool,
)


class TestToolsPackageOnly:
    def test_tools_is_package_not_module_file(self):
        import agent_resilience.tools as tools

        assert tools.__file__.endswith(os.path.join("tools", "__init__.py"))
        leftover = Path(tools.__file__).resolve().parent.parent / "tools.py"
        assert not leftover.exists()

    def test_builtin_importable_from_package(self):
        from agent_resilience.tools.builtin import register_builtin_tools

        reg = ToolRegistry()
        register_builtin_tools(reg)
        assert "file_read" in reg


class TestIdentityContract:
    @pytest.fixture
    def validator(self):
        return SessionIdentityValidator(
            expected_agent_id="gabriel",
            expected_session_key="agent:gabriel:main",
        )

    def test_snake_case_accepted(self, validator):
        ok, err = validator.validate(
            {
                "agent_id": "gabriel",
                "session_key": "agent:gabriel:main",
                "timestamp": time.time(),
            }
        )
        assert ok is True
        assert err is None

    def test_iso_timestamp_accepted(self, validator):
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ok, err = validator.validate(
            {
                "agentId": "gabriel",
                "sessionKey": "agent:gabriel:main",
                "timestamp": ts,
            }
        )
        assert ok is True, err
        assert err is None

    def test_garbage_timestamp_does_not_raise(self, validator):
        ok, err = validator.validate(
            {
                "agentId": "gabriel",
                "sessionKey": "agent:gabriel:main",
                "timestamp": "not-a-time",
            }
        )
        assert ok is False
        assert err is not None
        assert err.result == ValidationResult.INVALID_TIMESTAMP

    def test_readme_names_are_not_public_exports(self):
        import agent_resilience

        for name in ("Agent", "ModelRouter", "Checkpoint"):
            assert not hasattr(agent_resilience, name)


class TestCircuitDefaults:
    def test_default_state_file_not_tmp(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        path = default_state_file("probe-agent")
        assert path == tmp_path / "state" / "lar" / "circuit_probe-agent.json"
        assert not str(path).startswith("/tmp/lar_circuit_")

    def test_agent_id_sanitized(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        path = default_state_file("../evil")
        assert ".." not in path.parts
        assert path.name == "circuit_evil.json"

    def test_camelcase_foreign_payload_rejected(self, tmp_path):
        cb = CircuitBreaker(
            "gabriel",
            config=CircuitBreakerConfig(failure_threshold=2),
            state_file=tmp_path / "cb.json",
        )
        ok, reason = cb.evaluate({"agentId": "harry", "cron_id": "c1"})
        assert ok is False
        assert reason is not None

    @pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not enforced on Windows NTFS")
    def test_atomic_save_mode(self, tmp_path):
        state = tmp_path / "cb.json"
        cb = CircuitBreaker(
            "gabriel",
            config=CircuitBreakerConfig(failure_threshold=1),
            state_file=state,
        )
        cb.evaluate({"agent_id": "other", "cron_id": "c1"})
        assert state.exists()
        mode = stat.S_IMODE(state.stat().st_mode)
        assert mode == 0o600


class TestFileSandbox:
    async def test_prefix_sibling_blocked(self, tmp_path: Path):
        evil = Path(str(tmp_path) + "x")
        evil.mkdir()
        (evil / "secret.txt").write_text("PREFIXPWN")
        tool = FileReadTool(base_path=str(tmp_path))
        result = await tool.execute(path=f"../{evil.name}/secret.txt")
        assert result.success is False
        assert "outside base directory" in result.error

    async def test_absolute_path_blocked(self, tmp_path: Path):
        outside = tmp_path.parent / "lar_abs_secret.txt"
        outside.write_text("ABSPWN")
        try:
            tool = FileReadTool(base_path=str(tmp_path))
            result = await tool.execute(path=str(outside))
            assert result.success is False
            assert "outside base directory" in result.error
        finally:
            outside.unlink(missing_ok=True)

    async def test_symlink_escape_blocked(self, tmp_path: Path):
        outside = tmp_path.parent / "lar_link_target"
        outside.mkdir(exist_ok=True)
        secret = outside / "secret.txt"
        secret.write_text("LINKPWN")
        (tmp_path / "escape").symlink_to(outside)
        try:
            tool = FileReadTool(base_path=str(tmp_path))
            result = await tool.execute(path="escape/secret.txt")
            assert result.success is False
            assert "outside base directory" in result.error
        finally:
            secret.unlink(missing_ok=True)
            outside.rmdir()

    async def test_write_absolute_blocked(self, tmp_path: Path):
        target = tmp_path.parent / "lar_write_escape.txt"
        tool = FileWriteTool(base_path=str(tmp_path), allow_overwrite=True)
        result = await tool.execute(path=str(target), content="OWNED")
        assert result.success is False
        assert not target.exists()


class TestExecHardening:
    async def test_semicolon_injection_rejected(self):
        result = await ExecTool().execute(command="echo SAFE; echo INJECTED")
        assert result.success is False
        assert "metacharacters" in result.error

    async def test_subshell_rejected(self):
        result = await ExecTool().execute(command="echo $(whoami)")
        assert result.success is False

    async def test_python3_not_default_allowed(self):
        result = await ExecTool().execute(command="python3 --version")
        assert result.success is False
        assert "not in the allowed list" in result.error


class TestCheckpointDeleteOld:
    async def test_delete_old_removes_iso_rows(self, tmp_path: Path):
        store = CheckpointStore(tmp_path / "cp.db")
        old = AgentState(task_id="old")
        old.timestamp = (datetime.utcnow() - timedelta(days=40)).isoformat()
        new = AgentState(task_id="new")
        await store.save(old)
        await store.save(new)
        deleted = await store.delete_old(30)
        assert deleted == 1
        assert await store.latest_for_task("old") is None
        assert await store.latest_for_task("new") is not None

    async def test_delete_old_rejects_sql_string(self, tmp_path: Path):
        store = CheckpointStore(tmp_path / "cp.db")
        with pytest.raises(ValueError):
            await store.delete_old("1); DROP TABLE checkpoints;--")  # type: ignore[arg-type]


class TestCliEntrypoint:
    def test_main_is_sync(self):
        from agent_resilience.__main__ import main

        assert not inspect.iscoroutinefunction(main)
        assert callable(main)
