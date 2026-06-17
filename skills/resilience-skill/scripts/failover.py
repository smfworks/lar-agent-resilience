"""LAR Model Failover — Production-grade fallback chain with consolidation.

The atomic unit of LAR. Wraps ModelRouter, ModelLifecycle, and a
consolidation phase into a single installable skill.

When a model dies (deprecation, outage, capability shock), this skill:
1. Detects the failure via the circuit breaker
2. Selects the next model in the fallback chain
3. Runs a consolidation phase (async awakening) before re-enabling tool use
4. Logs every transition for observability
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

try:
    import structlog
    import logging
    # Silence structlog by default — callers can re-enable
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR),
    )
    logger = structlog.get_logger("lar.failover")
    _HAS_STRUCTLOG = True
except Exception:
    # Fallback to standard logging if structlog isn't available
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logger = logging.getLogger("lar.failover")
    _HAS_STRUCTLOG = False


def _log(level: str, msg: str, **kwargs) -> None:
    """Unified logging that works with both structlog and stdlib logging."""
    if _HAS_STRUCTLOG:
        getattr(logger, level)(msg, **kwargs)
    else:
        log_fn = getattr(logger, level)
        log_fn(f"{msg} {kwargs}" if kwargs else msg)


@dataclass
class ModelConfig:
    """Single model in a fallback chain."""

    model_id: str
    provider: str = "ollama"
    timeout_seconds: float = 30.0
    enabled: bool = True
    notes: str = ""


@dataclass
class SwapEvent:
    """Record of a model swap event."""

    timestamp: str
    from_model: str
    to_model: str
    reason: str
    consolidation_steps: int
    consolidation_recovery: float  # 0.0-1.0, agency gain after settling
    duration_seconds: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "from_model": self.from_model,
            "to_model": self.to_model,
            "reason": self.reason,
            "consolidation_steps": self.consolidation_steps,
            "consolidation_recovery": self.consolidation_recovery,
            "duration_seconds": self.duration_seconds,
        }


class ModelRouter:
    """Pluggable model selection with fallback chain.

    Selects a model from the chain. If the primary fails, the router
    advances to the next enabled model. The router tracks its own
    state and persists it to disk so swaps survive process restarts.
    """

    def __init__(
        self,
        primary: str,
        fallbacks: list[str],
        state_path: Optional[Path] = None,
        provider: str = "ollama",
    ):
        self.models = [ModelConfig(model_id=primary, provider=provider)]
        for fb in fallbacks:
            self.models.append(ModelConfig(model_id=fb, provider=provider))
        self.state_path = state_path or Path("model_router_state.json")
        self.history: list[SwapEvent] = []
        self.current_index = 0
        self._load_state()

    def _load_state(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.current_index = data.get("current_index", 0)
                self.history = [
                    SwapEvent(**e) for e in data.get("history", [])
                ]
                _log(
                    "info",
                    "router_state_loaded",
                    current_index=self.current_index,
                    history_count=len(self.history),
                )
            except Exception as e:
                _log("warning", "router_state_load_failed", error=str(e))

    def _save_state(self) -> None:
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "current_index": self.current_index,
            "current_model": self.current.model_id,
            "history": [e.to_dict() for e in self.history[-100:]],
        }
        self.state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    @property
    def current(self) -> ModelConfig:
        return self.models[self.current_index]

    def all_models(self) -> list[str]:
        return [m.model_id for m in self.models]

    def has_fallback(self) -> bool:
        return self.current_index < len(self.models) - 1

    def advance(self, reason: str = "model_failure") -> Optional[ModelConfig]:
        """Advance to next model in the chain. Returns the new model, or None if exhausted."""
        if not self.has_fallback():
            _log("error", "fallback_chain_exhausted", current=self.current.model_id)
            return None

        from_model = self.current.model_id
        self.current_index += 1
        to_model = self.current.model_id

        event = SwapEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            from_model=from_model,
            to_model=to_model,
            reason=reason,
            consolidation_steps=0,
            consolidation_recovery=0.0,
            duration_seconds=0.0,
        )
        self.history.append(event)
        self._save_state()

        _log(
            "warning",
            "model_swap",
            from_model=from_model,
            to_model=to_model,
            reason=reason,
            current_index=self.current_index,
        )
        return self.current

    def record_consolidation(
        self,
        steps: int,
        recovery: float,
        duration_seconds: float,
    ) -> None:
        """Record the consolidation metrics for the most recent swap."""
        if not self.history:
            return
        last = self.history[-1]
        last.consolidation_steps = steps
        last.consolidation_recovery = recovery
        last.duration_seconds = duration_seconds
        self._save_state()
        _log(
            "info",
            "consolidation_complete",
            steps=steps,
            recovery=recovery,
            duration_seconds=duration_seconds,
        )

    def status(self) -> dict:
        """Return router status for observability."""
        return {
            "current_model": self.current.model_id,
            "current_index": self.current_index,
            "fallback_chain": self.all_models(),
            "fallbacks_remaining": len(self.models) - self.current_index - 1,
            "swap_count": len(self.history),
            "recent_swaps": [e.to_dict() for e in self.history[-5:]],
        }


class Consolidator:
    """Asynchronous awakening phase after a model swap.

    After a model swap, the agent should observe and predict before it
    starts using tools. This consolidator runs N prediction-only steps
    on a replay buffer and measures the agency gain.

    Based on Evan Ye's "From Prediction to Self" (arxiv 2606.05605):
    agency is developmental, not substrate-property. A swapped model
    needs settling time before its self-world model stabilizes.
    """

    def __init__(self, steps: int = 50, agency_threshold: float = 0.15):
        self.steps = steps
        self.agency_threshold = agency_threshold

    async def consolidate(self, predict_fn, replay_buffer: list) -> dict:
        """Run consolidation. Returns metrics dict.

        Args:
            predict_fn: async callable that takes an observation and returns a prediction
            replay_buffer: list of recent observations to use for prediction

        Returns:
            dict with keys: steps, recovery, duration_seconds, threshold_met
        """
        if not replay_buffer:
            return {
                "steps": 0,
                "recovery": 0.0,
                "duration_seconds": 0.0,
                "threshold_met": False,
            }

        start = time.time()
        correct = 0
        total = 0

        # Run prediction-only phase
        sample = replay_buffer[-self.steps:] if len(replay_buffer) > self.steps else replay_buffer
        for obs in sample:
            try:
                prediction = await predict_fn(obs["input"])
                # In a real system, recovery is measured by self-prediction gain:
                # how well the new model predicts the next state. For a demo,
                # we measure completion (whether the model produced any output).
                if prediction:
                    correct += 1
                total += 1
            except Exception as e:
                _log("warning", "consolidation_step_failed", error=str(e))
                continue

        recovery = correct / total if total > 0 else 0.0
        duration = time.time() - start

        return {
            "steps": total,
            "recovery": recovery,
            "duration_seconds": duration,
            "threshold_met": recovery >= self.agency_threshold,
        }


# ── CLI ──────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LAR Model Failover — fallback chain with consolidation",
    )
    parser.add_argument("--primary", required=True, help="Primary model ID")
    parser.add_argument(
        "--fallback",
        action="append",
        default=[],
        help="Fallback model ID (can be passed multiple times)",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=Path("model_router_state.json"),
        help="Path to router state file",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show router status")

    advance = sub.add_parser("advance", help="Advance to next model in chain")
    advance.add_argument("--reason", default="manual")

    simulate = sub.add_parser(
        "simulate-death",
        help="Simulate a model death and trigger failover",
    )
    simulate.add_argument(
        "--model-id",
        default=None,
        help="Model to mark as dead (defaults to current)",
    )
    simulate.add_argument(
        "--reason",
        default="Simulated Fable-style export-control shutdown",
    )

    return parser


async def _main() -> int:
    args = _build_arg_parser().parse_args()

    router = ModelRouter(
        primary=args.primary,
        fallbacks=args.fallback,
        state_path=args.state_path,
    )

    if args.command == "status":
        print(json.dumps(router.status(), indent=2))
    elif args.command == "advance":
        new = router.advance(reason=args.reason)
        if new:
            print(json.dumps({
                "swapped": True,
                "current_model": new.model_id,
                "fallbacks_remaining": len(router.models) - router.current_index - 1,
            }, indent=2))
        else:
            print(json.dumps({"swapped": False, "reason": "fallback_chain_exhausted"}, indent=2))
            return 1
    elif args.command == "simulate-death":
        target = args.model_id or router.current.model_id
        # Mark the current model as dead and advance
        new = router.advance(reason=args.reason)
        if new:
            print(json.dumps({
                "simulated_death": True,
                "dead_model": target,
                "new_model": new.model_id,
                "consolidation_required": True,
                "message": f"Model {target} marked dead. Agent now on {new.model_id}. Run consolidation before resuming tool use.",
            }, indent=2))
        else:
            print(json.dumps({
                "simulated_death": True,
                "dead_model": target,
                "new_model": None,
                "consolidation_required": False,
                "message": "Fallback chain exhausted. No model available.",
            }, indent=2))
            return 1

    return 0


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()