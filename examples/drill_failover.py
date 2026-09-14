#!/usr/bin/env python3
"""Resilience drill: primary dies → fallback takes over → checkpoint resumes.

Combines FallbackBackend + CheckpointStore across a real process boundary.
No Ollama, no network — fake LLM backends only.

    python examples/drill_failover.py

Optional:
    LAR_EXAMPLE_DIR=/tmp/lar-demo python examples/drill_failover.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import structlog

from agent_resilience import (
    AgentState,
    CheckpointStore,
    FallbackBackend,
    LLMBackend,
    LLMResponse,
    Phase,
)

TASK_ID = "drill-failover"


def _silence_library_logs() -> None:
    logging.disable(logging.CRITICAL)

    def _drop(_logger: object, _method: str, _event_dict: dict) -> None:
        raise structlog.DropEvent

    structlog.configure(processors=[_drop], cache_logger_on_first_use=True)


class FakeLLMBackend(LLMBackend):
    """Minimal LLMBackend stand-in. Same pattern as tests/test_llm.py (no HTTP)."""

    def __init__(self, model: str, *, fail: bool = False, content: str = "") -> None:
        self.model = model
        self.fail = fail
        self.content = content

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        if self.fail:
            raise RuntimeError(f"{self.model} is dead (simulated export-control shutdown)")
        return LLMResponse(content=self.content, model=self.model)

    async def health_check(self) -> dict:
        if self.fail:
            return {"status": "unhealthy", "error": f"{self.model} unreachable"}
        return {"status": "healthy", "model_available": True, "target_model": self.model}

    async def close(self) -> None:
        return None


def _db_path() -> Path:
    raw = os.environ.get("LAR_CHECKPOINT_DB")
    if raw:
        return Path(raw)
    example_dir = Path(os.environ.get("LAR_EXAMPLE_DIR", tempfile.mkdtemp(prefix="lar-drill-")))
    example_dir.mkdir(parents=True, exist_ok=True)
    return example_dir / "drill.db"


async def run_until_crash(db_path: Path) -> int:
    """Failover, persist mid-task state, then exit (process death)."""
    _silence_library_logs()
    primary = FakeLLMBackend("cloud-primary", fail=True)
    fallback = FakeLLMBackend(
        "local-fallback",
        content="failover answer from local-fallback",
    )
    backend = FallbackBackend([primary, fallback], ["local-fallback"])

    print("[1] primary=cloud-primary dies; FallbackBackend tries local-fallback")
    try:
        response = await backend.chat([{"role": "user", "content": "continue the job"}])
    except Exception as exc:
        print(f"FAIL: fallback chain exhausted: {exc}", file=sys.stderr)
        return 1
    finally:
        await backend.close()

    if response.model != "local-fallback":
        print(f"FAIL: expected local-fallback, got {response.model!r}", file=sys.stderr)
        return 1
    print(f"[2] fallback served the request model={response.model}")

    store = CheckpointStore(db_path)
    state = AgentState(
        task_id=TASK_ID,
        step_number=1,
        phase=Phase.ACT,
        messages=[
            {"role": "user", "content": "continue the job"},
            {"role": "assistant", "content": response.content},
        ],
        model_used=response.model,
        checkpoint_reason="crash",
        is_complete=False,
        context={"failover": True},
    )
    checkpoint_id = await store.save(state)
    print(
        f"[3] checkpoint saved id={checkpoint_id} phase={state.phase.value} "
        f"model_used={state.model_used} pid={os.getpid()}"
    )
    print("[4] process exiting — simulated crash")
    return 0


async def resume_after_crash(db_path: Path) -> int:
    """New process: load the incomplete checkpoint and finish the task."""
    _silence_library_logs()
    store = CheckpointStore(db_path)
    latest = await store.latest_for_task(TASK_ID)
    if latest is None or latest.is_complete:
        print("FAIL: expected an incomplete checkpoint after crash", file=sys.stderr)
        return 1
    if latest.model_used != "local-fallback":
        print(f"FAIL: resume model should be local-fallback, got {latest.model_used!r}", file=sys.stderr)
        return 1

    print(
        f"[5] resumed pid={os.getpid()} checkpoint_id={latest.checkpoint_id} "
        f"phase={latest.phase.value} model_used={latest.model_used}"
    )

    latest.phase = Phase.RESPOND
    latest.step_number += 1
    latest.messages.append({"role": "assistant", "content": "finished after resume"})
    latest.is_complete = True
    latest.checkpoint_reason = "resume"
    await store.save(latest)

    print(
        f"[6] task complete checkpoint_id={latest.checkpoint_id} "
        f"phase={latest.phase.value} steps={latest.step_number}"
    )
    print("SUCCESS: drill complete — failover + resume after process death")
    return 0


def orchestrate(db_path: Path) -> int:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["LAR_DRILL_MODE"] = "run"
    env["LAR_CHECKPOINT_DB"] = str(db_path)
    print(f"[SETUP] offline drill db={db_path}", flush=True)
    ran = subprocess.run([sys.executable, __file__], env=env, check=False)
    if ran.returncode != 0:
        print("FAIL: failover/save process did not exit 0", file=sys.stderr)
        return ran.returncode

    env["LAR_DRILL_MODE"] = "resume"
    resumed = subprocess.run([sys.executable, __file__], env=env, check=False)
    return resumed.returncode


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    mode = os.environ.get("LAR_DRILL_MODE", "orchestrate")
    db_path = _db_path()
    if mode == "run":
        return asyncio.run(run_until_crash(db_path))
    if mode == "resume":
        return asyncio.run(resume_after_crash(db_path))
    return orchestrate(db_path)


if __name__ == "__main__":
    sys.exit(main())
