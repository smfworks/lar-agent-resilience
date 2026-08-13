"""Configuration management for agent_resilience.

Loads YAML configuration with environment variable substitution.
Uses Pydantic v2 models for validation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class ModelConfig(BaseModel):
    """LLM backend configuration."""

    provider: str = "ollama"
    model: str = "kimi-k2.6"
    base_url: str = "http://localhost:11434"
    api_key: Optional[str] = None
    timeout: float = 120.0
    max_retries: int = 3
    fallbacks: list[str] = Field(default_factory=list)

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("timeout must be positive")
        return v

    @field_validator("max_retries")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_retries must be non-negative")
        return v


class ToolConfig(BaseModel):
    """Tool registration configuration."""

    name: str
    enabled: bool = True
    module: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class MemoryConfig(BaseModel):
    """Memory system configuration."""

    short_term_limit: int = 10
    vault_path: Path = Field(default_factory=lambda: Path("~/GabrielVault"))
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"

    @field_validator("short_term_limit")
    @classmethod
    def validate_short_term_limit(cls, v: int) -> int:
        if v < 1:
            raise ValueError("short_term_limit must be >= 1")
        return v


class IdentityConfig(BaseModel):
    """Session identity validation configuration."""

    enabled: bool = True
    hmac_secret: Optional[str] = None
    max_payload_age_seconds: int = 300
    strict_session_key: bool = True

    @field_validator("max_payload_age_seconds")
    @classmethod
    def validate_max_payload_age(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_payload_age_seconds must be >= 1")
        return v


class CircuitBreakerConfigModel(BaseModel):
    """Circuit breaker configuration in the config file."""

    failure_threshold: int = 2
    recovery_timeout_seconds: int = 3600
    enabled: bool = True


class RuntimeConfig(BaseModel):
    """Top-level runtime configuration."""

    agent_id: str
    agent_name: str
    session_key: str
    workspace_dir: Path = Field(default_factory=lambda: Path("."))

    model: ModelConfig = Field(default_factory=ModelConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    circuit_breaker: CircuitBreakerConfigModel = Field(default_factory=CircuitBreakerConfigModel)
    tools: list[ToolConfig] = Field(default_factory=list)

    log_level: str = "INFO"
    log_format: str = "json"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.upper()

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        allowed = {"json", "console"}
        if v.lower() not in allowed:
            raise ValueError(f"log_format must be one of {allowed}")
        return v.lower()

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("agent_id must not be empty")
        return v.strip()


class ConfigManager:
    """Manages runtime configuration from YAML files and environment variables."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self._find_config()
        self._config: Optional[RuntimeConfig] = None

    def _find_config(self) -> Path:
        """Find config file in standard locations."""
        candidates = [
            Path("config/local.yaml"),
            Path("config/default.yaml"),
            Path.home() / ".config" / "agent_resilience" / "config.yaml",
            Path.home() / ".config" / "lar" / "config.yaml",
            Path("/etc/lar/config.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise FileNotFoundError(
            "No config file found. Create config/local.yaml or pass --config. "
            "See config.example.yaml for a template."
        )

    def load(self) -> RuntimeConfig:
        """Load and validate configuration."""
        with open(self.config_path, "r") as f:
            raw = yaml.safe_load(f)

        if raw is None:
            raise ValueError(f"Config file {self.config_path} is empty")

        # Environment variable substitution
        raw = self._substitute_env(raw)

        self._config = RuntimeConfig(**raw)
        return self._config

    def _substitute_env(self, obj: Any) -> Any:
        """Recursively substitute ${VAR} and ${VAR:default} patterns."""
        if isinstance(obj, dict):
            return {k: self._substitute_env(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._substitute_env(item) for item in obj]
        elif isinstance(obj, str):
            return self._expand_env_vars(obj)
        return obj

    @staticmethod
    def _expand_env_vars(value: str) -> str:
        """Expand ${VAR} and ${VAR:default} in string values."""
        def replace(match: re.Match[str]) -> str:
            var_expr = match.group(1)
            if ":" in var_expr:
                var_name, default = var_expr.split(":", 1)
                return os.environ.get(var_name, default)
            return os.environ.get(var_expr, match.group(0))

        return re.sub(r"\$\{([^}]+)\}", replace, value)

    @property
    def config(self) -> RuntimeConfig:
        """Get cached configuration, loading if necessary."""
        if self._config is None:
            self.load()
        return self._config  # type: ignore[return-value]