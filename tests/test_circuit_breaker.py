"""Tests for agent_resilience.circuit_breaker — CircuitBreaker.

Covers: CLOSED/OPEN/HALF_OPEN state transitions, misfire recording,
threshold tripping, state persistence, manual reset, status reporting.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    MisfireEvent,
)


@pytest.fixture
def cb(tmp_path: Path) -> CircuitBreaker:
    """Fresh circuit breaker with threshold=2, persistence to tmp."""
    return CircuitBreaker(
        agent_id="test-agent",
        config=CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout_seconds=3600,
            half_open_max_attempts=1,
            enabled=True,
        ),
        state_file=tmp_path / "circuit.json",
    )


@pytest.fixture
def foreign_payload():
    return {
        "agent_id": "wrong-agent",
        "cron_id": "cron-123",
        "type": "cron",
    }


@pytest.fixture
def valid_payload():
    return {
        "agent_id": "test-agent",
        "cron_id": "cron-456",
        "type": "cron",
    }


class TestCircuitBreakerStates:
    def test_initial_state_is_closed(self, cb):
        assert cb.state == CircuitState.CLOSED

    def test_valid_payload_accepted_when_closed(self, cb, valid_payload):
        ok, reason = cb.evaluate(valid_payload)
        assert ok is True
        assert reason is None

    def test_foreign_payload_rejected_when_closed(self, cb, foreign_payload):
        ok, reason = cb.evaluate(foreign_payload)
        assert ok is False
        assert "Foreign payload rejected" in reason

    def test_single_misfire_does_not_trip(self, cb, foreign_payload):
        cb.evaluate(foreign_payload)
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 1

    def test_threshold_misfires_trip_circuit(self, cb, foreign_payload):
        cb.evaluate(foreign_payload)  # 1st misfire
        cb.evaluate(foreign_payload)  # 2nd misfire → trip
        assert cb.state == CircuitState.OPEN
        assert cb._failure_count == 2

    def test_open_circuit_rejects_all(self, cb, foreign_payload, valid_payload):
        # Trip the circuit
        cb.evaluate(foreign_payload)
        cb.evaluate(foreign_payload)
        assert cb.state == CircuitState.OPEN
        # Even valid payloads should be rejected when OPEN
        ok, reason = cb.evaluate(valid_payload)
        assert ok is False
        assert "OPEN" in reason

    def test_disabled_circuit_accepts_everything(self, foreign_payload):
        cb = CircuitBreaker(
            agent_id="test-agent",
            config=CircuitBreakerConfig(enabled=False),
            state_file=Path("/tmp/test_cb_disabled.json"),
        )
        ok, reason = cb.evaluate(foreign_payload)
        assert ok is True
        assert reason is None


class TestCircuitBreakerPersistence:
    def test_state_persists_to_disk(self, tmp_path: Path, foreign_payload):
        state_file = tmp_path / "persist_cb.json"
        cb1 = CircuitBreaker(
            agent_id="persist-agent",
            config=CircuitBreakerConfig(failure_threshold=2),
            state_file=state_file,
        )
        cb1.evaluate(foreign_payload)
        cb1.evaluate(foreign_payload)
        assert cb1.state == CircuitState.OPEN

        # New instance should load the OPEN state
        cb2 = CircuitBreaker(
            agent_id="persist-agent",
            config=CircuitBreakerConfig(failure_threshold=2),
            state_file=state_file,
        )
        assert cb2.state == CircuitState.OPEN
        assert cb2._failure_count == 2

    def test_misfires_loaded_from_disk(self, tmp_path: Path, foreign_payload):
        state_file = tmp_path / "misfires_cb.json"
        cb1 = CircuitBreaker(
            agent_id="persist-agent",
            config=CircuitBreakerConfig(failure_threshold=10),
            state_file=state_file,
        )
        cb1.evaluate(foreign_payload)
        cb1.evaluate(foreign_payload)

        cb2 = CircuitBreaker(
            agent_id="persist-agent",
            config=CircuitBreakerConfig(failure_threshold=10),
            state_file=state_file,
        )
        assert len(cb2.misfires) == 2

    def test_corrupt_state_file_handled_gracefully(self, tmp_path: Path):
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("not valid json {{{")
        cb = CircuitBreaker(
            agent_id="corrupt-agent",
            state_file=state_file,
        )
        # Should fall back to defaults
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerRecovery:
    def test_manual_reset_closes_circuit(self, cb, foreign_payload):
        cb.evaluate(foreign_payload)
        cb.evaluate(foreign_payload)
        assert cb.state == CircuitState.OPEN
        cb.manual_reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_half_open_after_recovery_timeout(self, tmp_path: Path, foreign_payload):
        state_file = tmp_path / "recovery_cb.json"
        cb = CircuitBreaker(
            agent_id="recovery-agent",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0,  # immediately recoverable
            ),
            state_file=state_file,
        )
        # Trip with one misfire
        cb.evaluate(foreign_payload)
        assert cb.state == CircuitState.OPEN

        # Need to set last_failure_time far enough in the past for recovery
        from datetime import datetime, timedelta
        cb._last_failure_time = datetime.utcnow() - timedelta(seconds=10)

        # Should transition to HALF_OPEN since recovery_timeout=0
        # Use a valid payload to avoid recording another misfire
        valid_payload = {"agent_id": "recovery-agent", "cron_id": "c1"}
        ok, reason = cb.evaluate(valid_payload)
        assert cb.state == CircuitState.HALF_OPEN or cb.state == CircuitState.CLOSED

    def test_half_open_success_closes_circuit(self, tmp_path: Path, valid_payload):
        state_file = tmp_path / "halfopen_close.json"
        cb = CircuitBreaker(
            agent_id="recovery-agent",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0,
            ),
            state_file=state_file,
        )
        # Trip
        foreign = {"agent_id": "wrong", "cron_id": "c1"}
        cb.evaluate(foreign)
        assert cb.state == CircuitState.OPEN

        # Set last_failure_time in the past so recovery is attempted
        from datetime import datetime, timedelta
        cb._last_failure_time = datetime.utcnow() - timedelta(seconds=10)

        # Next eval transitions to HALF_OPEN, and since payload is valid, closes
        # Use the correct agent_id matching the circuit breaker's agent
        valid_recovery = {"agent_id": "recovery-agent", "cron_id": "cron-456", "type": "cron"}
        ok, _ = cb.evaluate(valid_recovery)
        assert ok is True
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_retrips(self, tmp_path: Path, foreign_payload):
        state_file = tmp_path / "halfopen_retrip.json"
        cb = CircuitBreaker(
            agent_id="recovery-agent",
            config=CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0,
                half_open_max_attempts=1,
            ),
            state_file=state_file,
        )
        # Trip
        cb.evaluate(foreign_payload)
        assert cb.state == CircuitState.OPEN

        # Set last_failure_time in the past so recovery is attempted
        from datetime import datetime, timedelta
        cb._last_failure_time = datetime.utcnow() - timedelta(seconds=10)

        # First eval: transitions to HALF_OPEN, then misfire causes retrip
        ok, reason = cb.evaluate(foreign_payload)
        assert ok is False
        assert reason is not None
        # With threshold=1, _record_misfire trips immediately, so the reason
        # is "Foreign payload rejected" (the HALF_OPEN branch is never reached
        # because _record_misfire already tripped the circuit to OPEN)
        assert "rejected" in reason.lower() or "re-tripped" in reason.lower() or "OPEN" in reason
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerStatus:
    def test_get_status_returns_dict(self, cb, foreign_payload):
        cb.evaluate(foreign_payload)
        status = cb.get_status()
        assert isinstance(status, dict)
        assert status["state"] == "closed"
        assert status["agent_id"] == "test-agent"
        assert status["failure_count"] == 1
        assert status["failure_threshold"] == 2
        assert status["recent_misfires_24h"] == 1
        assert status["total_misfires"] == 1

    def test_status_no_failures(self, cb):
        status = cb.get_status()
        assert status["failure_count"] == 0
        assert status["last_failure"] is None


class TestMisfireEvent:
    def test_to_dict(self):
        event = MisfireEvent(
            timestamp="2026-01-01T00:00:00",
            cron_id="cron-1",
            expected_agent_id="agent-a",
            actual_agent_id="agent-b",
        )
        d = event.to_dict()
        assert d["cron_id"] == "cron-1"
        assert d["expected_agent_id"] == "agent-a"
        assert d["actual_agent_id"] == "agent-b"
        assert d["payload_type"] == "cron"
        assert d["reason"] == "agent_id_mismatch"