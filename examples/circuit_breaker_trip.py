#!/usr/bin/env python3
"""Circuit breaker trips on foreign-payload contamination.

Two misfires (wrong agent_id) open the circuit. After that, even a valid
payload is rejected until reset. State is written to a temp file — never /tmp
world-writable defaults, never your real $XDG_STATE_HOME/lar/.

Offline: stdlib + CircuitBreaker. No Ollama, no network.

    python examples/circuit_breaker_trip.py

Optional:
    LAR_EXAMPLE_DIR=/tmp/lar-demo python examples/circuit_breaker_trip.py
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import structlog

from agent_resilience import CircuitBreaker, CircuitBreakerConfig, CircuitState


def _silence_library_logs() -> None:
    logging.disable(logging.CRITICAL)

    def _drop(_logger: object, _method: str, _event_dict: dict) -> None:
        raise structlog.DropEvent

    structlog.configure(processors=[_drop], cache_logger_on_first_use=True)


def _state_file() -> Path:
    example_dir = Path(os.environ.get("LAR_EXAMPLE_DIR", tempfile.mkdtemp(prefix="lar-circuit-")))
    example_dir.mkdir(parents=True, exist_ok=True)
    return example_dir / "circuit.json"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    _silence_library_logs()
    state_file = _state_file()
    breaker = CircuitBreaker(
        agent_id="gabriel",
        config=CircuitBreakerConfig(failure_threshold=2, enabled=True),
        state_file=state_file,
    )

    own = {"agent_id": "gabriel", "cron_id": "cron-own", "type": "cron"}
    foreign = {"agent_id": "harry", "cron_id": "cron-foreign", "type": "cron"}

    print(f"[SETUP] agent_id=gabriel threshold=2 state={state_file}")

    ok, reason = breaker.evaluate(own)
    if not ok:
        print(f"FAIL: own payload rejected while CLOSED: {reason}", file=sys.stderr)
        return 1
    print("[CLOSED] own payload accepted")

    ok, reason = breaker.evaluate(foreign)
    if ok or breaker.state != CircuitState.CLOSED:
        print(f"FAIL: first misfire should reject without tripping: {reason}", file=sys.stderr)
        return 1
    print(f"[MISFIRE 1] rejected ({reason}); circuit still {breaker.state.value}")

    ok, reason = breaker.evaluate(foreign)
    if breaker.state != CircuitState.OPEN:
        print(f"FAIL: expected OPEN after threshold, got {breaker.state.value}", file=sys.stderr)
        return 1
    print(f"[MISFIRE 2] circuit {breaker.state.value} — {reason}")

    ok, reason = breaker.evaluate(own)
    if ok:
        print("FAIL: own payload should be rejected while OPEN", file=sys.stderr)
        return 1
    print(f"[OPEN] own payload rejected: {reason}")

    status = breaker.get_status()
    print(
        f"[STATUS] state={status['state']} failures={status['failure_count']} "
        f"recent_misfires_24h={status['recent_misfires_24h']}"
    )
    print("SUCCESS: circuit breaker tripped on contamination")
    return 0


if __name__ == "__main__":
    sys.exit(main())
