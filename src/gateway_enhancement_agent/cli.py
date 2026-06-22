"""CLI entrypoint."""

from __future__ import annotations

import argparse
import os
import sys

from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.config import target_repo
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.loop_runner import run_loop
from gateway_enhancement_agent.sdlc_pipeline import SDLCPipeline
from gateway_enhancement_agent.state_store import StateStore
from gateway_enhancement_agent.target_inventory import TargetInventory
from gateway_enhancement_agent.validation_runner import ValidationRunner


def _load_dotenv() -> None:
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.isfile(env_path):
        return
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def cmd_status(_: argparse.Namespace) -> int:
    store = StateStore()
    state = store.load()
    repo = target_repo()
    print(f"Target repo: {repo}")
    print(f"Cycles completed: {state.get('cycle_count', 0)}")
    last = state.get("last_cycle")
    if last:
        print(f"Last cycle: #{last.get('cycle_id')} status={last.get('status')} phase={last.get('phase')}")
    return 0


def cmd_discover(_: argparse.Namespace) -> int:
    inv = TargetInventory().snapshot()
    comp = CompetitorRegistry().snapshot()
    print("=== Target inventory ===")
    print(f"Gateway routes: {inv['gateway_route_count']}")
    print(f"Partial/Gap endpoints: {inv['partial_gap_count']}")
    print(f"Gateway tests: {', '.join(inv['gateway_test_files']) or 'none'}")
    print("=== Competitors (local) ===")
    print(f"Profiles: {comp['competitor_count']} capabilities: {comp['capability_count']}")
    return 0


def cmd_analyze(_: argparse.Namespace) -> int:
    analyzer = GapAnalyzer()
    print(analyzer.report_markdown())
    top = analyzer.top_gap()
    if top:
        print(f"Top gap: [{top.gap_id}] {top.title}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cycle = SDLCPipeline().run_cycle(skip_validation=args.skip_validation)
    print(f"Cycle {cycle.cycle_id} finished: status={cycle.status}")
    print(f"Artifacts: artifacts/cycle-{cycle.cycle_id:04d}/")
    if cycle.active_gap_id:
        print(f"Active gap: {cycle.active_gap_id} — open agent_work_order.md in Cursor")
    if cycle.errors:
        for err in cycle.errors:
            print(f"  error: {err}", file=sys.stderr)
        return 1
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    results = ValidationRunner().run_all()
    print(ValidationRunner().report_markdown(results))
    return 0 if ValidationRunner().summary(results)["passed"] else 1


def cmd_loop(args: argparse.Namespace) -> int:
    run_loop(
        interval_seconds=args.interval,
        max_cycles=args.max_cycles,
        skip_validation=args.skip_validation,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gateway-agent",
        description="Local competitor-gap SDLC agent for external gateway repos (no cloud).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show loop state and target repo").set_defaults(func=cmd_status)
    sub.add_parser("discover", help="Print inventory and competitor snapshot").set_defaults(func=cmd_discover)
    sub.add_parser("analyze", help="Print gap matrix").set_defaults(func=cmd_analyze)

    run_p = sub.add_parser("run", help="Run one full SDLC cycle")
    run_p.add_argument("--skip-validation", action="store_true", help="Skip pytest/smoke gates")
    run_p.set_defaults(func=cmd_run)

    sub.add_parser("validate", help="Run validation gates in TARGET_REPO").set_defaults(func=cmd_validate)

    loop_p = sub.add_parser("loop", help="Run SDLC cycles continuously")
    loop_p.add_argument("--interval", type=int, default=int(os.environ.get("LOOP_INTERVAL_SECONDS", "3600")))
    loop_p.add_argument("--max-cycles", type=int, default=int(os.environ.get("MAX_CYCLES", "0")))
    loop_p.add_argument("--skip-validation", action="store_true")
    loop_p.set_defaults(func=cmd_loop)

    return parser


def main() -> None:
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    try:
        target_repo()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
