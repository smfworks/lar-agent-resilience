"""Tests for agent_resilience.model_lifecycle — ModelLifecycle and ModelRecord.

Covers: register/update, deprecation, health checks, Fable simulation,
state persistence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_resilience.model_lifecycle import ModelLifecycle, ModelRecord


@pytest.fixture
def lifecycle(tmp_path: Path) -> ModelLifecycle:
    return ModelLifecycle(state_path=tmp_path / "lifecycle.json")


class TestModelRecord:
    def test_defaults(self):
        rec = ModelRecord(
            model_id="test-model",
            provider="ollama",
            status="active",
            first_seen_at="2026-01-01T00:00:00",
            last_seen_at="2026-01-01T00:00:00",
        )
        assert rec.model_id == "test-model"
        assert rec.provider == "ollama"
        assert rec.status == "active"
        assert rec.last_price_check_at is None
        assert rec.deprecation_notice_at is None
        assert rec.estimated_eol_at is None
        assert rec.notes == []


class TestModelLifecycle:
    def test_register_new_model(self, lifecycle):
        rec = lifecycle.register_or_update("new-model", provider="ollama")
        assert rec.model_id == "new-model"
        assert rec.provider == "ollama"
        assert rec.status == "active"
        assert "new-model" in lifecycle.models

    def test_register_with_note(self, lifecycle):
        rec = lifecycle.register_or_update("noted-model", provider="ollama", note="Initial registration")
        assert len(rec.notes) == 1
        assert "Initial registration" in rec.notes[0]

    def test_update_existing_model(self, lifecycle):
        lifecycle.register_or_update("existing-model", provider="ollama")
        rec = lifecycle.register_or_update("existing-model", provider="ollama", status="deprecated")
        assert rec.status == "deprecated"
        assert len(rec.notes) >= 1  # Should have a status change note

    def test_update_with_price_check(self, lifecycle):
        lifecycle.register_or_update("priced-model", provider="ollama")
        rec = lifecycle.register_or_update("priced-model", provider="ollama", price_check=True)
        assert rec.last_price_check_at is not None

    def test_mark_deprecated(self, lifecycle):
        lifecycle.register_or_update("deprecate-me", provider="ollama")
        rec = lifecycle.mark_deprecated("deprecate-me", estimated_eol_at="2026-12-31")
        assert rec is not None
        assert rec.status == "deprecated"
        assert rec.estimated_eol_at == "2026-12-31"
        assert rec.deprecation_notice_at is not None

    def test_mark_deprecated_unknown_model(self, lifecycle):
        result = lifecycle.mark_deprecated("nonexistent")
        assert result is None

    def test_check_health_empty(self, lifecycle):
        report = lifecycle.check_health()
        assert report["healthy"] is True
        assert report["alerts"] == []
        assert report["summary"]["active"] == []

    def test_check_health_with_active_model(self, lifecycle):
        lifecycle.register_or_update("active-model", provider="ollama", status="active")
        report = lifecycle.check_health()
        assert "active-model" in report["summary"]["active"]
        assert report["healthy"] is True

    def test_check_health_with_deprecated_model(self, lifecycle):
        lifecycle.register_or_update("dep-model", provider="ollama", status="active")
        lifecycle.mark_deprecated("dep-model")
        report = lifecycle.check_health()
        assert "dep-model" in report["summary"]["deprecated"]
        assert report["healthy"] is False  # deprecated triggers warning alert

    def test_check_health_with_eol_alert(self, lifecycle):
        lifecycle.register_or_update("eol-model", provider="ollama", status="active")
        lifecycle.mark_deprecated("eol-model", estimated_eol_at="2026-08-14")  # near EOL
        report = lifecycle.check_health()
        assert len(report["alerts"]) >= 1
        # Should have a critical or warning alert about EOL
        eol_alerts = [a for a in report["alerts"] if "EOL" in a["message"]]
        assert len(eol_alerts) >= 1

    def test_state_persistence(self, tmp_path: Path):
        state_path = tmp_path / "persist_lifecycle.json"
        lc1 = ModelLifecycle(state_path=state_path)
        lc1.register_or_update("persist-model", provider="ollama")

        # New instance should load state
        lc2 = ModelLifecycle(state_path=state_path)
        assert "persist-model" in lc2.models
        assert lc2.models["persist-model"].provider == "ollama"

    def test_simulate_fable_deprecation(self, lifecycle):
        result = lifecycle.simulate_fable_deprecation(model_id="fable-model", days_until_eol=7)
        assert result["simulated"] is True
        assert result["model_id"] == "fable-model"
        assert result["days_until_eol"] == 7
        assert result["record"] is not None
        assert result["record"]["status"] == "deprecated"

    def test_simulate_fable_deprecation_existing_model(self, lifecycle):
        lifecycle.register_or_update("existing-sim", provider="openai", status="active")
        result = lifecycle.simulate_fable_deprecation(model_id="existing-sim", days_until_eol=3)
        assert result["simulated"] is True
        assert result["record"]["status"] == "deprecated"

    def test_corrupt_state_handled(self, tmp_path: Path):
        state_path = tmp_path / "corrupt_lifecycle.json"
        state_path.write_text("not valid json {{{")
        lc = ModelLifecycle(state_path=state_path)
        assert lc.models == {}

    def test_check_health_with_unavailable_model(self, lifecycle):
        lifecycle.register_or_update("unavail-model", provider="ollama", status="unavailable")
        report = lifecycle.check_health()
        assert "unavail-model" in report["summary"]["unavailable"]

    def test_check_health_with_drift_detected(self, lifecycle):
        lifecycle.register_or_update("drift-model", provider="ollama", status="drift_detected")
        report = lifecycle.check_health()
        assert "drift-model" in report["summary"]["drift_detected"]