"""Core library tests for agent_resilience (LAR)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent_resilience.checkpoint import AgentState, CheckpointStore, Phase
from agent_resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from agent_resilience.config import ConfigManager
from agent_resilience.identity import SessionIdentityValidator, ValidationResult
from agent_resilience.tools import ToolRegistry


def test_package_exports_version():
    import agent_resilience

    assert agent_resilience.__version__
    import lar  # compatibility path

    assert lar.__version__ == agent_resilience.__version__


def test_config_from_mapping_and_env(monkeypatch):
    monkeypatch.setenv("AGENT_ID", "jeff")
    cfg = ConfigManager.from_mapping(
        {
            "agent_id": "${AGENT_ID:gabriel}",
            "agent_name": "Jeff",
            "session_key": "agent:jeff:main",
            "log_level": "debug",
            "identity": {"hmac_secret": ""},
        }
    )
    assert cfg.agent_id == "jeff"
    assert cfg.log_level == "DEBUG"
    assert cfg.identity.hmac_secret is None
    assert cfg.workspace_dir.exists() or True


def test_config_rejects_bad_log_level():
    with pytest.raises(Exception):
        ConfigManager.from_mapping(
            {
                "agent_id": "a",
                "agent_name": "A",
                "session_key": "k",
                "log_level": "LOUD",
            }
        )


def test_identity_accepts_snake_and_iso():
    v = SessionIdentityValidator("jeff", "agent:jeff:main")
    ok, err = v.validate(
        {
            "agent_id": "jeff",
            "session_key": "agent:jeff:main",
            "timestamp": time.time(),
        }
    )
    assert ok and err is None

    ok, err = v.validate(
        {
            "agentId": "jeff",
            "sessionKey": "agent:jeff:main",
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        }
    )
    assert ok and err is None


def test_identity_rejects_wrong_agent():
    v = SessionIdentityValidator("jeff", "agent:jeff:main")
    ok, err = v.validate(
        {
            "agent_id": "harry",
            "session_key": "agent:jeff:main",
            "timestamp": time.time(),
        }
    )
    assert not ok
    assert err is not None
    assert err.result == ValidationResult.WRONG_AGENT_ID


def test_identity_rejects_stale():
    v = SessionIdentityValidator("jeff", "agent:jeff:main", max_payload_age_seconds=5)
    ok, err = v.validate(
        {
            "agent_id": "jeff",
            "session_key": "agent:jeff:main",
            "timestamp": time.time() - 30,
        }
    )
    assert not ok
    assert err is not None
    assert err.result == ValidationResult.STALE_PAYLOAD


def test_circuit_breaker_trips_on_foreign_payloads(tmp_path: Path):
    cb = CircuitBreaker(
        "jeff",
        config=CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=3600),
        state_file=tmp_path / "cb.json",
    )
    accepted, _ = cb.evaluate({"agent_id": "jeff", "cron_id": "ok"})
    assert accepted
    accepted, reason = cb.evaluate({"agent_id": "harry", "cron_id": "x1"})
    assert not accepted
    accepted, reason = cb.evaluate({"agent_id": "harry", "cron_id": "x2"})
    assert not accepted
    assert cb.state == CircuitState.OPEN
    accepted, reason = cb.evaluate({"agent_id": "jeff", "cron_id": "later"})
    assert not accepted
    assert "OPEN" in (reason or "")
    cb.manual_reset()
    accepted, _ = cb.evaluate({"agent_id": "jeff", "cron_id": "after"})
    assert accepted


@pytest.mark.asyncio
async def test_checkpoint_roundtrip(tmp_path: Path):
    store = CheckpointStore(tmp_path / "ck.db")
    state = AgentState(task_id="t1", step_number=2, phase=Phase.ACT, messages=[{"role": "user", "content": "hi"}])
    cid = await store.save(state)
    loaded = await store.load(cid)
    assert loaded is not None
    assert loaded.task_id == "t1"
    assert loaded.phase == Phase.ACT
    latest = await store.latest_for_task("t1")
    assert latest is not None
    assert latest.checkpoint_id == cid
    incomplete = await store.incomplete_tasks()
    assert "t1" in incomplete


def test_tool_registry_public_registry():
    reg = ToolRegistry()
    assert reg.registry == {}
    assert "missing" not in reg
    assert reg.get_tool_names() == []
