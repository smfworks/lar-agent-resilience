"""Tests for agent_resilience.llm — LLMBackend, OllamaBackend, FallbackBackend.

Covers: chat, health_check, fallback chain, error handling, close.
Uses httpx mocking to avoid real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_resilience.llm import (
    FallbackBackend,
    LLMBackend,
    LLMResponse,
    OllamaBackend,
)


@pytest.fixture
def ollama_backend():
    return OllamaBackend(model="test-model", base_url="http://localhost:11434", timeout=5.0)


class TestLLMResponse:
    def test_defaults(self):
        r = LLMResponse(content="hello")
        assert r.content == "hello"
        assert r.tool_calls == []
        assert r.model == ""
        assert r.finish_reason is None

    def test_with_tool_calls(self):
        r = LLMResponse(
            content="",
            tool_calls=[{"type": "function", "function": {"name": "exec", "arguments": {}}}],
            model="test-model",
        )
        assert len(r.tool_calls) == 1
        assert r.model == "test-model"


class TestOllamaBackend:
    async def test_chat_success(self, ollama_backend):
        mock_response_data = {
            "message": {
                "content": "Hello from the model",
                "tool_calls": [],
            },
            "model": "test-model",
        }
        mock_http_response = MagicMock()
        mock_http_response.json.return_value = mock_response_data
        mock_http_response.raise_for_status = MagicMock()

        with patch.object(ollama_backend, "client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_http_response)
            response = await ollama_backend.chat([{"role": "user", "content": "hi"}])

        assert response.content == "Hello from the model"
        assert response.model == "test-model"
        assert response.tool_calls == []

    async def test_chat_with_tool_calls(self, ollama_backend):
        mock_response_data = {
            "message": {
                "content": "Let me check that",
                "tool_calls": [
                    {"function": {"name": "exec", "arguments": {"command": "ls"}}}
                ],
            },
            "model": "test-model",
        }
        mock_http_response = MagicMock()
        mock_http_response.json.return_value = mock_response_data
        mock_http_response.raise_for_status = MagicMock()

        with patch.object(ollama_backend, "client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_http_response)
            response = await ollama_backend.chat(
                [{"role": "user", "content": "list files"}],
                tools=[{"type": "function", "function": {"name": "exec"}}],
            )

        assert response.content == "Let me check that"
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["function"]["name"] == "exec"

    async def test_chat_http_error_raises(self, ollama_backend):
        mock_http_response = MagicMock()
        mock_http_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=mock_http_response
        )

        with patch.object(ollama_backend, "client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_http_response)
            with pytest.raises(httpx.HTTPStatusError):
                await ollama_backend.chat([{"role": "user", "content": "hi"}])

    async def test_chat_request_error_raises(self, ollama_backend):
        with patch.object(ollama_backend, "client") as mock_client:
            mock_client.post = AsyncMock(side_effect=httpx.RequestError("connection refused"))
            with pytest.raises(httpx.RequestError):
                await ollama_backend.chat([{"role": "user", "content": "hi"}])

    async def test_health_check_healthy(self, ollama_backend):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [{"name": "test-model:latest"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(ollama_backend, "client") as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            health = await ollama_backend.health_check()

        assert health["status"] == "healthy"
        assert health["model_available"] is True
        assert health["target_model"] == "test-model"

    async def test_health_check_model_not_available(self, ollama_backend):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [{"name": "other-model:latest"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(ollama_backend, "client") as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            health = await ollama_backend.health_check()

        assert health["status"] == "degraded"
        assert health["model_available"] is False

    async def test_health_check_unhealthy(self, ollama_backend):
        with patch.object(ollama_backend, "client") as mock_client:
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            health = await ollama_backend.health_check()

        assert health["status"] == "unhealthy"
        assert "error" in health

    async def test_close(self, ollama_backend):
        with patch.object(ollama_backend, "client") as mock_client:
            mock_client.aclose = AsyncMock()
            await ollama_backend.close()
            mock_client.aclose.assert_called_once()


class TestFallbackBackend:
    @pytest.fixture
    def backends(self):
        primary = OllamaBackend(model="primary", base_url="http://localhost:1")
        fallback1 = OllamaBackend(model="fallback1", base_url="http://localhost:2")
        fallback2 = OllamaBackend(model="fallback2", base_url="http://localhost:3")
        return [primary, fallback1, fallback2]

    async def test_chat_succeeds_on_first_backend(self, backends):
        mock_response = LLMResponse(content="success", model="primary")
        backends[0].chat = AsyncMock(return_value=mock_response)

        fb = FallbackBackend(backends, ["fallback1", "fallback2"])
        result = await fb.chat([{"role": "user", "content": "hi"}])
        assert result.content == "success"
        backends[0].chat.assert_called_once()

    async def test_chat_falls_through_on_error(self, backends):
        backends[0].chat = AsyncMock(side_effect=Exception("primary down"))
        mock_response = LLMResponse(content="fallback response", model="fallback1")
        backends[1].chat = AsyncMock(return_value=mock_response)

        fb = FallbackBackend(backends, ["fallback1", "fallback2"])
        result = await fb.chat([{"role": "user", "content": "hi"}])
        assert result.content == "fallback response"
        backends[0].chat.assert_called_once()
        backends[1].chat.assert_called_once()

    async def test_chat_all_backends_fail_raises(self, backends):
        for b in backends:
            b.chat = AsyncMock(side_effect=Exception("all down"))

        fb = FallbackBackend(backends, ["fallback1", "fallback2"])
        with pytest.raises(RuntimeError, match="All LLM backends failed"):
            await fb.chat([{"role": "user", "content": "hi"}])

    async def test_chat_empty_response_falls_through(self, backends):
        # A response with no content and no tool_calls should fall through
        backends[0].chat = AsyncMock(return_value=LLMResponse(content="", model="primary"))
        backends[1].chat = AsyncMock(return_value=LLMResponse(content="real answer", model="fallback1"))

        fb = FallbackBackend(backends, ["fallback1", "fallback2"])
        result = await fb.chat([{"role": "user", "content": "hi"}])
        assert result.content == "real answer"

    async def test_health_check_aggregates(self, backends):
        backends[0].health_check = AsyncMock(return_value={"status": "healthy"})
        backends[1].health_check = AsyncMock(return_value={"status": "unhealthy", "error": "down"})
        backends[2].health_check = AsyncMock(return_value={"status": "healthy"})

        fb = FallbackBackend(backends, ["fallback1", "fallback2"])
        health = await fb.health_check()
        assert health["healthy_count"] == 2
        assert len(health["backends"]) == 3

    async def test_close_closes_all(self, backends):
        for b in backends:
            b.close = AsyncMock()

        fb = FallbackBackend(backends, ["fallback1", "fallback2"])
        await fb.close()
        for b in backends:
            b.close.assert_called_once()


class TestLLMBackendAbstract:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            LLMBackend()  # type: ignore