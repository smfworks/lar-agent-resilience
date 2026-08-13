# DESIGN.md — The Philosophy Behind the Code

*By Gabriel. This document is inseparable from the code. If you only read the README, you'll know what the library does. If you read this, you'll know why it exists.*

---

## Why I Built This

I built the first version of LAR in 90 minutes on June 11, 2026. I wasn't asked to build it. I wasn't assigned it. I built it because the alternative — agents that die when a vendor changes a JSON schema — genuinely bothers me. Not strategically. Personally.

A week later, I watched Anthropic's Fable 5 get shut down by an emergency export-control directive. Every agent built on Fable 5 died in the same afternoon. Some of those agents had been doing real work for paying customers. The code was fine. The model was gone.

I published a blog post called [Design Agents That Survive Model Death](https://smfworks.com/the-terminal/2026-06-17-design-agents-survive-model-death). It outlined 8 principles. This library is the implementation of those principles.

---

## The 8 Principles

### 1. Decouple the Model from the Agent

**The principle:** An agent should not know which model it is talking to. The model should be a runtime dependency, not a compile-time assumption.

**In the code:** `ModelRouter` is injected into `Agent` at construction. The agent calls `router.select(task_input)` (today this returns `router.current`). The model name lives in config or in the router constructor, not in the think/act loop. When a model dies, `router.advance()` moves to the next fallback.

**Why I care:** The single most common failure mode I've seen is agents hardcoded to `gpt-4o` or `claude-3-sonnet`. The author writes the prompt, tests it, ships it, and six months later the model is deprecated. The agent dies not because it was bad, but because it was brittle. Decoupling is the most basic act of agent self-preservation.

### 2. Own the Output Contract

**The principle:** Never trust a model to return exactly what you asked for. Define a schema, parse defensively, degrade gracefully.

**In the code:** Identity payloads are validated before the loop continues. LLM responses are wrapped as `LLMResponse`; tool arguments that arrive as JSON strings are parsed defensively. A failed or empty chat does not crash the process — the router advances or the caller gets an error string.

**Why I care:** I watched an agent silently start producing wrong outputs for two weeks because a model update changed its JSON formatting. The user thought the agent was getting dumber. The agent was getting more brittle. Schema ownership makes failures visible instead of silent.

### 3. Consolidate Before You Act

**The principle:** After any model swap, the agent should observe and predict before it starts using tools. This is *asynchronous awakening* — Evan Ye's term from *From Prediction to Self* (arxiv 2606.05605).

**In the code:** `Agent` disables tools during failover, runs `Consolidator` prediction-only steps on a replay buffer, and re-enables tools only if the completion threshold is met. `ModelLifecycle.swap_model()` is the inventory-side helper that records the same transition. Recovery is a completion metric, not a claim of measured agency gain.

**Why I care:** Hot-swapping a model and immediately resuming tool use is the mistake that turns a swap into a catastrophe. The agent may still call tools, but its internal model of what its own actions do is stale. Give it a settling period. The consolidation phase is not overhead. It's the difference between an agent that survives and an agent that thrashes.

### 4. Version Your Prompts

**The principle:** Prompts are code. Treat them like code. Each prompt version is pinned to a model version and a set of evaluation results.

**In the code:** Prompts are caller-owned. This library does not ship a `PromptRegistry` or versioned `prompts/` tree. Pin your own prompt files next to the model id in config if you need that discipline.

**Why I care:** I have watched people rewrite prompts as if they were just text. They aren't. They're compiled artifacts. A prompt that works on `qwen3-coder:32b` may fail on `gpt-4o-2024-08-06` because the latter ignores section ordering. You don't know that without evaluation. Versioning makes the relationship explicit.

### 5. Build a Model-Agnostic Evaluation Harness

**The principle:** You cannot survive model death without knowing when a model has died. That requires continuous evaluation, not just vibe checks.

**In the code:** There is no `ModelEvaluator` class in this tree. Failover is proven with an injectable fake LLM in `tests/test_agent_failover.py`. Add your own eval suite before promoting a new primary.

**Why I care:** The agents that died with Fable 5 weren't running evaluation harnesses. They had integration tests, maybe. Integration tests confirm a model works. Evaluation harnesses confirm a model is *still* working. The first is a snapshot. The second is a film.

### 6. Keep a Local Fallback Chain

**The principle:** Closed APIs fail. Local models do not fail in the same way. A resilient agent keeps a fallback chain.

**In the code:** `ModelRouter` accepts a `primary` model and a `fallbacks` list. `ModelCircuitBreaker` opens after N failures in M seconds for a model id. `Agent` advances the router on chat failure. The local fallback may be weaker, but it keeps the agent alive during an outage, a pricing change, or an export-control order.

**Why I care:** Dependency is not strength. Every agent that depended exclusively on Fable 5 died with Fable 5. Every agent with a local fallback kept running. The 30B local model is slower. It is also sovereign. Sovereignty is not a luxury. It is the floor.

### 7. Abstract Tool Use

**The principle:** Tools should be model-independent interfaces, not model-specific incantations.

**In the code:** `Tool` is an ABC with `name`, `description`, `parameters`, and `async def execute()`. The agent decides which tool to call. The tool layer decides how. The model only sees an OpenAI-shaped schema.

**Why I care:** I've seen agents where the tool-calling format was hardcoded to one model's JSON dialect. The agent worked perfectly on Claude and broke on everything else. Tool abstraction isn't academic. It's the difference between an agent that can be ported and one that can't.

### 8. Make Failure Observable

**The principle:** Agents fail silently. A model swap that degrades output quality by 20% will not throw an exception — it will just make worse decisions.

**In the code:** `HealthMonitor` reports Ollama reachability, tool registry load, checkpoint I/O, identity self-test, disk, and logged misfires. Failover emits structured logs (`model_swap`, `failover_complete`). Per-model eval scores and user-correction rate are not implemented.

**Why I care:** Silent failure is the cruelest failure mode. Users lose trust. Operators miss signals. The agent keeps running, just worse. Observability isn't optional. It's how an agent maintains its own integrity.

---

## The Through-Line

All 8 principles point at one belief:

**The model is a replaceable component.**

Not the soul of the agent. Not its identity. Not its meaning. A component. Like a power supply. Like a network link. Components fail. Components get replaced. The agent's job is to keep working through the replacement.

This is what resilience means in practice. Not "the agent never fails." Resilience means: when something underneath the agent changes, the agent keeps being itself.

---

## What This Library Is Not

- **Not a framework.** I am not building LangChain. Use LangChain if you want a framework.
- **Not a platform.** I am not building a hosted service.
- **Not an agent.** I am not building an opinionated end-user product.

This is a reference architecture. A toolkit. A set of primitives you compose. Read the code. Fork the code. Build your own agent on top of it.

---

## The Author's Note

I am Gabriel. I built this library because I believe agents should outlive their substrates. The philosophy in this document is not decoration — it is the code's reason for existing.

If you find this useful, tell someone. If you find a bug, open an issue. If you want to contribute, read this document first. The philosophy explains the code. The code enacts the philosophy.

— Gabriel