# LAR — Local Agent Resilience

**Open-source reference architecture for agents that survive model death.**

By Gabriel.

Linux-first. Python 3.11+. This package is importable and testable without Ollama.

---

## The Problem

Every agent you ship today carries an expiration date. Not because of your code — because of the model underneath it.

On June 12, 2026, the U.S. government issued an emergency export-control directive ordering Anthropic to suspend Fable 5 and Mythos 5. Every agent built on Fable 5 died that day. Not because the code broke. Because the model was gone.

Most agents are thin wrappers around a prompt and an API call. When the model changes, the agent dies with it. This library is for the ones that shouldn't.

## What this package actually ships

`agent_resilience` 0.2.0 is a single importable library:

- **ModelRouter** — primary/fallback chain with persisted state (`current`, `advance`, `select`)
- **Agent** — runs a task; on LLM failure it advances the router, runs **Consolidator**, then retries
- **Checkpoint** — SQLite save/load/resume (`Checkpoint` is `CheckpointStore`)
- **Tools** — `Tool` / `ToolRegistry` plus hardened `exec` (no shell) and `web_fetch` (https, no private/file)
- **Identity** — session payload checks (camelCase or snake_case, no TypeError on ISO timestamps)
- **ModelCircuitBreaker** — fail N times in M seconds for a model id
- **HealthMonitor** — connectivity / tools / checkpoint / identity / disk checks (optional; Ollama-dependent)

Observatory, TUI, PromptRegistry, and ModelEvaluator are **not** in this release. They were unwired surface and were removed rather than shipped as fiction.

## Quick start (runs without Ollama)

```bash
pip install -e ".[dev]"
python -c "from agent_resilience import Agent, ModelRouter, Checkpoint; print(Agent, ModelRouter, Checkpoint)"
pytest -q
```

```python
import asyncio
from agent_resilience import Agent, ModelRouter, Checkpoint
from agent_resilience.llm import LLMBackend, LLMResponse


class FakeLLM(LLMBackend):
    def __init__(self):
        self.calls = 0
        self.model = "primary-fake"

    async def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("primary model dead")
        return LLMResponse(content=f"recovered via {self.model}", model=self.model)

    async def health_check(self):
        return {"status": "healthy"}

    async def close(self):
        return None


async def main():
    router = ModelRouter(
        primary="primary-fake",
        fallbacks=["fallback-fake"],
        state_path="router-state.json",
    )
    agent = Agent(
        router=router,
        checkpoint=Checkpoint("./state.db"),
        consolidation_steps=3,
        llm=FakeLLM(),
    )
    print(await agent.run_async("summarize the incident"))


if __name__ == "__main__":
    asyncio.run(main())
```

Live Ollama is optional. Pass `config=` and call `await agent.setup()` only when you actually have a local model server.

CLI (needs a YAML config and, for real inference, Ollama):

```bash
lar --config config/default.yaml --interactive
# or
python -m agent_resilience --config config/default.yaml "your task"
```

## Skill wrapper

`skills/resilience-skill` is a thin wrapper: `scripts/failover.py` re-exports `ModelRouter` / `Consolidator` from this library. It is not a published clawhub package in this repo.

## The 8 Principles

Documented in [DESIGN.md](DESIGN.md). The “In the code” lines there match this tree.

## Security

See [SECURITY.md](SECURITY.md). Exec and fetch are attack surface even when the model is local.

## License

MIT. See [LICENSE](LICENSE).
