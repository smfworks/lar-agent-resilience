"""
LAR — Circuit Breaker Module

Defense against session routing misfires (inspired by Harry→Gabriel incident).

If an agent receives more than one foreign cron payload in a 24h window,
the circuit breaker trips and auto-disables all further cron processing
until manually reset.

Inspired by the Dawn Circle discussion: "The gap between what's written
and what happens in practice is the place where agents break."
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger("lar.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Tripped — rejecting all cron payloads
    HALF_OPEN = "half_open"  # Testing if service is restored


@dataclass
class CircuitBreakerConfig:
    """Configuration for the circuit breaker."""

    failure_threshold: int = 2          # Foreign payloads before trip
    recovery_timeout_seconds: int = 3600  # Auto-reset after 1 hour
    half_open_max_attempts: int = 1   # Max test requests in half-open
    enabled: bool = True


@dataclass
class MisfireEvent:
    """Record of a detected session misfire."""

    timestamp: str
    cron_id: str
    expected_agent_id: str
    actual_agent_id: str
    payload_type: str = "cron"
    reason: str = "agent_id_mismatch"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cron_id": self.cron_id,
            "expected_agent_id": self.expected_agent_id,
            "actual_agent_id": self.actual_agent_id,
            "payload_type": self.payload_type,
            "reason": self.reason,
        }


def default_state_file(agent_id: str) -> Path:
    """Per-user state path. Never /tmp — world-writable and wiped on reboot."""
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in agent_id)
    safe = safe.strip("._") or "agent"
    root = os.environ.get("XDG_STATE_HOME")
    base = Path(root) if root else Path.home() / ".local" / "state"
    return base / "lar" / f"circuit_{safe}.json"


class CircuitBreaker:
    """Protects agent from foreign payload contamination."""

    def __init__(
        self,
        agent_id: str,
        config: CircuitBreakerConfig | None = None,
        state_file: Path | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.config = config or CircuitBreakerConfig()
        self.state_file = Path(state_file) if state_file else default_state_file(agent_id)
        self.state = CircuitState.CLOSED
        self.misfires: list[MisfireEvent] = []
        self._failure_count = 0
        self._last_failure_time: datetime | None = None
        self._half_open_attempts = 0
        self._load_state()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Exclusive flock around load/save. Best-effort if fcntl is missing."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_file.with_name(self.state_file.name + ".lock")
        with open(lock_path, "a+", encoding="utf-8") as lock_fh:
            try:
                import fcntl

                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError) as exc:
                logger.debug("circuit_lock_unavailable", error=str(exc))
            try:
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass

    def _load_state(self) -> None:
        """Load persisted circuit state."""
        if not self.state_file.exists():
            return
        try:
            with self._locked(), open(self.state_file, encoding="utf-8") as f:
                data = json.load(f)
            self.state = CircuitState(data.get("state", "closed"))
            self.misfires = [MisfireEvent(**m) for m in data.get("misfires", [])]
            self._failure_count = data.get("failure_count", 0)
            self._last_failure_time = (
                datetime.fromisoformat(data["last_failure_time"])
                if data.get("last_failure_time")
                else None
            )
            logger.debug("circuit_state_loaded", state=self.state.value)
        except Exception as e:
            logger.warning("circuit_state_load_failed", error=str(e))

    def _save_state(self) -> None:
        """Persist circuit state atomically (tmp + replace) under flock."""
        try:
            data = {
                "state": self.state.value,
                "misfires": [m.to_dict() for m in self.misfires[-50:]],
                "failure_count": self._failure_count,
                "last_failure_time": (
                    self._last_failure_time.isoformat() if self._last_failure_time else None
                ),
                "timestamp": datetime.utcnow().isoformat(),
            }
            payload = json.dumps(data, indent=2)
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with self._locked():
                fd, tmp_name = tempfile.mkstemp(
                    prefix=self.state_file.name + ".",
                    suffix=".tmp",
                    dir=self.state_file.parent,
                    text=True,
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                        tmp.write(payload)
                        tmp.flush()
                        os.fsync(tmp.fileno())
                    os.chmod(tmp_name, 0o600)
                    os.replace(tmp_name, self.state_file)
                except Exception:
                    with suppress(OSError):
                        os.unlink(tmp_name)
                    raise
        except Exception as e:
            logger.warning("circuit_state_save_failed", error=str(e))

    def evaluate(self, payload: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Evaluate if a payload should be accepted.

        Returns:
            (accepted: bool, reason: str | None)
        """
        if not self.config.enabled:
            return True, None

        # Check if circuit is OPEN
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                self._half_open_attempts = 0
                logger.info("circuit_entered_half_open", agent_id=self.agent_id)
                self._save_state()
            else:
                logger.warning(
                    "circuit_open_payload_rejected",
                    agent_id=self.agent_id,
                    cron_id=payload.get("cron_id", "unknown"),
                )
                return False, f"Circuit breaker OPEN for {self.agent_id}"

        # Validate payload agent id (snake_case or camelCase — same contract as identity)
        payload_agent = payload.get("agent_id") or payload.get("agentId") or ""
        if payload_agent and payload_agent != self.agent_id:
            # Foreign payload detected
            self._record_misfire(payload)

            if self.state == CircuitState.HALF_OPEN:
                self._half_open_attempts += 1
                if self._half_open_attempts >= self.config.half_open_max_attempts:
                    # Still getting misfires — trip again
                    self._trip()
                    return False, f"Circuit breaker re-tripped for {self.agent_id}"
                else:
                    # Allow one test through
                    return True, None

            return False, f"Foreign payload rejected: expected {self.agent_id}, got {payload_agent}"

        # Valid payload
        if self.state == CircuitState.HALF_OPEN:
            # Success in half-open — close the circuit
            self._close()

        return True, None

    def _record_misfire(self, payload: dict[str, Any]) -> None:
        """Record a misfire and check if we should trip."""
        event = MisfireEvent(
            timestamp=datetime.utcnow().isoformat(),
            cron_id=payload.get("cron_id", "unknown"),
            expected_agent_id=self.agent_id,
            actual_agent_id=payload.get("agent_id") or payload.get("agentId") or "unknown",
            payload_type=payload.get("type", "cron"),
            reason=payload.get("reason", "agent_id_mismatch"),
        )
        self.misfires.append(event)
        self._failure_count += 1
        self._last_failure_time = datetime.utcnow()

        logger.warning(
            "misfire_detected",
            expected=self.agent_id,
            actual=event.actual_agent_id,
            cron_id=event.cron_id,
            failure_count=self._failure_count,
        )

        if self._failure_count >= self.config.failure_threshold:
            self._trip()

        self._save_state()

    def _trip(self) -> None:
        """Trip the circuit breaker."""
        self.state = CircuitState.OPEN
        logger.critical(
            "circuit_breaker_tripped",
            agent_id=self.agent_id,
            failure_count=self._failure_count,
            threshold=self.config.failure_threshold,
        )
        self._save_state()

    def _close(self) -> None:
        """Close the circuit breaker (reset to normal)."""
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_attempts = 0
        logger.info("circuit_breaker_closed", agent_id=self.agent_id)
        self._save_state()

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self._last_failure_time:
            return True
        elapsed = (datetime.utcnow() - self._last_failure_time).total_seconds()
        return elapsed >= self.config.recovery_timeout_seconds

    def manual_reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._close()
        logger.info("circuit_breaker_manually_reset", agent_id=self.agent_id)

    def get_status(self) -> dict:
        """Return current circuit breaker status."""
        recent_misfires = [
            m for m in self.misfires
            if (datetime.utcnow() - datetime.fromisoformat(m.timestamp)).total_seconds() < 86400
        ]
        return {
            "state": self.state.value,
            "agent_id": self.agent_id,
            "failure_count": self._failure_count,
            "failure_threshold": self.config.failure_threshold,
            "recent_misfires_24h": len(recent_misfires),
            "total_misfires": len(self.misfires),
            "last_failure": self._last_failure_time.isoformat() if self._last_failure_time else None,
            "recovery_timeout_seconds": self.config.recovery_timeout_seconds,
        }
