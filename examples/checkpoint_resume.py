#!/usr/bin/env python3
"""Checkpoint save/resume across real process death.

Process A writes an incomplete AgentState to SQLite and exits.
Process B opens the same DB and continues from the last step.

Offline: stdlib + CheckpointStore. No Ollama, no network.

    python examples/checkpoint_resume.py

Optional:
    LAR_EXAMPLE_DIR=/tmp/lar-demo python examples/checkpoint_resume.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_resilience import AgentState, CheckpointStore, Phase

TASK_ID = "checkpoint-demo"


async def save_and_die(db_path: Path) -> int:
    store = CheckpointStore(db_path)
    state = AgentState(
        task_id=TASK_ID,
        step_number=2,
        phase=Phase.THINK,
        messages=[
            {"role": "user", "content": "review the failover patch"},
            {"role": "assistant", "content": "drafting a plan..."},
        ],
        context={"note": "saved mid-think before crash"},
        model_used="local-fallback",
        checkpoint_reason="crash",
        is_complete=False,
    )
    checkpoint_id = await store.save(state)
    print(
        f"[SAVE] pid={os.getpid()} checkpoint_id={checkpoint_id} "
        f"phase={state.phase.value} step={state.step_number}"
    )
    print("[DEATH] saver process exiting (simulated crash)")
    return 0


async def resume_after_death(db_path: Path) -> int:
    store = CheckpointStore(db_path)
    latest = await store.latest_for_task(TASK_ID)
    if latest is None:
        print("FAIL: no checkpoint found after process death", file=sys.stderr)
        return 1
    if latest.is_complete:
        print("FAIL: expected an incomplete checkpoint", file=sys.stderr)
        return 1

    print(
        f"[RESUME] pid={os.getpid()} loaded checkpoint_id={latest.checkpoint_id} "
        f"phase={latest.phase.value} step={latest.step_number}"
    )
    print(f"[RESUME] messages={len(latest.messages)} model_used={latest.model_used!r}")

    latest.phase = Phase.RESPOND
    latest.step_number += 1
    latest.messages.append({"role": "assistant", "content": "resumed after crash"})
    latest.is_complete = True
    latest.checkpoint_reason = "resume"
    await store.save(latest)

    reloaded = await store.load(latest.checkpoint_id)
    if reloaded is None or not reloaded.is_complete:
        print("FAIL: resumed state did not persist", file=sys.stderr)
        return 1
    if reloaded.phase != Phase.RESPOND:
        print(f"FAIL: expected phase=respond, got {reloaded.phase}", file=sys.stderr)
        return 1

    print(
        f"[DONE]  checkpoint_id={reloaded.checkpoint_id} "
        f"phase={reloaded.phase.value} complete={reloaded.is_complete}"
    )
    print("SUCCESS: checkpoint survived process death")
    return 0


def _db_path() -> Path:
    raw = os.environ.get("LAR_CHECKPOINT_DB")
    if raw:
        return Path(raw)
    example_dir = Path(os.environ.get("LAR_EXAMPLE_DIR", tempfile.mkdtemp(prefix="lar-checkpoint-")))
    example_dir.mkdir(parents=True, exist_ok=True)
    return example_dir / "checkpoints.db"


def orchestrate(db_path: Path) -> int:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["LAR_CHECKPOINT_MODE"] = "save"
    env["LAR_CHECKPOINT_DB"] = str(db_path)
    print(f"[SETUP] db={db_path}", flush=True)
    saved = subprocess.run([sys.executable, __file__], env=env, check=False)
    if saved.returncode != 0:
        print("FAIL: saver process did not exit 0", file=sys.stderr)
        return saved.returncode

    env["LAR_CHECKPOINT_MODE"] = "resume"
    resumed = subprocess.run([sys.executable, __file__], env=env, check=False)
    return resumed.returncode


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    mode = os.environ.get("LAR_CHECKPOINT_MODE", "orchestrate")
    db_path = _db_path()
    if mode == "save":
        return asyncio.run(save_and_die(db_path))
    if mode == "resume":
        return asyncio.run(resume_after_death(db_path))
    return orchestrate(db_path)


if __name__ == "__main__":
    sys.exit(main())
