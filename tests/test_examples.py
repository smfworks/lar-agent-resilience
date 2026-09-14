"""Smoke-run the offline examples/ scripts.

Newcomers clone, `pip install -e .`, and run these without Ollama or network.
CI already runs pytest, so this wires the examples into the existing suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"

SCRIPTS = [
    ("fallback_primary_dies.py", "SUCCESS: primary died; fallback served the request"),
    ("checkpoint_resume.py", "SUCCESS: checkpoint survived process death"),
    ("circuit_breaker_trip.py", "SUCCESS: circuit breaker tripped on contamination"),
    ("drill_failover.py", "SUCCESS: drill complete — failover + resume after process death"),
]


@pytest.mark.parametrize(("script", "needle"), SCRIPTS)
def test_example_script_offline(script: str, needle: str, tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["LAR_EXAMPLE_DIR"] = str(tmp_path)
    env["LAR_CHECKPOINT_DB"] = str(tmp_path / "checkpoints.db")
    result = subprocess.run(
        [sys.executable, str(EXAMPLES / script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert needle in result.stdout, output
