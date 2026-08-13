# Changelog

## 0.2.0 — 2026-08-13

Production-hardening pass. The advertised import path now works.

- Package renamed to `agent-resilience`; all imports are `agent_resilience`
- Public exports: `Agent`, `ModelRouter`, `Checkpoint`
- `tools.py` / `tools/` collision removed
- Skill `ModelRouter` promoted into the library; skill script is a wrapper
- `ExecTool` no longer uses `shell=True`; `WebFetchTool` is https + public-only
- Tests cover packaging, identity, checkpoint, failover, tool safety
- Linux CI: pytest + ruff on Python 3.11 and 3.12
- Unwired Observatory / TUI / benchmark / memory modules removed
