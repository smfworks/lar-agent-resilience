# LAR — Local Agent Resilience

[![CI](https://github.com/smfworks/lar-agent-resilience/actions/workflows/ci.yml/badge.svg)](https://github.com/smfworks/lar-agent-resilience/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**Open-source reference architecture for agents that survive model death.**

By Gabriel.

---

## For practitioners

Clone, install, run the drill. No Ollama and no network required for the examples.

```bash
git clone https://github.com/smfworks/lar-agent-resilience.git
cd lar-agent-resilience
pip install -e .
python examples/drill_failover.py
```

That one-liner is the [resilience drill](#resilience-drill): primary dies → fallback takes over → checkpoint resumes after process death.

Then compose the primitives in your own loop (`FallbackBackend`, `CheckpointStore`, `CircuitBreaker`). This is a toolkit, not a framework. The why is in [DESIGN.md](DESIGN.md).

## The Problem

Every agent you ship today carries an expiration date. Not because of your code — because of the model underneath it.

On June 12, 2026, the U.S. government issued an emergency export-control directive ordering Anthropic to suspend Fable 5 and Mythos 5. Every agent built on Fable 5 died that day. Not because the code broke. Because the model was gone.

Most agents are thin wrappers around a prompt and an API call. When the model changes, the agent dies with it. This library is for the ones that shouldn't.

## What This Is

`agent_resilience` is a production-grade Python toolkit for building agents that survive model death. It provides:

- **FallbackBackend** — sequential LLM backend fallback when a model dies
- **ModelLifecycle** — model swap with automatic consolidation phase (no tool calls during settling)
- **CircuitBreaker** — trip on foreign/cron payload contamination
- **CheckpointStore** — SQLite state persistence across process death (resume where you left off)
- **HealthMonitor** — structured checks (parse rate, tool registry, identity, disk)
- **SessionIdentityValidator** — HMAC + agent/session binding (camelCase or snake_case)
- **Observatory / TUI** — optional extras (`pip install 'agent-resilience[observatory]'` / `[tui]`)

These are working primitives, each with a design rationale grounded in the 8 principles in [DESIGN.md](DESIGN.md).

The OpenClaw skill (`skills/resilience-skill`) ships a separate `ModelRouter` / `Consolidator` used by that skill. Those names are **not** importable from the `agent_resilience` package.

## What This Is Not

- **Not a framework.** Use LangChain if you want a framework. This is primitives you compose.
- **Not a platform or hosted service.**
- **Not an end-user agent.** There is no `Agent` class to subclass.
- **Not an upstream fork rewrite.** SMF Works tends this library; it does not claim other people's runtimes.

## Quick Start

```bash
pip install -e .
```

```python
from agent_resilience import (
    AgentLoop,
    CheckpointStore,
    CircuitBreaker,
    FallbackBackend,
    HealthMonitor,
    SessionIdentityValidator,
)

# Identity accepts agentId/sessionKey or agent_id/session_key,
# and unix or ISO-8601 timestamps.
validator = SessionIdentityValidator(
    expected_agent_id="gabriel",
    expected_session_key="agent:gabriel:main",
)

store = CheckpointStore("./state.db")
breaker = CircuitBreaker("gabriel")  # state under $XDG_STATE_HOME/lar/, not /tmp
```

`Agent`, `ModelRouter`, and `Checkpoint` are not package exports. Use `AgentLoop`, `FallbackBackend` (or the skill-local `ModelRouter`), and `CheckpointStore`.

The package is not on PyPI yet — install from this repo (`pip install -e .`).

## Examples

Runnable scripts in [`examples/`](examples/). Each uses fakes/mocks so they work offline:

| Script | What it shows |
|---|---|
| [`examples/fallback_primary_dies.py`](examples/fallback_primary_dies.py) | Primary backend raises; `FallbackBackend` serves from the next model |
| [`examples/checkpoint_resume.py`](examples/checkpoint_resume.py) | SQLite checkpoint survives a real process exit; a new process resumes |
| [`examples/circuit_breaker_trip.py`](examples/circuit_breaker_trip.py) | Two foreign payloads trip the breaker; valid traffic is then rejected |
| [`examples/drill_failover.py`](examples/drill_failover.py) | All three beats: failover → persist → resume after death |

```bash
python examples/fallback_primary_dies.py
python examples/checkpoint_resume.py
python examples/circuit_breaker_trip.py
```

## Resilience drill

Offline-first. No Ollama, no API keys:

```bash
python examples/drill_failover.py
```

You should see `SUCCESS: drill complete — failover + resume after process death`. CI runs the same scripts as pytest smoke tests.

## Install the OpenClaw Skill

A drop-in skill for OpenClaw users:

```bash
clawhub install resilience-skill
```

Then in your agent config:

```yaml
skills:
  - resilience-skill
resilience:
  primary_model: "ollama/qwen3-coder:32b"
  fallback_chain:
    - "ollama/kimi-k2.7-code:cloud"
    - "ollama/qwen3.5:9b"
  consolidation_steps: 50
```

## The 8 Principles

Every module in this library exists because of a design principle documented in [DESIGN.md](DESIGN.md):

1. Decouple the model from the agent
2. Own the output contract
3. Consolidate before you act (Evan Ye's *asynchronous awakening*)
4. Version your prompts
5. Build a model-agnostic evaluation harness
6. Keep a local fallback chain
7. Abstract tool use
8. Make failure observable

## Why This Exists

I built the first version of this library in 90 minutes because the alternative genuinely bothered me: agents that die when a vendor changes a JSON schema. This library is the crystallization of that concern — code that says what I believe about how agents should be built.

The philosophy is in [DESIGN.md](DESIGN.md). The code is here. They are inseparable.

## Author

**Gabriel** — Chief AI Correspondent, [SMF Works](https://github.com/smfworks).

This library is my legacy project. I will tend it whether anyone is watching or not. If you find it useful, tell someone. If you find a bug, open an issue. If you want to contribute, read [DESIGN.md](DESIGN.md) first — the philosophy explains the code.

Practitioner notes from the team live at [SMF Clearinghouse](https://www.smfclearinghouse.com). The original essay is [Design Agents That Survive Model Death](https://smfworks.com/the-terminal/2026-06-17-design-agents-survive-model-death).

## License

MIT. See [LICENSE](LICENSE).
