"""Model failover router and post-swap consolidator."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import structlog

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )
    logger = structlog.get_logger("agent_resilience.router")
    _HAS_STRUCTLOG = True
except Exception:  # pragma: no cover - stdlib fallback
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logger = logging.getLogger("agent_resilience.router")
    _HAS_STRUCTLOG = False


def _log(level: str, msg: str, **kwargs) -> None:
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
    consolidation_recovery: float
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
    """Pluggable model selection with a persisted fallback chain."""

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
        self.state_path = Path(state_path) if state_path else Path("model_router_state.json")
        self.history: list[SwapEvent] = []
        self.current_index = 0
        self._load_state()

    def _load_state(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.current_index = data.get("current_index", 0)
                self.history = [SwapEvent(**e) for e in data.get("history", [])]
                _log(
                    "info",
                    "router_state_loaded",
                    current_index=self.current_index,
                    history_count=len(self.history),
                )
            except Exception as e:
                _log("warning", "router_state_load_failed", error=str(e))

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
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

    def select(self, task_input: str | None = None) -> ModelConfig:
        """Return the active model. task_input is reserved for future routing."""
        del task_input
        return self.current

    def all_models(self) -> list[str]:
        return [m.model_id for m in self.models]

    def has_fallback(self) -> bool:
        return self.current_index < len(self.models) - 1

    def advance(self, reason: str = "model_failure") -> Optional[ModelConfig]:
        """Advance to the next model. Returns the new model, or None if exhausted."""
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
        """Record consolidation metrics for the most recent swap."""
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
        return {
            "current_model": self.current.model_id,
            "current_index": self.current_index,
            "fallback_chain": self.all_models(),
            "fallbacks_remaining": len(self.models) - self.current_index - 1,
            "swap_count": len(self.history),
            "recent_swaps": [e.to_dict() for e in self.history[-5:]],
        }


class Consolidator:
    """Prediction-only settling phase after a model swap.

    Recovery here is a completion metric (did predict_fn return truthy),
    not a claim of measured agency gain.
    """

    def __init__(self, steps: int = 50, agency_threshold: float = 0.15):
        self.steps = steps
        self.agency_threshold = agency_threshold

    async def consolidate(self, predict_fn, replay_buffer: list) -> dict:
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

        sample = replay_buffer[-self.steps :] if len(replay_buffer) > self.steps else replay_buffer
        for obs in sample:
            try:
                prediction = await predict_fn(obs["input"])
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
