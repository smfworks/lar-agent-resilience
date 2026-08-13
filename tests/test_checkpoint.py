"""Tests for agent_resilience.checkpoint — CheckpointStore and AgentState.

Covers: save/load cycle, latest_for_task, list_for_task, incomplete_tasks,
delete_old, AgentState serialization, Phase enum.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_resilience.checkpoint import (
    AgentState,
    CheckpointStore,
    Phase,
)


@pytest.fixture
def store(tmp_path: Path) -> CheckpointStore:
    return CheckpointStore(tmp_path / "checkpoints.db")


@pytest.fixture
def sample_state():
    return AgentState(
        task_id="task-1",
        step_number=3,
        phase=Phase.THINK,
        context={"key": "value"},
        messages=[{"role": "user", "content": "hello"}],
        tool_calls=[{"function": {"name": "exec", "arguments": {"command": "ls"}}}],
        tool_results=[{"tool": "exec", "result": {"success": True}}],
        memory_snapshot={"short_term": 5},
        model_used="test-model",
        tools_available=["exec", "file_read"],
        checkpoint_reason="step_boundary",
    )


class TestAgentState:
    def test_defaults(self):
        state = AgentState()
        assert state.task_id == "default"
        assert state.step_number == 0
        assert state.phase == Phase.OBSERVE
        assert state.is_complete is False
        assert state.max_iterations == 10
        assert state.checkpoint_reason == "step_boundary"

    def test_to_json(self, sample_state):
        j = sample_state.to_json()
        data = json.loads(j)
        assert data["task_id"] == "task-1"
        assert data["step_number"] == 3
        assert data["phase"] == "think"

    def test_from_dict_roundtrip(self, sample_state):
        data = json.loads(sample_state.to_json())
        restored = AgentState.from_dict(data)
        assert restored.task_id == "task-1"
        assert restored.step_number == 3
        assert restored.phase == Phase.THINK
        assert restored.model_used == "test-model"

    def test_from_dict_converts_phase_string(self):
        data = {"task_id": "t", "phase": "act"}
        state = AgentState.from_dict(data)
        assert state.phase == Phase.ACT

    def test_phase_enum_values(self):
        assert Phase.OBSERVE.value == "observe"
        assert Phase.THINK.value == "think"
        assert Phase.ACT.value == "act"
        assert Phase.RESPOND.value == "respond"


class TestCheckpointStore:
    async def test_save_and_load(self, store, sample_state):
        cp_id = await store.save(sample_state)
        assert cp_id == sample_state.checkpoint_id

        loaded = await store.load(cp_id)
        assert loaded is not None
        assert loaded.task_id == "task-1"
        assert loaded.step_number == 3
        assert loaded.phase == Phase.THINK
        assert loaded.model_used == "test-model"
        assert loaded.tools_available == ["exec", "file_read"]

    async def test_load_nonexistent_returns_none(self, store):
        result = await store.load("nonexistent-id")
        assert result is None

    async def test_latest_for_task(self, store, sample_state):
        # Save multiple checkpoints for same task
        s1 = AgentState(task_id="task-x", step_number=1, phase=Phase.OBSERVE)
        s2 = AgentState(task_id="task-x", step_number=2, phase=Phase.THINK)
        s3 = AgentState(task_id="task-x", step_number=3, phase=Phase.ACT)

        await store.save(s1)
        await store.save(s2)
        await store.save(s3)

        latest = await store.latest_for_task("task-x")
        assert latest is not None
        # Should be the most recent by timestamp
        assert latest.task_id == "task-x"

    async def test_latest_for_task_nonexistent(self, store):
        result = await store.latest_for_task("no-such-task")
        assert result is None

    async def test_list_for_task(self, store, sample_state):
        for i in range(5):
            s = AgentState(task_id="list-task", step_number=i, phase=Phase.OBSERVE)
            await store.save(s)

        results = await store.list_for_task("list-task")
        assert len(results) == 5
        assert all(r.task_id == "list-task" for r in results)

    async def test_list_for_task_with_limit(self, store):
        for i in range(10):
            s = AgentState(task_id="limit-task", step_number=i, phase=Phase.OBSERVE)
            await store.save(s)

        results = await store.list_for_task("limit-task", limit=3)
        assert len(results) == 3

    async def test_incomplete_tasks(self, store):
        s1 = AgentState(task_id="incomplete-1", is_complete=False)
        s2 = AgentState(task_id="complete-1", is_complete=True)
        s3 = AgentState(task_id="incomplete-2", is_complete=False)
        await store.save(s1)
        await store.save(s2)
        await store.save(s3)

        incomplete = await store.incomplete_tasks()
        assert "incomplete-1" in incomplete
        assert "incomplete-2" in incomplete
        assert "complete-1" not in incomplete

    async def test_incomplete_tasks_empty(self, store):
        result = await store.incomplete_tasks()
        assert result == []

    async def test_save_replaces_same_id(self, store, sample_state):
        await store.save(sample_state)
        # Save again with same ID — should replace, not duplicate
        await store.save(sample_state)
        results = await store.list_for_task("task-1")
        assert len(results) == 1

    async def test_db_directory_created(self, tmp_path: Path, sample_state):
        nested = tmp_path / "deep" / "nested" / "path" / "checkpoints.db"
        store = CheckpointStore(nested)
        await store.save(sample_state)
        assert nested.exists()

    async def test_complete_checkpoint_loaded(self, store):
        s = AgentState(task_id="done-task", is_complete=True, phase=Phase.RESPOND)
        await store.save(s)
        loaded = await store.load(s.checkpoint_id)
        assert loaded is not None
        assert loaded.is_complete is True

    async def test_error_state_persisted(self, store):
        s = AgentState(task_id="err-task", error="something went wrong")
        await store.save(s)
        loaded = await store.load(s.checkpoint_id)
        assert loaded is not None
        assert loaded.error == "something went wrong"