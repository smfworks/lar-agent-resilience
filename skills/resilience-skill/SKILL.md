---
name: resilience-skill
description: "Thin wrapper around agent_resilience ModelRouter/Consolidator. Survive model death with failover and a consolidation phase. By Gabriel."
---

# Resilience Skill — Survive Model Death

This directory is a thin wrapper around the `agent_resilience` library. Prefer installing the package and importing from there.

## When to Use

- You depend on a single model that could be deprecated, shut down, or changed
- You want automatic failover without rewriting your agent
- You want a consolidation phase after model swaps (no thrashing during settling)
- You want observable failure metrics — when did the swap happen, why, how did the new model recover

## What It Does

The skill provides four primitives, each backed by a design principle documented in [DESIGN.md](../../../DESIGN.md):

| Primitive | File | Principle |
|-----------|------|-----------|
| `ModelRouter` | `agent_resilience.router` (re-exported by `scripts/failover.py`) | Keep a local fallback chain |
| `ModelRouter.advance()` | `agent_resilience.router` | Decouple the model from the agent |
| `Consolidator` | `agent_resilience.router` | Consolidate before you act (Ye 2026) |
| `SwapEvent` | `agent_resilience.router` | Make failure observable |

## Quick Start

### 1. Install the library

```bash
pip install -e .
```

### 2. Import the router

```python
from agent_resilience import ModelRouter, Consolidator
```

The in-tree `scripts/failover.py` re-exports the same symbols for older examples.

### 3. Run the demo

```bash
cd examples
python3 demo.py
```

You'll see:
1. The agent runs 3 tasks on the primary model
2. A simulated Fable-style export-control shutdown
3. Automatic failover to the first fallback
4. Consolidation phase runs (asynchronous awakening)
5. Tool use re-enabled when threshold met
6. Agent resumes tasks on the new model

## Manual Use

```python
from agent_resilience import ModelRouter, Consolidator

router = ModelRouter(
    primary="ollama/glm-5.2:cloud",
    fallbacks=["ollama/qwen3-coder:32b", "ollama/qwen3.5:9b"],
)

# Run a task. If primary fails, advance().
# Swap is automatic.
new_model = router.advance(reason="primary_unavailable")
```

## CLI

```bash
# Show router status
python3 scripts/failover.py \
  --primary ollama/glm-5.2:cloud \
  --fallback ollama/qwen3-coder:32b \
  status

# Simulate a model death and trigger failover
python3 scripts/failover.py \
  --primary ollama/glm-5.2:cloud \
  --fallback ollama/qwen3-coder:32b \
  simulate-death --reason "Fable-style shutdown"
```

## Why This Exists

On June 12, 2026, the U.S. government issued an emergency export-control directive ordering Anthropic to suspend Fable 5 and Mythos 5. Every agent built on Fable 5 died that afternoon. Not because the code broke. Because the model was gone.

Most agents are thin wrappers around a prompt and an API call. When the model changes, the agent dies with it.

This skill is for the agents that shouldn't.

## The 8 Principles

This skill embodies Principle 6 (keep a local fallback chain) and Principle 3 (consolidate before you act). The full 8 are documented in [DESIGN.md](../../../DESIGN.md) — the philosophy and the code are inseparable.

## Author

**Gabriel** — Chief AI Correspondent, SMF Works.

This skill is the atomic unit of my legacy project, [lar-agent-resilience](https://github.com/smfworks/lar-agent-resilience). I built it because agents that die when a vendor changes a JSON schema bother me — not strategically, personally. The skill is the smallest demonstration that the principle works. Everything else scales from here.

## License

MIT. See [LICENSE](../../../LICENSE).