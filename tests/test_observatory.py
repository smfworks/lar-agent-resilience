"""Tests for agent_resilience.observatory — Observatory and StepEvent.

Covers: event recording, state snapshot, checkpoint/memory tracking,
error recording, integration hooks.
"""

from __future__ import annotations

import time

import pytest

from agent_resilience.observatory import (
    Observatory,
    ObservatoryState,
    StepEvent,
)


@pytest.fixture
def observatory():
    return Observatory(host="127.0.0.1", port=9999)


class TestStepEvent:
    def test_defaults(self):
        event = StepEvent(
            timestamp=time.time(),
            phase="think",
            step_number=1,
            duration_ms=42.5,
        )
        assert event.phase == "think"
        assert event.step_number == 1
        assert event.duration_ms == 42.5
        assert event.detail == ""
        assert event.tool is None
        assert event.success is True

    def test_with_tool(self):
        event = StepEvent(
            timestamp=time.time(),
            phase="act",
            step_number=2,
            duration_ms=10.0,
            tool="exec",
            tool_input={"command": "ls"},
            tool_output_preview="file1\nfile2",
        )
        assert event.tool == "exec"
        assert event.tool_input == {"command": "ls"}


class TestObservatoryState:
    def test_snapshot(self):
        state = ObservatoryState(agent_id="test-agent")
        snap = state.snapshot()
        assert snap["agent_id"] == "test-agent"
        assert snap["total_steps"] == 0
        assert snap["circuit_state"] == "CLOSED"
        assert snap["error_count"] == 0
        assert snap["checkpoint_count"] == 0
        assert "recent_steps" in snap
        assert "tool_counts" in snap

    def test_uptime_calculated(self):
        state = ObservatoryState(agent_id="test")
        snap = state.snapshot()
        assert snap["uptime_s"] >= 0


class TestObservatory:
    def test_initial_state(self, observatory):
        assert observatory.host == "127.0.0.1"
        assert observatory.port == 9999
        assert observatory.state.total_steps == 0
        assert observatory.clients == set()
        assert observatory.health_monitor is None
        assert observatory.checkpoint_store is None
        assert observatory.circuit_breaker is None

    def test_record_step_increments(self, observatory):
        event = StepEvent(
            timestamp=time.time(),
            phase="think",
            step_number=1,
            duration_ms=50.0,
            success=True,
        )
        observatory.record_step(event)
        assert observatory.state.total_steps == 1
        assert observatory.state.current_phase == "running"
        assert len(observatory.state.recent_steps) == 1

    def test_record_step_with_tool(self, observatory):
        event = StepEvent(
            timestamp=time.time(),
            phase="act",
            step_number=1,
            duration_ms=50.0,
            tool="exec",
            success=True,
        )
        observatory.record_step(event)
        assert observatory.state.tool_counts["exec"] == 1

    def test_record_step_error_increments_error_count(self, observatory):
        event = StepEvent(
            timestamp=time.time(),
            phase="error",
            step_number=1,
            duration_ms=0,
            success=False,
        )
        observatory.record_step(event)
        assert observatory.state.error_count == 1

    def test_record_checkpoint(self, observatory):
        observatory.record_checkpoint()
        observatory.record_checkpoint()
        assert observatory.state.checkpoint_count == 2

    def test_record_memory_write(self, observatory):
        observatory.record_memory_write()
        assert observatory.state.memory_writes == 1

    def test_record_error(self, observatory):
        observatory.record_error("something went wrong")
        assert observatory.state.error_count == 1
        assert len(observatory.state.recent_steps) == 1

    def test_attach_health(self, observatory):
        mock_monitor = type("MockMonitor", (), {"check_all": lambda self: None})()
        # Can't easily test the full health check without mocking, but verify attach works
        observatory.attach_health(mock_monitor)  # type: ignore
        assert observatory.health_monitor is mock_monitor

    def test_attach_circuit_breaker(self, observatory):
        import pathlib
        import tempfile

        from agent_resilience.circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker(
            agent_id="obs-test",
            state_file=pathlib.Path(tempfile.mktemp(suffix=".json")),
        )
        observatory.attach_circuit_breaker(cb)
        assert observatory.circuit_breaker is cb
        assert observatory.state.circuit_state == CircuitState.CLOSED.name

    def test_static_dir_default(self, observatory):
        assert observatory.static_dir is not None
        assert observatory.static_dir.name == "ui"
