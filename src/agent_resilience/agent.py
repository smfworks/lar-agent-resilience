"""Public Agent with model-router failover and optional checkpoints."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import structlog

from agent_resilience.checkpoint import AgentState, CheckpointStore, Phase
from agent_resilience.config import RuntimeConfig
from agent_resilience.identity import SessionIdentityValidator
from agent_resilience.llm import FallbackBackend, LLMBackend, LLMResponse, OllamaBackend
from agent_resilience.router import Consolidator, ModelRouter
from agent_resilience.tools import ToolRegistry

logger = structlog.get_logger("agent_resilience.agent")


def _parse_tool_arguments(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class Agent:
    """Resilient agent loop with optional ModelRouter failover.

    Inject a fake ``llm`` in tests. Production callers can pass ``config``
    and call ``setup()`` to wire Ollama backends from that config.
    """

    def __init__(
        self,
        router: ModelRouter | None = None,
        checkpoint: CheckpointStore | Path | str | None = None,
        consolidation_steps: int = 50,
        llm: LLMBackend | None = None,
        config: RuntimeConfig | None = None,
        identity: SessionIdentityValidator | None = None,
        tool_registry: ToolRegistry | None = None,
        agency_threshold: float = 0.15,
    ):
        self.router = router
        if isinstance(checkpoint, (str, Path)):
            checkpoint = CheckpointStore(checkpoint)
        self.checkpoint = checkpoint
        self.consolidation_steps = consolidation_steps
        self.consolidator = Consolidator(
            steps=consolidation_steps,
            agency_threshold=agency_threshold,
        )
        self.llm = llm
        self.config = config
        self.identity = identity or SessionIdentityValidator(
            expected_agent_id=config.agent_id if config else "default",
            expected_session_key=config.session_key if config else "default",
            hmac_secret=config.identity.hmac_secret if config else None,
            strict_session_key=config.identity.strict_session_key if config else False,
            max_payload_age_seconds=(
                config.identity.max_payload_age_seconds if config else 300
            ),
        )
        self.tool_registry = tool_registry or ToolRegistry()
        self._message_history: list[dict] = []
        self._replay_buffer: list[dict] = []
        self.tools_enabled = True
        self.last_consolidation: dict | None = None
        self.failover_count = 0

        agent_id = config.agent_id if config else "default"
        logger.info("agent_initialized", agent_id=agent_id)

    async def setup(self) -> None:
        """Initialize Ollama backends and builtin tools from config."""
        if self.config is None:
            raise RuntimeError("Agent.setup() requires a RuntimeConfig")

        primary = OllamaBackend(
            model=self.config.model.model,
            base_url=self.config.model.base_url,
            timeout=self.config.model.timeout,
        )
        if self.config.model.fallbacks:
            fallbacks = [
                OllamaBackend(model=m, base_url=self.config.model.base_url)
                for m in self.config.model.fallbacks
            ]
            self.llm = FallbackBackend([primary] + fallbacks, self.config.model.fallbacks)
        else:
            self.llm = primary

        tool_config: dict[str, Any] = {}
        for tc in self.config.tools:
            if not tc.enabled:
                continue
            if tc.name == "exec":
                tool_config["exec"] = tc.config
            elif tc.name in ("file_read", "file_write"):
                tool_config.setdefault("file", {}).update(tc.config)

        from agent_resilience.tools.builtin import register_builtin_tools

        register_builtin_tools(self.tool_registry, tool_config)
        logger.info("builtin_tools_registered", count=len(self.tool_registry.get_tool_names()))

        health = await self.llm.health_check()
        logger.info("llm_health_check", status=health)
        logger.info("agent_setup_complete", tools=self.tool_registry.get_tool_names())

    def run(self, task: str, **kwargs) -> str:
        """Synchronous wrapper around :meth:`run_async`."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(task, **kwargs))
        raise RuntimeError("Agent.run() cannot be called from a running event loop; use await run_async()")

    async def run_async(
        self,
        task: str,
        payload: Optional[dict] = None,
        task_id: str = "default",
    ) -> str:
        """Execute one agent cycle with failover + optional checkpoint."""
        if self.llm is None:
            raise RuntimeError("No LLM backend. Pass llm=... or call setup() after providing config.")

        checkpoint_store = self.checkpoint
        step_number = 0

        if checkpoint_store:
            latest = await checkpoint_store.latest_for_task(task_id)
            if latest and not latest.is_complete:
                logger.info(
                    "resuming_from_checkpoint",
                    task_id=task_id,
                    step=latest.step_number,
                    phase=latest.phase.value,
                )
                self._message_history = list(latest.messages)
                step_number = latest.step_number
            else:
                self._message_history.append({"role": "user", "content": task})
        else:
            self._message_history.append({"role": "user", "content": task})

        if payload:
            valid, error = self.identity.validate(payload)
            if not valid:
                logger.warning(
                    "payload_rejected",
                    reason=error.result.name if error else "unknown",
                )
                return f"Payload rejected: {error.reason if error else 'unknown error'}"

        logger.info("thinking", task_preview=task[:100])
        tools = self.tool_registry.list_tools() if self.tools_enabled else None

        try:
            response = await self._chat_with_failover(
                self._message_history,
                tools=tools if tools else None,
            )
        except Exception as e:
            logger.error("llm_chat_failed", error=str(e))
            return f"Error: LLM backend failed — {str(e)}"

        step_number += 1

        if response.tool_calls and self.tools_enabled:
            logger.info("tool_calls_detected", count=len(response.tool_calls))
            tool_results = []
            for tool_call in response.tool_calls:
                func = tool_call.get("function", {})
                name = func.get("name", "")
                arguments = _parse_tool_arguments(func.get("arguments", {}))

                if name in self.tool_registry:
                    result = await self.tool_registry.execute(name, **arguments)
                    tool_results.append({"tool": name, "result": result.to_dict()})
                else:
                    tool_results.append(
                        {"tool": name, "error": f"Tool '{name}' not found in registry"}
                    )

            self._message_history.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": response.tool_calls,
                }
            )
            for result in tool_results:
                self._message_history.append({"role": "tool", "content": json.dumps(result)})

            if checkpoint_store:
                await self._save_checkpoint(
                    checkpoint_store,
                    task_id,
                    step_number,
                    Phase.ACT,
                    response,
                    complete=False,
                    tool_calls=response.tool_calls,
                    tool_results=[str(r) for r in tool_results],
                )

            logger.info("rethinking_with_tool_results", results=len(tool_results))
            try:
                response = await self._chat_with_failover(self._message_history, tools=None)
            except Exception as e:
                logger.error("llm_rethink_failed", error=str(e))
                return f"Error: LLM failed after tool execution — {str(e)}"

        self._message_history.append({"role": "assistant", "content": response.content})
        self._replay_buffer.append({"input": task, "output": response.content})

        if checkpoint_store:
            await self._save_checkpoint(
                checkpoint_store,
                task_id,
                step_number,
                Phase.RESPOND,
                response,
                complete=True,
            )
            logger.info("cycle_complete_checkpointed")

        logger.info(
            "cycle_complete",
            response_preview=(response.content or "")[:200],
            history_length=len(self._message_history),
        )
        return response.content

    async def _chat_with_failover(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> LLMResponse:
        assert self.llm is not None
        try:
            response = await self.llm.chat(messages, tools=tools)
            if not response.content and not response.tool_calls:
                raise RuntimeError("empty LLM response")
            return response
        except Exception as first_error:
            if not self.router or not self.router.has_fallback():
                raise
            logger.warning("llm_failover", error=str(first_error), current=self.router.current.model_id)
            await self._failover(reason=str(first_error))
            if getattr(self.llm, "model", None) is not None:
                try:
                    self.llm.model = self.router.current.model_id
                except Exception:
                    pass
            response = await self.llm.chat(messages, tools=tools if self.tools_enabled else None)
            if not response.content and not response.tool_calls:
                raise RuntimeError("empty LLM response after failover")
            return response

    async def _failover(self, reason: str) -> None:
        if not self.router:
            return
        previous = self.router.current.model_id
        new = self.router.advance(reason=reason)
        if new is None:
            raise RuntimeError(f"fallback chain exhausted after failure of {previous}")

        self.tools_enabled = False
        self.failover_count += 1

        async def predict(obs: str):
            if self.llm is None:
                return f"consolidated-{new.model_id}"
            try:
                result = await self.llm.chat([{"role": "user", "content": f"predict:{obs}"}])
                return result.content
            except Exception:
                return f"consolidated-{new.model_id}"

        buffer = self._replay_buffer or [{"input": "settling"}]
        metrics = await self.consolidator.consolidate(predict, buffer)
        self.last_consolidation = metrics
        self.router.record_consolidation(
            steps=metrics["steps"],
            recovery=metrics["recovery"],
            duration_seconds=metrics["duration_seconds"],
        )
        self.tools_enabled = bool(metrics.get("threshold_met", False))
        logger.info(
            "failover_complete",
            from_model=previous,
            to_model=new.model_id,
            tools_enabled=self.tools_enabled,
            consolidation=metrics,
        )

    async def _save_checkpoint(
        self,
        store: CheckpointStore,
        task_id: str,
        step_number: int,
        phase: Phase,
        response: LLMResponse,
        complete: bool,
        tool_calls: list | None = None,
        tool_results: list | None = None,
    ) -> str:
        state = AgentState(
            task_id=task_id,
            step_number=step_number,
            phase=phase,
            context={},
            messages=self._message_history.copy(),
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
            memory_snapshot={},
            is_complete=complete,
            iteration=step_number,
            model_used=getattr(response, "model_used", None) or getattr(response, "model", "") or "unknown",
            tools_available=self.tool_registry.get_tool_names(),
            checkpoint_reason="step_boundary",
        )
        return await store.save(state)

    async def shutdown(self) -> None:
        if self.llm and hasattr(self.llm, "close"):
            await self.llm.close()
        logger.info("agent_shutdown")


# Back-compat name used by the original CLI.
AgentLoop = Agent
