# Contributing

1. Read [DESIGN.md](DESIGN.md). The eight principles are the review bar.
2. Fork and branch from `main`. Conventional commits (`fix:`, `test:`, `docs:`, `ci:`).
3. `pip install -e ".[dev]"` then `pytest -q`.
4. Do not add a new framework. This is a toolkit.
5. Public docs stay factual. Do not invent APIs in the README.

## Layout

- `src/agent_resilience/` — installable package
- `src/lar/` — compatibility import path (`import lar`)
- `skills/resilience-skill/` — OpenClaw/Hermes skill wrapper
- `tests/` — pytest
