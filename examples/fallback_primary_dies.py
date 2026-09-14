#!/usr/bin/env python3
"""Primary backend dies; FallbackBackend serves the request from the next model.

Offline: uses in-process fake LLM backends (no Ollama, no network).

    python examples/fallback_primary_dies.py
"""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog

from agent_resilience import FallbackBackend, LLMBackend, LLMResponse


def _silence_library_logs() -> None:
    logging.disable(logging.CRITICAL)

    def _drop(_logger: object, _method: str, _event_dict: dict) -> None:
        raise structlog.DropEvent

    structlog.configure(processors=[_drop], cache_logger_on_first_use=True)


class FakeLLMBackend(LLMBackend):
    """Minimal LLMBackend stand-in. Same pattern as tests/test_llm.py (no HTTP)."""

    def __init__(self, model: str, *, fail: bool = False, content: str = "") -> None:
        self.model = model
        self.fail = fail
        self.content = content
        self.calls = 0

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.model} is dead (simulated export-control shutdown)")
        return LLMResponse(content=self.content, model=self.model)

    async def health_check(self) -> dict:
        if self.fail:
            return {"status": "unhealthy", "error": f"{self.model} unreachable"}
        return {"status": "healthy", "model_available": True, "target_model": self.model}

    async def close(self) -> None:
        return None


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    _silence_library_logs()
    primary = FakeLLMBackend("cloud-primary", fail=True)
    fallback = FakeLLMBackend(
        "local-fallback",
        content="still working — served by local-fallback",
    )
    backend = FallbackBackend([primary, fallback], ["local-fallback"])

    print("[SETUP] primary=cloud-primary  fallback=local-fallback")
    print("[CHAT]  sending one request through FallbackBackend...")

    try:
        response = await backend.chat([{"role": "user", "content": "ping"}])
    except Exception as exc:
        print(f"FAIL: fallback chain exhausted: {exc}", file=sys.stderr)
        return 1
    finally:
        await backend.close()

    if primary.calls < 1:
        print("FAIL: primary was never tried", file=sys.stderr)
        return 1
    if response.model != "local-fallback":
        print(f"FAIL: expected local-fallback, got {response.model!r}", file=sys.stderr)
        return 1

    print(f"[PRIMARY]  cloud-primary raised after {primary.calls} call(s) — expected")
    print(f"[FALLBACK] {response.model} answered: {response.content}")
    print("SUCCESS: primary died; fallback served the request")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
