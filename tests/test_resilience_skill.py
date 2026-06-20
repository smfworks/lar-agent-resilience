"""Pytest conversion of the resilience skill tests.

The original test runner lives at
`skills/resilience-skill/examples/test_demo.py` and is a standalone
async script. This file ports those six checks to pytest so they
can run in CI, surface diffs on regression, and integrate with
pytest-asyncio for proper event-loop handling.

Why this matters: a skill that survives model death should also
survive a `git push` without silently breaking. The 6 tests below
are the smoke test that the failover primitive is still contract-
correct after a refactor.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the skill's failover module importable without an install step.
_SKILL_SCRIPTS = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "resilience-skill"
    / "scripts"
)
if str(_SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SKILL_SCRIPTS))

from failover import Consolidator, ModelRouter  # noqa: E402


# ---------------------------------------------------------------------------
# ModelRouter tests
# ---------------------------------------------------------------------------


async def test_router_creation(tmp_path):
    """Router constructed with primary + fallbacks exposes them in order."""
    router = ModelRouter(
        primary="ollama/test-primary:cloud",
        fallbacks=["ollama/test-fallback1:cloud", "ollama/test-fallback2:cloud"],
        state_path=tmp_path / "router.json",
    )
    assert router.current.model_id == "ollama/test-primary:cloud"
    assert len(router.models) == 3
    assert router.has_fallback()


async def test_advance_moves_to_next_model(tmp_path):
    """advance() rotates to the next model in the chain and records history."""
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
    """advance() returns None when the chain has no further models."""
    router = ModelRouter(
        primary="ollama/test-only:cloud",
        fallbacks=[],
        state_path=tmp_path / "router.json",
    )
    assert not router.has_fallback()
    assert router.advance(reason="test") is None


async def test_state_persists_across_instances(tmp_path):
    """State written by one router instance is visible to a fresh one."""
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


# ---------------------------------------------------------------------------
# Consolidator test
# ---------------------------------------------------------------------------


async def test_consolidator_runs():
    """Consolidator completes N steps, returns a metrics dict with recovery."""
    consolidator = Consolidator(steps=5, agency_threshold=0.5)

    async def predict(obs):
        return f"predicted-{obs}"

    buffer = [
        {"input": f"obs-{i}", "expected": f"result-{i}"} for i in range(10)
    ]
    metrics = await consolidator.consolidate(predict, buffer)

    # Steps are capped by consolidator.steps, not the buffer size.
    assert metrics["steps"] == 5
    assert "recovery" in metrics
    assert "duration_seconds" in metrics
    assert "threshold_met" in metrics
    assert 0.0 <= metrics["recovery"] <= 1.0


# ---------------------------------------------------------------------------
# End-to-end: the full Fable-style cycle
# ---------------------------------------------------------------------------


async def test_full_resilience_cycle(tmp_path):
    """Run on primary → fail → consolidate → resume on fallback. The full
    invariant LAR is meant to deliver: the agent continues working
    after the primary model disappears, and a new instance reading
    the state file sees the post-failover state.
    """
    state_path = tmp_path / "full_cycle.json"

    router = ModelRouter(
        primary="ollama/primary:cloud",
        fallbacks=["ollama/fallback:cloud"],
        state_path=state_path,
    )

    # Phase 1 — start on primary
    assert router.current.model_id == "ollama/primary:cloud"

    # Phase 2 — primary dies (Fable-style shutdown)
    new = router.advance(reason="test_death")
    assert new is not None
    assert new.model_id == "ollama/fallback:cloud"

    # Phase 3 — fresh process reading the same state file sees the
    # post-failover state. The agent did not forget the swap.
    recovered = ModelRouter(
        primary="ollama/primary:cloud",
        fallbacks=["ollama/fallback:cloud"],
        state_path=state_path,
    )
    assert recovered.current.model_id == "ollama/fallback:cloud"
    assert len(recovered.history) == 1
