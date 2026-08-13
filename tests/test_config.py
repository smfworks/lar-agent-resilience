"""Tests for agent_resilience.config — ConfigManager and RuntimeConfig.

Covers: YAML loading, env-var substitution, Pydantic validation,
default values, error cases, and the config property.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_resilience.config import (
    ConfigManager,
    RuntimeConfig,
    ModelConfig,
    ToolConfig,
    MemoryConfig,
    IdentityConfig,
    CircuitBreakerConfigModel,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def sample_yaml(tmp_path: Path) -> Path:
    """Write a minimal valid config YAML."""
    config = """
agent_id: "test-agent"
agent_name: "Test Agent"
session_key: "session:test:main"
workspace_dir: "/tmp/test_workspace"

model:
  provider: "ollama"
  model: "test-model"
  base_url: "http://localhost:11434"
  timeout: 60.0
  max_retries: 2
  fallbacks:
    - "fallback-1"
    - "fallback-2"

memory:
  short_term_limit: 20
  vault_path: "~/test_vault"
  embedding_provider: "ollama"
  embedding_model: "nomic-embed-text"

identity:
  enabled: true
  hmac_secret: "test-secret"
  max_payload_age_seconds: 600
  strict_session_key: true

circuit_breaker:
  failure_threshold: 3
  recovery_timeout_seconds: 1800
  enabled: true

tools:
  - name: "exec"
    enabled: true
    config:
      allowed_commands: ["ls", "cat"]

log_level: "debug"
log_format: "console"
"""
    path = tmp_path / "config.yaml"
    path.write_text(config)
    return path


@pytest.fixture
def minimal_yaml(tmp_path: Path) -> Path:
    """Write a minimal config with only required fields."""
    config = """
agent_id: "minimal-agent"
agent_name: "Minimal"
session_key: "session:minimal:main"
"""
    path = tmp_path / "minimal.yaml"
    path.write_text(config)
    return path


# ── RuntimeConfig validation tests ───────────────────────────────────────


class TestRuntimeConfig:
    def test_valid_config(self):
        cfg = RuntimeConfig(
            agent_id="agent-1",
            agent_name="Agent One",
            session_key="session:1:main",
        )
        assert cfg.agent_id == "agent-1"
        assert cfg.agent_name == "Agent One"
        assert cfg.session_key == "session:1:main"
        assert cfg.workspace_dir == Path(".")

    def test_defaults_are_populated(self):
        cfg = RuntimeConfig(
            agent_id="a1", agent_name="A", session_key="sk"
        )
        assert isinstance(cfg.model, ModelConfig)
        assert isinstance(cfg.memory, MemoryConfig)
        assert isinstance(cfg.identity, IdentityConfig)
        assert isinstance(cfg.circuit_breaker, CircuitBreakerConfigModel)
        assert cfg.tools == []
        assert cfg.log_level == "INFO"
        assert cfg.log_format == "json"

    def test_log_level_uppercased(self):
        cfg = RuntimeConfig(
            agent_id="a", agent_name="A", session_key="s", log_level="debug"
        )
        assert cfg.log_level == "DEBUG"

    def test_log_level_invalid(self):
        with pytest.raises(ValidationError):
            RuntimeConfig(
                agent_id="a", agent_name="A", session_key="s", log_level="BOGUS"
            )

    def test_log_format_lowercased(self):
        cfg = RuntimeConfig(
            agent_id="a", agent_name="A", session_key="s", log_format="JSON"
        )
        assert cfg.log_format == "json"

    def test_log_format_invalid(self):
        with pytest.raises(ValidationError):
            RuntimeConfig(
                agent_id="a", agent_name="A", session_key="s", log_format="xml"
            )

    def test_agent_id_empty_rejected(self):
        with pytest.raises(ValidationError):
            RuntimeConfig(agent_id="", agent_name="A", session_key="s")

    def test_agent_id_whitespace_stripped(self):
        cfg = RuntimeConfig(agent_id="  spaced  ", agent_name="A", session_key="s")
        assert cfg.agent_id == "spaced"


class TestModelConfig:
    def test_defaults(self):
        mc = ModelConfig()
        assert mc.provider == "ollama"
        assert mc.model == "kimi-k2.6"
        assert mc.timeout == 120.0
        assert mc.max_retries == 3
        assert mc.fallbacks == []

    def test_timeout_must_be_positive(self):
        with pytest.raises(ValidationError):
            ModelConfig(timeout=0)

    def test_timeout_negative_rejected(self):
        with pytest.raises(ValidationError):
            ModelConfig(timeout=-1.0)

    def test_max_retries_non_negative(self):
        with pytest.raises(ValidationError):
            ModelConfig(max_retries=-1)

    def test_max_retries_zero_ok(self):
        mc = ModelConfig(max_retries=0)
        assert mc.max_retries == 0


class TestMemoryConfig:
    def test_defaults(self):
        mc = MemoryConfig()
        assert mc.short_term_limit == 10

    def test_short_term_limit_must_be_positive(self):
        with pytest.raises(ValidationError):
            MemoryConfig(short_term_limit=0)

    def test_short_term_limit_negative_rejected(self):
        with pytest.raises(ValidationError):
            MemoryConfig(short_term_limit=-5)


class TestIdentityConfig:
    def test_defaults(self):
        ic = IdentityConfig()
        assert ic.enabled is True
        assert ic.hmac_secret is None
        assert ic.max_payload_age_seconds == 300
        assert ic.strict_session_key is True

    def test_max_payload_age_must_be_positive(self):
        with pytest.raises(ValidationError):
            IdentityConfig(max_payload_age_seconds=0)


class TestToolConfig:
    def test_defaults(self):
        tc = ToolConfig(name="exec")
        assert tc.name == "exec"
        assert tc.enabled is True
        assert tc.module == ""
        assert tc.config == {}


# ── ConfigManager tests ──────────────────────────────────────────────────


class TestConfigManager:
    def test_load_full_config(self, sample_yaml: Path):
        cm = ConfigManager(sample_yaml)
        cfg = cm.load()
        assert cfg.agent_id == "test-agent"
        assert cfg.agent_name == "Test Agent"
        assert cfg.session_key == "session:test:main"
        assert cfg.model.model == "test-model"
        assert cfg.model.timeout == 60.0
        assert cfg.model.fallbacks == ["fallback-1", "fallback-2"]
        assert cfg.memory.short_term_limit == 20
        assert cfg.identity.hmac_secret == "test-secret"
        assert cfg.circuit_breaker.failure_threshold == 3
        assert len(cfg.tools) == 1
        assert cfg.tools[0].name == "exec"
        assert cfg.log_level == "DEBUG"
        assert cfg.log_format == "console"

    def test_load_minimal_config(self, minimal_yaml: Path):
        cm = ConfigManager(minimal_yaml)
        cfg = cm.load()
        assert cfg.agent_id == "minimal-agent"
        # Defaults should be populated
        assert cfg.model.model == "kimi-k2.6"
        assert cfg.memory.short_term_limit == 10

    def test_config_property_caches(self, sample_yaml: Path):
        cm = ConfigManager(sample_yaml)
        cfg1 = cm.config  # triggers load
        cfg2 = cm.config
        assert cfg1 is cfg2

    def test_config_property_loads_if_not_loaded(self, sample_yaml: Path):
        cm = ConfigManager(sample_yaml)
        assert cm._config is None
        cfg = cm.config
        assert cfg is not None
        assert cfg.agent_id == "test-agent"

    def test_empty_config_raises(self, tmp_path: Path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        cm = ConfigManager(path)
        with pytest.raises(ValueError, match="empty"):
            cm.load()

    def test_env_var_substitution(self, tmp_path: Path):
        os.environ["TEST_AGENT_ID"] = "env-agent-42"
        config = """
