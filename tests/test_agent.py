"""Tests for agent_resilience.agent — AgentLoop lifecycle.

Covers: initialization, setup, run_cycle with mocked LLM, identity validation,
tool execution, checkpoint integration, shutdown, error handling.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_resilience.agent import AgentLoop
from agent_resilience.checkpoint import AgentState, CheckpointStore, Phase
from agent_resilience.config import ModelConfig, RuntimeConfig
from agent_resilience.identity import SessionIdentityValidator
from agent_resilience.llm import LLMResponse


@pytest.fixture
def config():
    return RuntimeConfig(
        agent_id="test-agent",
        agent_name="Test Agent",
        session_key="session:test:main",
        model=ModelConfig(model="test-model", base_url="http://localhost:11434", timeout=5.0),
    )


@pytest.fixture
def identity():
    return SessionIdentityValidator(
        expected_agent_id="test-agent",
        expected_session_key="session:test:main",
        max_payload_age_seconds=300,
    )


@pytest.fixture
def agent(config, identity):
    return AgentLoop(config, identity)


@pytest.fixture
def valid_payload():
    return {
        "agentId": "test-agent",
        "sessionKey": "session:test:main",
        "timestamp": time.time(),
    }


class TestAgentLoopInit:
    def test_initial_state(self, agent):
        assert agent.config is not None
        assert agent.identity is not None
        assert agent.llm is None
        assert agent._running is False
        assert agent._message_history == []
        assert agent.tool_registry is not None
        assert agent.observatory is None

    def test_observatory_optional(self, config, identity):
        mock_obs = MagicMock()
        agent = AgentLoop(config, identity, observatory=mock_obs)
        assert agent.observatory is mock_obs


class TestAgentLoopSetup:
    async def test_setup_initializes_llm(self, agent):
        with patch.object(agent.llm.__class__, "health_check", new_callable=AsyncMock) if agent.llm else patch("agent_resilience.llm.OllamaBackend.health_check", new_callable=AsyncMock, return_value={"status": "healthy"}):  # noqa: SIM117
            # Mock the OllamaBackend to avoid real network calls
            with patch("agent_resilience.llm.OllamaBackend") as mock_backend:
                mock_instance = MagicMock()
                mock_instance.health_check = AsyncMock(return_value={"status": "healthy"})
                mock_instance.close = AsyncMock()
                mock_backend.return_value = mock_instance

                await agent.setup()

        assert agent.llm is not None
        assert len(agent.tool_registry.get_tool_names()) >= 5

    async def test_setup_with_fallbacks(self, config, identity):
        config.model.fallbacks = ["fallback-1", "fallback-2"]
        agent = AgentLoop(config, identity)

        with patch("agent_resilience.llm.OllamaBackend") as mock_backend:
            mock_instance = MagicMock()
            mock_instance.health_check = AsyncMock(return_value={"status": "healthy"})
            mock_instance.close = AsyncMock()
            mock_instance.model = "test-model"
            mock_backend.return_value = mock_instance

            await agent.setup()

        assert agent.llm is not None


class TestAgentLoopRunCycle:
    async def test_simple_response(self, agent):
        # Mock the LLM
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(content="Hello!", model="test-model"))
        mock_llm.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_llm.close = AsyncMock()
        agent.llm = mock_llm

        result = await agent.run_cycle("Say hello")
        assert result == "Hello!"
        assert len(agent._message_history) == 2  # user + assistant
        assert agent._message_history[0]["role"] == "user"
        assert agent._message_history[1]["role"] == "assistant"

    async def test_identity_rejection(self, agent, valid_payload):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(content="response", model="test-model"))
        mock_llm.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_llm.close = AsyncMock()
        agent.llm = mock_llm

        # Tamper with the payload
        valid_payload["agentId"] = "wrong-agent"
        result = await agent.run_cycle("task", payload=valid_payload)
        assert "Payload rejected" in result
        # LLM should not have been called
        mock_llm.chat.assert_not_called()

    async def test_llm_failure_returns_error(self, agent):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM is down"))
        mock_llm.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_llm.close = AsyncMock()
        agent.llm = mock_llm

        result = await agent.run_cycle("task")
        assert "Error: LLM backend failed" in result

    async def test_tool_execution(self, agent):
        # First response includes a tool call, second is final
        mock_llm = MagicMock()
        tool_call_response = LLMResponse(
            content="Let me check",
            tool_calls=[{
                "type": "function",
                "function": {"name": "exec", "arguments": {"command": "echo hello"}},
            }],
            model="test-model",
        )
        final_response = LLMResponse(content="Done! The output is: hello", model="test-model")
        mock_llm.chat = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_llm.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_llm.close = AsyncMock()
        agent.llm = mock_llm

        # Register built-in tools
        from agent_resilience.tools.builtin import register_builtin_tools
        register_builtin_tools(agent.tool_registry)

        result = await agent.run_cycle("Run echo hello")
        assert "Done" in result
        # LLM should have been called twice (think + rethink)
        assert mock_llm.chat.call_count == 2

    async def test_unknown_tool_records_error(self, agent):
        mock_llm = MagicMock()
        tool_call_response = LLMResponse(
            content="Let me try",
            tool_calls=[{
                "type": "function",
                "function": {"name": "nonexistent_tool", "arguments": {}},
            }],
            model="test-model",
        )
        final_response = LLMResponse(content="OK", model="test-model")
        mock_llm.chat = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_llm.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_llm.close = AsyncMock()
        agent.llm = mock_llm

        result = await agent.run_cycle("task")
        assert result == "OK"

    async def test_with_checkpoint_store(self, agent, tmp_path):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(content="Done!", model="test-model"))
        mock_llm.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_llm.close = AsyncMock()
        agent.llm = mock_llm

        store = CheckpointStore(tmp_path / "agent_test.db")
        result = await agent.run_cycle("task", checkpoint_store=store, task_id="test-task")
        assert result == "Done!"

        # Verify checkpoint was saved
        checkpoints = await store.list_for_task("test-task")
        assert len(checkpoints) >= 1
        assert checkpoints[0].is_complete is True

    async def test_resume_from_checkpoint(self, agent, tmp_path):
        # Pre-populate a checkpoint store with an incomplete checkpoint
        store = CheckpointStore(tmp_path / "resume_test.db")
        incomplete_state = AgentState(
            task_id="resume-task",
            step_number=2,
            phase=Phase.THINK,
            messages=[{"role": "user", "content": "original task"}],
            is_complete=False,
        )
        await store.save(incomplete_state)

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(content="Resumed!", model="test-model"))
        mock_llm.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_llm.close = AsyncMock()
        agent.llm = mock_llm

        result = await agent.run_cycle("new task", checkpoint_store=store, task_id="resume-task")
        assert result == "Resumed!"
        # The message history should have been restored from checkpoint
        # (then a new assistant message added)
        assert any(m.get("content") == "original task" for m in agent._message_history)


class TestAgentLoopShutdown:
    async def test_shutdown_closes_llm(self, agent):
        mock_llm = MagicMock()
        mock_llm.close = AsyncMock()
        agent.llm = mock_llm

        await agent.shutdown()
        mock_llm.close.assert_called_once()

    async def test_shutdown_without_llm(self, agent):
        agent.llm = None
        # Should not raise
        await agent.shutdown()
