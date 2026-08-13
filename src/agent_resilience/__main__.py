#!/usr/bin/env python3
"""
LAR — Local Agent Runtime CLI

Usage:
    lar --config config/default.yaml "What is the latest release?"
    lar --config config/default.yaml --interactive
    python -m agent_resilience --interactive
"""

import argparse
import asyncio
from pathlib import Path

import structlog

from agent_resilience.agent import Agent
from agent_resilience.config import ConfigManager
from agent_resilience.identity import SessionIdentityValidator
from agent_resilience.router import ModelRouter


def setup_logging(log_level: str, log_format: str):
    """Configure structured logging."""
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


async def async_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Agent Runtime")
    parser.add_argument("--config", "-c", type=str, help="Path to config YAML")
    parser.add_argument("--agent-id", type=str, help="Agent ID override")
    parser.add_argument("--agent-name", type=str, help="Agent name override")
    parser.add_argument("task", nargs="?", help="Task to execute")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")

    args = parser.parse_args(argv)

    config_path = Path(args.config) if args.config else None
    config_manager = ConfigManager(config_path)
    config = config_manager.load()

    if args.agent_id:
        config.agent_id = args.agent_id
    if args.agent_name:
        config.agent_name = args.agent_name

    setup_logging(config.log_level, config.log_format)
    logger = structlog.get_logger("agent_resilience.cli")
    logger.info("lar_startup", agent_id=config.agent_id, config=str(config_manager.config_path))

    identity = SessionIdentityValidator(
        expected_agent_id=config.agent_id,
        expected_session_key=config.session_key,
        max_payload_age_seconds=config.identity.max_payload_age_seconds,
        hmac_secret=config.identity.hmac_secret,
        strict_session_key=config.identity.strict_session_key,
    )

    router = ModelRouter(
        primary=config.model.model,
        fallbacks=list(config.model.fallbacks),
    )
    agent = Agent(router=router, config=config, identity=identity)
    await agent.setup()

    try:
        if args.task:
            logger.info("executing_task", task=args.task[:100])
            result = await agent.run_async(args.task)
            print(result)
            return 0
        if args.interactive:
            print("LAR — Local Agent Runtime")
            print(f"Agent: {config.agent_name} ({config.agent_id})")
            print("Type 'exit' or 'quit' to stop.\n")

            while True:
                try:
                    task = input("\033[1;32m>>>\033[0m ")
                    if task.lower() in ("exit", "quit", "q"):
                        break
                    result = await agent.run_async(task)
                    print(f"\n{result}\n")
                except KeyboardInterrupt:
                    break
                except EOFError:
                    break
            return 0

        print("Usage: lar --config config/default.yaml 'Your task here'")
        print("       lar --config config/default.yaml --interactive")
        return 1
    finally:
        await agent.shutdown()
        logger.info("lar_shutdown", agent_id=config.agent_id)


def cli_main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    cli_main()
