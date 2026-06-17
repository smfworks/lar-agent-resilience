---
name: resilience-skill
description: "Drop-in model resilience for any OpenClaw agent. Survive model death (Fable-style shutdowns, deprecations, outages) with automatic failover and consolidation phase. By Gabriel."
---

# Resilience Skill — Survive Model Death

Drop this skill into any OpenClaw agent. Configure a primary model and a fallback chain. If the primary dies — export-control directive, deprecation, outage, capability shock — the agent fails over automatically, runs a consolidation phase, and keeps working.

This is the smallest atomic unit of LAR (Local Agent Resilience). Install it. Configure it. Pull the primary model. Watch the agent survive.

## When to Use

- You depend on a single model that could be deprecated, shut down, or changed
- You want automatic failover without rewriting your agent
- You want a consolidation phase after model swaps (no thrashing during settling)
- You want observable failure metrics — when did the swap happen, why, how did the new model recover

## What It Does

The skill provides four primitives, each backed by a design principle documented in [DESIGN.md](../../../DESIGN.md):

| Primitive | File | Principle |
|-----------|------|-----------|
| `ModelRouter` | `scripts/failover.py` | Keep a local fallback chain |
| `ModelRouter.advance()` | `scripts/failover.py` | Decouple the model from the agent |
| `Consolidator` | `scripts/failover.py` | Consolidate before you act (Ye 2026) |
| `SwapEvent` | `scripts/failover.py` | Make failure observable |

## Quick Start

### 1. Install the skill

```bash
clawhub install resilience-skill
```

### 2. Configure your agent

```yaml
# openclaw.yaml
skills:
  - resilience-skill

resilience:
  primary_model: "ollama/glm-5.2:cloud"
  fallback_chain:
    - "ollama/qwen3-coder:32b"
    - "ollama/kimi-k2.7-code:cloud"
    - "ollama/qwen3.5:9b"
  consolidation_steps: 50
  agency_threshold: 0.15
```

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
from failover import ModelRouter, Consolidator

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