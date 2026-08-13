"""Checkpoint save/load/resume and delete_old contract."""

from pathlib import Path

import pytest

from agent_resilience.checkpoint import AgentState, Checkpoint, CheckpointStore, Phase


@pytest.mark.asyncio
async def test_save_and_load(tmp_path: Path):
    store = Checkpoint(tmp_path / "state.db")
    state = AgentState(
        task_id="t1",
        step_number=2,
        phase=Phase.ACT,
        messages=[{"role": "user", "content": "hello"}],
        is_complete=False,
        model_used="fake",
    )
    cid = await store.save(state)
    loaded = await store.load(cid)
    assert loaded is not None
    assert loaded.task_id == "t1"
    assert loaded.step_number == 2
    assert loaded.phase is Phase.ACT
    assert loaded.messages[0]["content"] == "hello"
    assert loaded.is_complete is False


@pytest.mark.asyncio
async def test_resume_incomplete_task(tmp_path: Path):
    store = CheckpointStore(tmp_path / "state.db")
    await store.save(
        AgentState(task_id="job", step_number=1, phase=Phase.THINK, is_complete=False)
    )
    latest = await store.latest_for_task("job")
    assert latest is not None
    assert latest.is_complete is False
    incomplete = await store.incomplete_tasks()
    assert "job" in incomplete


@pytest.mark.asyncio
async def test_delete_old_requires_int(tmp_path: Path):
    store = Checkpoint(tmp_path / "state.db")
    await store.save(AgentState(task_id="x"))
    deleted = await store.delete_old(days=30)
    assert isinstance(deleted, int)
    with pytest.raises(TypeError):
        await store.delete_old(days="30")  # type: ignore[arg-type]
