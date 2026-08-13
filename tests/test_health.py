"""Tests for agent_resilience.health — HealthMonitor and health checks.

Covers: individual checks (ollama, tools, checkpoint, identity, disk, cron),
aggregated report, misfire tracking, session counting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_resilience.checkpoint import CheckpointStore
from agent_resilience.config import ModelConfig, RuntimeConfig
from agent_resilience.health import (
    CheckResult,
    HealthMonitor,
    HealthReport,
    HealthStatus,
)


@pytest.fixture
def config():
    return RuntimeConfig(
        agent_id="health-agent",
        agent_name="Health Agent",
        session_key="session:health:main",
        model=ModelConfig(model="test-model", base_url="http://localhost:11434"),
    )


@pytest.fixture
def monitor(config):
    return HealthMonitor(config)


@pytest.fixture
def monitor_with_store(config, tmp_path):
    store = CheckpointStore(tmp_path / "health_checkpoints.db")
    return HealthMonitor(config, checkpoint_store=store)


class TestHealthStatus:
    def test_enum_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"


class TestCheckResult:
    def test_to_dict(self):
        cr = CheckResult(
            name="test_check",
            status=HealthStatus.HEALTHY,
            details={"key": "value"},
            latency_ms=12.5,
        )
        d = cr.to_dict()
        assert d["name"] == "test_check"
        assert d["status"] == "healthy"
        assert d["details"] == {"key": "value"}
        assert d["latency_ms"] == 12.5
        assert d["error"] is None

    def test_to_dict_with_error(self):
        cr = CheckResult(
            name="failed_check",
            status=HealthStatus.UNHEALTHY,
            error="something broke",
        )
        d = cr.to_dict()
        assert d["error"] == "something broke"


class TestHealthReport:
    def test_to_dict(self):
        checks = [
            CheckResult(name="c1", status=HealthStatus.HEALTHY),
            CheckResult(name="c2", status=HealthStatus.DEGRADED),
        ]
        report = HealthReport(
            overall=HealthStatus.DEGRADED,
            checks=checks,
            agent_id="test-agent",
        )
        d = report.to_dict()
        assert d["overall"] == "degraded"
        assert d["agent_id"] == "test-agent"
        assert len(d["checks"]) == 2

    def test_to_json(self):
        report = HealthReport(
            overall=HealthStatus.HEALTHY,
            checks=[],
            agent_id="test",
        )
        j = report.to_json()
        import json
        data = json.loads(j)
        assert data["overall"] == "healthy"


class TestHealthMonitorChecks:
    async def test_check_ollama_healthy(self, monitor):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "test-model:latest"}]}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await monitor.check_ollama()

        assert result.status == HealthStatus.HEALTHY
        assert result.details["models_available"] == 1

    async def test_check_ollama_unhealthy(self, monitor):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await monitor.check_ollama()

        assert result.status == HealthStatus.UNHEALTHY
        assert "connection refused" in result.error

    async def test_check_tools_healthy(self, monitor):
        result = await monitor.check_tools()
        assert result.status == HealthStatus.HEALTHY
        assert "exec" in result.details["tools"]
        assert result.details["tools_registered"] >= 5

    async def test_check_checkpoint_store_no_store(self, monitor):
        result = await monitor.check_checkpoint_store()
        assert result.status == HealthStatus.UNKNOWN
        assert "no checkpoint_store" in result.details["reason"]

    async def test_check_checkpoint_store_healthy(self, monitor_with_store):
        result = await monitor_with_store.check_checkpoint_store()
        assert result.status == HealthStatus.HEALTHY
        assert "incomplete_tasks" in result.details

    async def test_check_identity_validator_healthy(self, monitor):
        result = await monitor.check_identity_validator()
        assert result.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)
        assert "agent_id" in result.details

    async def test_check_disk_space(self, monitor):
        result = await monitor.check_disk_space()
        assert result.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)
        assert "total_gb" in result.details
        assert "free_gb" in result.details
        assert "used_percent" in result.details

    async def test_check_cron_misfires_no_misfires(self, monitor):
        result = await monitor.check_cron_misfires()
        assert result.status == HealthStatus.HEALTHY
        assert result.details["recent_misfires"] == 0

    async def test_check_cron_misfires_with_misfires(self, monitor):
        monitor.record_misfire("cron-1", "expected-agent", "wrong-session")
        result = await monitor.check_cron_misfires()
        assert result.status == HealthStatus.DEGRADED
        assert result.details["recent_misfires_24h"] == 1

    async def test_check_cron_misfires_multiple(self, monitor):
        monitor.record_misfire("cron-1", "expected", "wrong-1")
        monitor.record_misfire("cron-2", "expected", "wrong-2")
        result = await monitor.check_cron_misfires()
        assert result.status == HealthStatus.UNHEALTHY
        assert result.details["recent_misfires_24h"] == 2


class TestHealthMonitorAggregation:
    async def test_run_all_checks_returns_report(self, monitor):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"models": []}
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            report = await monitor.run_all_checks()

        assert isinstance(report, HealthReport)
        assert len(report.checks) == 6
        assert report.agent_id == "health-agent"
        assert report.uptime_seconds >= 0

    async def test_overall_status_unhealthy_when_any_unhealthy(self, monitor):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("down"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            report = await monitor.run_all_checks()

        # Ollama check will be unhealthy → overall should be unhealthy
        assert report.overall == HealthStatus.UNHEALTHY

    async def test_session_count_tracking(self, monitor):
        assert monitor._session_count == 0
        monitor.record_session_created()
        monitor.record_session_created()
        assert monitor._session_count == 2
