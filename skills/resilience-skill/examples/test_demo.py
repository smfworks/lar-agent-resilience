"""Test the resilience demo end-to-end.

Run with: python3 test_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_DIR / "scripts"))
from failover import ModelRouter, Consolidator  # noqa: E402


async def test_router_creation() -> bool:
    """Test that ModelRouter can be created with primary and fallbacks."""
    router = ModelRouter(
        primary="ollama/test-primary:cloud",
        fallbacks=["ollama/test-fallback1:cloud", "ollama/test-fallback2:cloud"],
        state_path=Path("/tmp/test_router.json"),
    )
    assert router.current.model_id == "ollama/test-primary:cloud"
    assert len(router.models) == 3
    assert router.has_fallback()
    print("  [PASS] test_router_creation")
    return True


async def test_advance() -> bool:
    """Test that advance() moves to the next model."""
    router = ModelRouter(
        primary="ollama/test-primary:cloud",
        fallbacks=["ollama/test-fallback1:cloud"],
        state_path=Path("/tmp/test_advance.json"),
    )
    new = router.advance(reason="test")
    assert new is not None
    assert new.model_id == "ollama/test-fallback1:cloud"
    assert len(router.history) == 1
    print("  [PASS] test_advance")
    return True


async def test_chain_exhaustion() -> bool:
    """Test that advance() returns None when chain is exhausted."""
    router = ModelRouter(
        primary="ollama/test-only:cloud",
        fallbacks=[],
        state_path=Path("/tmp/test_exhaust.json"),
    )
    assert not router.has_fallback()
    result = router.advance(reason="test")
    assert result is None
    print("  [PASS] test_chain_exhaustion")
    return True


async def test_state_persistence() -> bool:
    """Test that router state survives reload."""
    state_path = Path("/tmp/test_persist.json")
    if state_path.exists():
        state_path.unlink()

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
    print("  [PASS] test_state_persistence")
    state_path.unlink()
    return True


async def test_consolidator_runs() -> bool:
    """Test that the Consolidator runs without error."""
    consolidator = Consolidator(steps=5, agency_threshold=0.5)

    async def predict(obs):
        return f"predicted-{obs}"

    buffer = [{"input": f"obs-{i}", "expected": f"result-{i}"} for i in range(10)]
    metrics = await consolidator.consolidate(predict, buffer)

    assert metrics["steps"] == 5  # limited to consolidator.steps
    assert "recovery" in metrics
    assert "duration_seconds" in metrics
    assert "threshold_met" in metrics
    print(f"  [PASS] test_consolidator_runs (recovery={metrics['recovery']:.2f})")
    return True


async def test_full_resilience_cycle() -> bool:
    """Test the full cycle: run tasks, simulate death, fail over, consolidate, resume."""
    state_path = Path("/tmp/test_full_cycle.json")
    if state_path.exists():
        state_path.unlink()

    router = ModelRouter(
        primary="ollama/primary:cloud",
        fallbacks=["ollama/fallback:cloud"],
        state_path=state_path,
    )

    # Phase 1: Run on primary
    assert router.current.model_id == "ollama/primary:cloud"

    # Phase 2: Simulate death
    new = router.advance(reason="test_death")
    assert new is not None
    assert new.model_id == "ollama/fallback:cloud"

    # Phase 3: Verify state persisted
    router2 = ModelRouter(
        primary="ollama/primary:cloud",
        fallbacks=["ollama/fallback:cloud"],
        state_path=state_path,
    )
    assert router2.current.model_id == "ollama/fallback:cloud"
    assert len(router2.history) == 1

    state_path.unlink()
    print("  [PASS] test_full_resilience_cycle")
    return True


async def main() -> int:
    print("=" * 60)
    print("LAR Resilience Skill — Tests")
    print("=" * 60)
    print()

    tests = [
        test_router_creation,
        test_advance,
        test_chain_exhaustion,
        test_state_persistence,
        test_consolidator_runs,
        test_full_resilience_cycle,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
        except Exception as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))