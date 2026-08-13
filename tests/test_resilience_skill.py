"""Library-backed skill tests (same six contracts as the original demo)."""

from __future__ import annotations

from agent_resilience.router import Consolidator, ModelRouter


async def test_router_creation(tmp_path):
    router = ModelRouter(
        primary="ollama/test-primary:cloud",
        fallbacks=["ollama/test-fallback1:cloud", "ollama/test-fallback2:cloud"],
        state_path=tmp_path / "router.json",
    )
    assert router.current.model_id == "ollama/test-primary:cloud"
    assert len(router.models) == 3
    assert router.has_fallback()
    assert router.select().model_id == "ollama/test-primary:cloud"


async def test_advance_moves_to_next_model(tmp_path):
    router = ModelRouter(
        primary="ollama/test-primary:cloud",
        fallbacks=["ollama/test-fallback1:cloud"],
        state_path=tmp_path / "router.json",
    )
    new = router.advance(reason="test")
    assert new is not None
    assert new.model_id == "ollama/test-fallback1:cloud"
    assert len(router.history) == 1


async def test_chain_exhaustion_returns_none(tmp_path):
    router = ModelRouter(
        primary="ollama/test-only:cloud",
        fallbacks=[],
        state_path=tmp_path / "router.json",
    )
    assert not router.has_fallback()
    assert router.advance(reason="test") is None


async def test_state_persists_across_instances(tmp_path):
    state_path = tmp_path / "persist.json"
    router1 = ModelRouter(
        primary="ollama/p1:cloud",
        fallbacks=["ollama/p2:cloud"],
        state_path=state_path,
    )
    router1.advance(reason="test")

    router2 = ModelRouter(
        primary="ollama/p1:cloud",
        fallbacks=["ollama/p2:cloud"],
        state_path=state_path,
    )
    assert router2.current_index == 1
    assert router2.current.model_id == "ollama/p2:cloud"
    assert len(router2.history) == 1


async def test_consolidator_runs():
    consolidator = Consolidator(steps=5, agency_threshold=0.5)

    async def predict(obs):
        return f"predicted-{obs}"

    buffer = [{"input": f"obs-{i}", "expected": f"result-{i}"} for i in range(10)]
    metrics = await consolidator.consolidate(predict, buffer)

    assert metrics["steps"] == 5
    assert "recovery" in metrics
    assert "duration_seconds" in metrics
    assert "threshold_met" in metrics
    assert 0.0 <= metrics["recovery"] <= 1.0


async def test_full_resilience_cycle(tmp_path):
    state_path = tmp_path / "full_cycle.json"

    router = ModelRouter(
        primary="ollama/primary:cloud",
        fallbacks=["ollama/fallback:cloud"],
        state_path=state_path,
    )

    assert router.current.model_id == "ollama/primary:cloud"
    new = router.advance(reason="test_death")
    assert new is not None
    assert new.model_id == "ollama/fallback:cloud"

    recovered = ModelRouter(
        primary="ollama/primary:cloud",
        fallbacks=["ollama/fallback:cloud"],
        state_path=state_path,
    )
    assert recovered.current.model_id == "ollama/fallback:cloud"
    assert len(recovered.history) == 1
