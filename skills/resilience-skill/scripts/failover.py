"""Thin skill wrapper around the library router.

Prefer: `from agent_resilience import ModelRouter, Consolidator`.
This module exists so existing skill examples keep importing `failover`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agent_resilience.router import Consolidator, ModelConfig, ModelRouter, SwapEvent

__all__ = ["Consolidator", "ModelConfig", "ModelRouter", "SwapEvent", "main"]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LAR Model Failover — fallback chain with consolidation",
    )
    parser.add_argument("--primary", required=True, help="Primary model ID")
    parser.add_argument(
        "--fallback",
        action="append",
        default=[],
        help="Fallback model ID (can be passed multiple times)",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=Path("model_router_state.json"),
        help="Path to router state file",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show router status")
    advance = sub.add_parser("advance", help="Advance to next model in chain")
    advance.add_argument("--reason", default="manual")
    simulate = sub.add_parser("simulate-death", help="Simulate a model death and trigger failover")
    simulate.add_argument("--model-id", default=None)
    simulate.add_argument("--reason", default="Simulated Fable-style export-control shutdown")
    return parser


async def _main() -> int:
    args = _build_arg_parser().parse_args()
    router = ModelRouter(
        primary=args.primary,
        fallbacks=args.fallback,
        state_path=args.state_path,
    )

    if args.command == "status":
        print(json.dumps(router.status(), indent=2))
    elif args.command == "advance":
        new = router.advance(reason=args.reason)
        if new:
            print(json.dumps({
                "swapped": True,
                "current_model": new.model_id,
                "fallbacks_remaining": len(router.models) - router.current_index - 1,
            }, indent=2))
        else:
            print(json.dumps({"swapped": False, "reason": "fallback_chain_exhausted"}, indent=2))
            return 1
    elif args.command == "simulate-death":
        target = args.model_id or router.current.model_id
        new = router.advance(reason=args.reason)
        if new:
            print(json.dumps({
                "simulated_death": True,
                "dead_model": target,
                "new_model": new.model_id,
                "consolidation_required": True,
                "message": f"Model {target} marked dead. Agent now on {new.model_id}.",
            }, indent=2))
        else:
            print(json.dumps({
                "simulated_death": True,
                "dead_model": target,
                "new_model": None,
                "consolidation_required": False,
                "message": "Fallback chain exhausted. No model available.",
            }, indent=2))
            return 1
    return 0


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