agent_id: "${TEST_AGENT_ID}"
agent_name: "Env Test"
session_key: "session:env:main"
"""
        path = tmp_path / "env.yaml"
        path.write_text(config)
        cm = ConfigManager(path)
        cfg = cm.load()
        assert cfg.agent_id == "env-agent-42"
        del os.environ["TEST_AGENT_ID"]

    def test_env_var_with_default(self, tmp_path: Path):
        os.environ.pop("NONEXISTENT_VAR_12345", None)
        config = """
agent_id: "${NONEXISTENT_VAR_12345:default-agent}"
agent_name: "Default Test"
session_key: "session:default:main"
"""
        path = tmp_path / "default.yaml"
        path.write_text(config)
        cm = ConfigManager(path)
        cfg = cm.load()
        assert cfg.agent_id == "default-agent"

    def test_env_var_unset_no_default_keeps_literal(self, tmp_path: Path):
        os.environ.pop("UNSET_VAR_99999", None)
        config = """
agent_id: "agent-x"
agent_name: "Literal Test"
session_key: "${UNSET_VAR_99999}"
"""
        path = tmp_path / "literal.yaml"
        path.write_text(config)
        cm = ConfigManager(path)
        cfg = cm.load()
        assert cfg.session_key == "${UNSET_VAR_99999}"

    def test_env_var_in_nested_dict(self, tmp_path: Path):
        os.environ["TEST_BASE_URL"] = "http://test-host:9999"
        config = """
agent_id: "nested-agent"
agent_name: "Nested"
session_key: "session:nested:main"
model:
  base_url: "${TEST_BASE_URL}"
"""
        path = tmp_path / "nested.yaml"
        path.write_text(config)
        cm = ConfigManager(path)
        cfg = cm.load()
        assert cfg.model.base_url == "http://test-host:9999"
        del os.environ["TEST_BASE_URL"]

    def test_find_config_raises_when_none_exists(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent_home")
        with pytest.raises(FileNotFoundError, match="No config file found"):
            ConfigManager()

    def test_config_path_stored(self, sample_yaml: Path):
        cm = ConfigManager(sample_yaml)
        assert cm.config_path == sample_yaml