"""CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import sys

from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.capability_coverage import CapabilityCoverage
from gateway_enhancement_agent.competitor_registry import CompetitorRegistry
from gateway_enhancement_agent.competitor_web_research import CompetitorWebResearcher, maybe_refresh_competitor_research
from gateway_enhancement_agent.agent_health import assess_agent_health, health_alert_markdown
from gateway_enhancement_agent.email_notifier import EmailNotifier
from gateway_enhancement_agent.weekly_summary import build_weekly_summary, weekly_summary_markdown
from gateway_enhancement_agent.config import source_root
from gateway_enhancement_agent.config import target_repo
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.local_llm import LLMConfig, LocalLLMClient
from gateway_enhancement_agent.loop_runner import run_loop
from gateway_enhancement_agent.mirror_sync import sync_mirror
from gateway_enhancement_agent.progress_log import log_file_path, log_hint, verbose_stderr
from gateway_enhancement_agent.preflight import preflight_markdown, run_preflight
from gateway_enhancement_agent.sdlc_pipeline import SDLCPipeline
from gateway_enhancement_agent.state_store import StateStore
from gateway_enhancement_agent.target_inventory import TargetInventory
from gateway_enhancement_agent.sdlc_validate import (
    combined_report_markdown,
    combined_summary,
    run_combined_validation,
)


def _load_dotenv() -> None:
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.isfile(env_path):
        return
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def cmd_status(_: argparse.Namespace) -> int:
    store = StateStore()
    state = store.load()
    repo = target_repo()
    source = os.environ.get("TARGET_REPO_SOURCE", "").strip()
    data_dir = os.environ.get("AGENT_DATA_DIR", "").strip()

    print(f"Target repo:      {repo}")
    if source and source != str(repo):
        print(f"Source repo:      {source}")
    if data_dir:
        print(f"Data dir:         {data_dir}")
    log_path = log_file_path()
    if log_path:
        print(f"Progress log:     {log_path}")
        print(f"  tail -f \"{log_path}\"")

    print(f"Cycles completed: {state.get('cycle_count', 0)}")
    last = state.get("last_cycle")
    if last:
        print(
            f"Last cycle:       #{last.get('cycle_id')} "
            f"status={last.get('status')} phase={last.get('phase')}"
        )
        meta = last.get("metadata") or {}
        gap = last.get("active_gap_id") or meta.get("active_gap_title")
        if last.get("active_gap_id"):
            title = meta.get("active_gap_title", "")
            print(f"Active gap:       [{last.get('active_gap_id')}] {title}".rstrip())
        impl = meta.get("local_implementation_succeeded")
        if impl is True:
            files = meta.get("local_implementation_files") or []
            print(f"Implementation:   {len(files)} file(s) written")
        elif meta.get("local_implementation_skipped"):
            print(f"Implementation:   skipped — {meta['local_implementation_skipped']}")
        elif impl is False and meta.get("local_implementation_attempted"):
            print("Implementation:   attempted, not applied")
        if meta.get("validation_passed") is not None:
            print(f"Validation:       {'PASS' if meta.get('validation_passed') else 'FAIL'}")
        if meta.get("merge_commit_sha"):
            print(
                f"Last merge:       {meta['merge_commit_sha'][:12]} "
                f"pushed={meta.get('merge_pushed')}"
            )
        errors = last.get("errors") or []
        if errors:
            print("Last errors:")
            for err in errors[:3]:
                print(f"  - {err}")

    cfg = LLMConfig.from_env()
    health = LocalLLMClient(cfg).health()
    print(
        f"Ollama:           reachable={health.reachable} "
        f"model={health.model} ready={health.model_available}"
    )
    if health.error:
        print(f"  {health.error}")

    from gateway_enhancement_agent.agent_health import HealthAlertConfig, launch_agent_status

    launch = launch_agent_status(HealthAlertConfig.from_env().launch_agent_label)
    pid = launch.get("pid")
    running = launch.get("running")
    print(f"LaunchAgent:      running={running}" + (f" pid={pid}" if pid else ""))
    if launch.get("reason") and not running:
        print(f"  {launch.get('reason')}")

    return 0


def cmd_discover(_: argparse.Namespace) -> int:
    research = maybe_refresh_competitor_research()
    if research.get("refreshed"):
        print(f"Web research refreshed: {research.get('web_capabilities_found', 0)} capabilities")
    inv = TargetInventory().snapshot()
    comp = CompetitorRegistry().snapshot()
    print("=== Target inventory ===")
    print(f"Gateway routes: {inv['gateway_route_count']}")
    print(f"Partial/Gap endpoints: {inv['partial_gap_count']}")
    print(f"Gateway tests: {', '.join(inv['gateway_test_files']) or 'none'}")
    print("=== Competitors (config + web cache) ===")
    print(f"Profiles: {comp['competitor_count']} capabilities: {comp['capability_count']} (web: {comp.get('web_capability_count', 0)})")
    if comp.get("web_research_updated_at"):
        print(f"Web research cache: {comp['web_research_updated_at']}")
    return 0


def cmd_research_competitors(args: argparse.Namespace) -> int:
    result = CompetitorWebResearcher().refresh(force=args.force)
    print(json.dumps(result, indent=2))
    if result.get("refreshed"):
        print("\n" + CompetitorWebResearcher().report_markdown())
        return 0
    print(f"Skipped: {result.get('skipped', 'unknown')}")
    return 0


def cmd_analyze(_: argparse.Namespace) -> int:
    analyzer = GapAnalyzer()
    print(analyzer.report_markdown())
    top = analyzer.top_gap()
    if top:
        print(f"Top gap: [{top.gap_id}] {top.title}")
    return 0


def cmd_preflight(_: argparse.Namespace) -> int:
    report = run_preflight()
    print(preflight_markdown(report))
    return 0 if report.get("ok") else 1


def cmd_run(args: argparse.Namespace) -> int:
    log_path = log_file_path()
    if log_path and verbose_stderr():
        log_hint(f"Progress log: tail -f {log_path}")
    cycle = SDLCPipeline().run_cycle(skip_validation=args.skip_validation)
    print(f"Cycle {cycle.cycle_id} finished: status={cycle.status}")
    print(f"Artifacts: artifacts/cycle-{cycle.cycle_id:04d}/")
    if cycle.active_gap_id:
        impl = cycle.metadata.get("local_implementation_succeeded")
        if impl is True:
            files = cycle.metadata.get("local_implementation_files") or []
            print(f"Active gap: {cycle.active_gap_id} — local LLM wrote {len(files)} file(s)")
        elif cycle.metadata.get("local_implementation_skipped"):
            print(f"Active gap: {cycle.active_gap_id} — {cycle.metadata['local_implementation_skipped']}")
        else:
            print(f"Active gap: {cycle.active_gap_id} — see implementation_report.md")
    if cycle.errors:
        for err in cycle.errors:
            print(f"  error: {err}", file=sys.stderr)
        return 1
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    combined = run_combined_validation()
    print(combined_report_markdown(combined))
    return 0 if combined.passed else 1


def cmd_self_test(_: argparse.Namespace) -> int:
    from gateway_enhancement_agent.self_test_runner import SelfTestRunner

    runner = SelfTestRunner()
    results = runner.run_all()
    print(runner.report_markdown(results))
    return 0 if runner.summary(results)["passed"] else 1


def cmd_loop(args: argparse.Namespace) -> int:
    run_loop(
        interval_seconds=args.interval,
        max_cycles=args.max_cycles,
        skip_validation=args.skip_validation,
    )
    return 0


def cmd_coverage(_: argparse.Namespace) -> int:
    coverage = CapabilityCoverage()
    print(coverage.report_markdown())
    return 0


def cmd_backlog(_: argparse.Namespace) -> int:
    print(BacklogStore().report_markdown())
    return 0


def cmd_sync_mirror(_: argparse.Namespace) -> int:
    result = sync_mirror()
    print(f"Mirror: {result['mirror_dir']}")
    print(f"Copied {len(result['files_copied'])} files from {result['target_repo']}")
    for path in result["files_copied"]:
        print(f"  - {path}")
    return 0


def cmd_llm_status(_: argparse.Namespace) -> int:
    cfg = LLMConfig.from_env()
    health = LocalLLMClient(cfg).health()
    print("=== Local LLM (Ollama) ===")
    print(f"Base URL:       {health.base_url}")
    print(f"Configured:     {health.model}")
    print(f"Reachable:      {health.reachable}")
    print(f"Model ready:    {health.model_available}")
    print(f"Auto-implement: {cfg.auto_implement}")
    if health.available_models:
        print(f"Installed:      {', '.join(health.available_models[:8])}")
    if health.error:
        print(f"Error:          {health.error}")
    if health.reachable and not health.model_available:
        print(f"\nPull a model:   ollama pull {cfg.model}")
    return 0 if health.reachable and health.model_available else 1


def cmd_weekly_report(_: argparse.Namespace) -> int:
    summary = build_weekly_summary()
    print(weekly_summary_markdown(summary))
    return 0


def cmd_send_weekly_report(args: argparse.Namespace) -> int:
    result = EmailNotifier().send_weekly_report(force=args.force)
    if result.get("sent"):
        print(f"Sent to {result['recipient']}: {result['subject']}")
        return 0
    if result.get("skipped"):
        print(f"Skipped: {result['skipped']}")
        return 0
    print(f"Failed: {result.get('error', 'unknown error')}", file=sys.stderr)
    return 1


def cmd_health_check(_: argparse.Namespace) -> int:
    report = assess_agent_health()
    print(json.dumps(report, indent=2))
    print()
    print(health_alert_markdown(report))
    return 0 if report.get("healthy") else 1


def cmd_send_health_alert(args: argparse.Namespace) -> int:
    result = EmailNotifier().send_health_alert(force=args.force)
    if result.get("sent"):
        print(f"Alert sent to {result['recipient']}: {result['subject']}")
        return 0
    if result.get("skipped"):
        print(f"Skipped: {result['skipped']}")
        return 0 if result.get("report", {}).get("healthy") else 1
    print(f"Failed: {result.get('error', 'unknown error')}", file=sys.stderr)
    if result.get("report_path"):
        print(f"Saved locally: {result['report_path']}")
    return 1


def cmd_design(_: argparse.Namespace) -> int:
    design = source_root() / "docs" / "DESIGN.md"
    if design.exists():
        print(design.read_text(encoding="utf-8"))
    else:
        print("docs/DESIGN.md not found", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gateway-agent",
        description="Local competitor-gap SDLC agent — uses Ollama on this Mac (CPU/GPU), no cloud or IDE.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="Check Ollama, git, venv, and mirror before autonomous runs").set_defaults(func=cmd_preflight)
    sub.add_parser("status", help="Show loop state and target repo").set_defaults(func=cmd_status)
    sub.add_parser("discover", help="Refresh web competitor research + print inventory").set_defaults(func=cmd_discover)
    research_p = sub.add_parser("research-competitors", help="Fetch competitor docs from web and extract capabilities")
    research_p.add_argument("--force", action="store_true", help="Ignore cache TTL and refetch")
    research_p.set_defaults(func=cmd_research_competitors)
    sub.add_parser("analyze", help="Print gap matrix").set_defaults(func=cmd_analyze)
    sub.add_parser("coverage", help="Print competitor capability coverage").set_defaults(func=cmd_coverage)
    sub.add_parser("backlog", help="Print enhancement backlog").set_defaults(func=cmd_backlog)
    sub.add_parser("sync-mirror", help="Sync governance mirror from TARGET_REPO").set_defaults(func=cmd_sync_mirror)
    sub.add_parser("llm-status", help="Check local Ollama model availability").set_defaults(func=cmd_llm_status)
    sub.add_parser("weekly-report", help="Print weekly gateway summary").set_defaults(func=cmd_weekly_report)
    send_weekly = sub.add_parser("send-weekly-report", help="Email weekly gateway summary")
    send_weekly.add_argument("--force", action="store_true", help="Send even if interval not elapsed")
    send_weekly.set_defaults(func=cmd_send_weekly_report)
    sub.add_parser("health-check", help="Assess agent health (exit 1 if unhealthy)").set_defaults(func=cmd_health_check)
    send_health = sub.add_parser("send-health-alert", help="Email alert if agent is not working")
    send_health.add_argument("--force", action="store_true", help="Send even if cooldown not elapsed")
    send_health.set_defaults(func=cmd_send_health_alert)
    sub.add_parser("design", help="Print architecture design document").set_defaults(func=cmd_design)

    run_p = sub.add_parser("run", help="Run one full SDLC cycle")
    run_p.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip SDLC validation (agent self-tests + TARGET_REPO gates). Not recommended.",
    )
    run_p.set_defaults(func=cmd_run)

    sub.add_parser("self-test", help="Run agent unit tests only").set_defaults(func=cmd_self_test)

    sub.add_parser("validate", help="Run agent self-tests + TARGET_REPO validation gates").set_defaults(func=cmd_validate)

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
    repo_optional = args.command in {"health-check", "send-health-alert", "send-weekly-report", "weekly-report"}
    if not repo_optional:
        try:
            target_repo()
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
