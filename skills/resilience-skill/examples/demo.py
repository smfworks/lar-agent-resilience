"""Demo: Watch an agent survive a model death in real time.

This script demonstrates the LAR resilience principle:
1. Configure an agent with a primary model and fallback chain
2. Run a few "tasks" successfully
3. Simulate the primary model's death (Fable-style export-control shutdown)
4. Watch the agent fail over automatically
5. Run the consolidation phase
6. Resume tasks on the new model

Run with:
    python3 demo.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Add scripts dir to path so we can import failover
_SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_DIR / "scripts"))
from failover import Consolidator, ModelRouter, SwapEvent  # noqa: E402

# Quiet the failover module's logger for clean demo output
logging.getLogger("lar.failover").setLevel(logging.WARNING)


class DemoAgent:
    """A toy agent that runs tasks and simulates model failures."""

    def __init__(
        self,
        router: ModelRouter,
        consolidation_steps: int = 10,
        state_path: Path = Path("demo_agent_state.json"),
    ):
        self.router = router
        self.consolidator = Consolidator(steps=consolidation_steps, agency_threshold=0.15)
        self.state_path = state_path
        self.replay_buffer: list[dict] = []
        self.task_count = 0
        self.tool_use_enabled = True

    async def predict(self, observation: str) -> str:
        """Toy prediction function. Returns a deterministic value based on the model.

        Each model has its own "signature" — different outputs for the same input.
        This simulates the model-specific behavior that consolidation measures.
        """
        # Simulate each model producing slightly different outputs
        model = self.router.current.model_id
        await asyncio.sleep(0.01)  # simulate inference latency
        return f"prediction-{model}-{hash(observation) % 1000}"

    async def run_task(self, task: str) -> dict:
        """Run a single task. Returns a result dict."""
        if not self.tool_use_enabled:
            return {"error": "tool_use_disabled", "task": task}

        self.task_count += 1
        start = time.time()

        # Toy "model output"
        output = f"result-{self.router.current.model_id}-task-{self.task_count}"
        latency = time.time() - start

        # Record observation for replay buffer
        self.replay_buffer.append({
            "input": task,
            "output": output,
            "expected": output,  # in a real agent, this would be the next-state
        })

        return {
            "task": task,
            "output": output,
            "model": self.router.current.model_id,
            "latency_ms": latency * 1000,
        }

    async def swap_model(self, reason: str = "model_failure") -> dict:
        """Swap to next model and run consolidation."""
        old_model = self.router.current.model_id
        new_model = self.router.advance(reason=reason)

        if not new_model:
            return {
                "swap_successful": False,
                "reason": "fallback_chain_exhausted",
            }

        # Disable tool use during consolidation
        self.tool_use_enabled = False
        print(f"\n  [CONSOLIDATION] {old_model} -> {new_model.model_id}")
        print(f"  [CONSOLIDATION] Disabling tool use. Running {self.consolidator.steps} prediction steps...")

        metrics = await self.consolidator.consolidate(self.predict, self.replay_buffer)

        self.router.record_consolidation(
            steps=metrics["steps"],
            recovery=metrics["recovery"],
            duration_seconds=metrics["duration_seconds"],
        )

        # Re-enable tool use if threshold met
        if metrics["threshold_met"]:
            self.tool_use_enabled = True
            print(f"  [CONSOLIDATION] Threshold met (recovery={metrics['recovery']:.2f}). Tool use re-enabled.")
        else:
            print(f"  [CONSOLIDATION] Threshold NOT met (recovery={metrics['recovery']:.2f}). Keeping tool use disabled.")

        return {
            "swap_successful": True,
            "from_model": old_model,
            "to_model": new_model.model_id,
            "consolidation": metrics,
            "tool_use_enabled": self.tool_use_enabled,
        }


async def main() -> int:
    print("=" * 70)
    print("LAR Resilience Demo — Watch an agent survive model death")
    print("=" * 70)

    # Configure the agent
    router = ModelRouter(
        primary="ollama/glm-5.2:cloud",
        fallbacks=[
            "ollama/qwen3-coder:32b",
            "ollama/kimi-k2.7-code:cloud",
            "ollama/qwen3.5:9b",
        ],
        state_path=Path("demo_router_state.json"),
    )

    print(f"\n[SETUP] Primary: {router.models[0].model_id}")
    print(f"[SETUP] Fallback chain:")
    for i, m in enumerate(router.models[1:], 1):
        print(f"         {i}. {m.model_id}")

    agent = DemoAgent(router=router, consolidation_steps=20)

    # Phase 1: Run a few successful tasks
    print(f"\n[PHASE 1] Running initial tasks on {router.current.model_id}...")
    for i in range(3):
        result = await agent.run_task(f"task-{i}")
        print(f"  Task {i}: model={result['model'].split('/')[-1]} output={result['output'][:50]}")

    # Phase 2: Simulate model death
    print(f"\n[PHASE 2] Simulating model death of {router.current.model_id}...")
    print(f"  >>> Emergency: U.S. export-control directive issued at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  >>> Fable-style shutdown. Every agent on {router.current.model_id} is now dead.")

    swap_result = await agent.swap_model(reason="Simulated Fable 5 export-control shutdown")

    if not swap_result["swap_successful"]:
        print(f"  [FATAL] {swap_result['reason']}")
        return 1

    print(f"\n  [RECOVERY] Now running on {swap_result['to_model']}")
    print(f"  [RECOVERY] Consolidation: {swap_result['consolidation']['steps']} steps, recovery={swap_result['consolidation']['recovery']:.2f}")

    # Phase 3: Continue working on the new model
    if swap_result["tool_use_enabled"]:
        print(f"\n[PHASE 3] Resuming tasks on {swap_result['to_model']}...")
        for i in range(3, 6):
            result = await agent.run_task(f"task-{i}")
            print(f"  Task {i}: model={result['model'].split('/')[-1]} output={result['output'][:50]}")

        print(f"\n[SUCCESS] Agent survived model death.")
        print(f"[SUCCESS] {agent.task_count} tasks completed across {len(set(e.to_model for e in router.history)) + 1} models.")

    # Show final router status
    print(f"\n[FINAL STATUS]")
    status = router.status()
    print(json.dumps({
        "current_model": status["current_model"],
        "fallbacks_remaining": status["fallbacks_remaining"],
        "total_swaps": status["swap_count"],
        "recent_swaps": status["recent_swaps"],
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))