"""Pytest configuration and fixtures shared across all test modules."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_state_file(tmp_path: Path) -> Path:
    """Return a path for a temporary state file."""
    return tmp_path / "state.json"


@pytest.fixture(autouse=True)
def _clean_env():
    """Clean up test-specific env vars before and after each test."""
    # Save and restore env vars that tests might set
    saved = {}
    test_vars = [
        "TEST_AGENT_ID",
        "TEST_BASE_URL",
        "NONEXISTENT_VAR_12345",
        "UNSET_VAR_99999",
    ]
    for var in test_vars:
        if var in os.environ:
            saved[var] = os.environ[var]
        os.environ.pop(var, None)

    yield

    # Restore
    for var, val in saved.items():
        os.environ[var] = val
    for var in test_vars:
        os.environ.pop(var, None)
