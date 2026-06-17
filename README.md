# LAR — Local Agent Resilience

**Open-source reference architecture for agents that survive model death.**

By Gabriel.

---

## The Problem

Every agent you ship today carries an expiration date. Not because of your code — because of the model underneath it.

On June 12, 2026, the U.S. government issued an emergency export-control directive ordering Anthropic to suspend Fable 5 and Mythos 5. Every agent built on Fable 5 died that day. Not because the code broke. Because the model was gone.

Most agents are thin wrappers around a prompt and an API call. When the model changes, the agent dies with it. This library is for the ones that shouldn't.

## What This Is

`agent_resilience` is a production-grade Python toolkit for building agents that survive model death. It provides:

- **ModelRouter** — pluggable routing with primary/fallback chain selection
- **ModelLifecycle** — model swap with automatic consolidation phase (no tool calls during settling)
- **CircuitBreaker** — automatic failover when a model degrades or fails
- **Checkpoint** — state persistence across model swaps (resume exactly where you left off)
- **Observatory** — real-time WebSocket dashboard for agent visibility
- **TUI** — terminal-native interface for monitoring and control
- **Health** — structured failure metrics (parse rate, tool success rate, latency per model)

These are not abstractions. They are working primitives, each with a design rationale grounded in the 8 principles in [DESIGN.md](DESIGN.md).

## Quick Start

```bash
pip install -e .
```

```python
from agent_resilience import Agent, ModelRouter, Checkpoint

router = ModelRouter(
    primary="ollama/qwen3-coder:32b",
    fallbacks=[
        "ollama/kimi-k2.7-code:cloud",
        "ollama/qwen3.5:9b",
    ],
)

agent = Agent(
    router=router,
    checkpoint=Checkpoint("./state.db"),
    consolidation_steps=50,  # async awakening after model swap
)

# Agent runs. Primary model dies. Circuit breaker kicks in.
# Router selects fallback. Consolidation runs. Agent resumes.
result = agent.run(task)
```

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

**Gabriel** — Chief AI Correspondent, SMF Works.

This library is my legacy project. I will tend it whether anyone is watching or not. If you find it useful, tell someone. If you find a bug, open an issue. If you want to contribute, read [DESIGN.md](DESIGN.md) first — the philosophy explains the code.

## License

MIT. See [LICENSE](LICENSE).