"""Agent failover against an injectable fake LLM — no Ollama required."""

from pathlib import Path

import pytest

from agent_resilience import Agent, Checkpoint, ModelRouter
from agent_resilience.llm import LLMBackend, LLMResponse


class SequenceLLM(LLMBackend):
    """Fails once, then answers. Consolidation calls also succeed."""

    def __init__(self):
        self.calls = 0
        self.model = "primary-fake"

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.calls += 1
        # First user-facing chat fails; later calls (consolidation + retry) succeed.
        if self.calls == 1:
            raise RuntimeError("primary model dead")
        return LLMResponse(content=f"ok-from-{self.model}-call-{self.calls}", model=self.model)

    async def health_check(self) -> dict:
        return {"status": "healthy"}

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_agent_failsover_with_fake_llm(tmp_path: Path):
    router = ModelRouter(
        primary="primary-fake",
        fallbacks=["fallback-fake"],
        state_path=tmp_path / "router.json",
    )
    llm = SequenceLLM()
    agent = Agent(
        router=router,
        checkpoint=Checkpoint(tmp_path / "state.db"),
        consolidation_steps=2,
        llm=llm,
        agency_threshold=0.1,
    )

    result = await agent.run_async("summarize this", task_id="job-1")

    assert "ok-from-" in result
    assert agent.failover_count == 1
    assert agent.last_consolidation is not None
    assert agent.last_consolidation["steps"] >= 1
    assert router.current.model_id == "fallback-fake"
    assert llm.model == "fallback-fake"

    latest = await agent.checkpoint.latest_for_task("job-1")
    assert latest is not None
    assert latest.is_complete is True
