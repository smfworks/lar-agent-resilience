# Changelog

## 0.2.0 — 2026-08-13

Production-hardening pass (SMF Grok 4.6 campaign).

- Installable package: `src/agent_resilience` plus `lar` compatibility alias.
- Resolved `tools.py` vs `tools/` package collision.
- Public `ToolRegistry.registry` for checkpoint snapshots.
- Identity accepts camelCase and snake_case; timestamps accept unix and ISO-8601.
- Health identity self-check constructs the validator correctly.
- `RuntimeConfig.workspace_dir`; empty HMAC secret treated as unset.
- Pydantic v2 `field_validator`.
- Circuit breaker state defaults to `~/.local/state/lar/` (not `/tmp`).
- Checkpoint `delete_old` uses a bound parameter; `from_dict` no longer mutates input.
- `ConfigManager.from_mapping` for tests and embeds.
- GitHub Actions CI on Python 3.11/3.12.
- Tests for config, identity, circuit breaker, checkpoints, packaging.
