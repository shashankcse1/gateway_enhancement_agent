"""Build weekly gateway enhancement summary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.config import load_json, target_repo
from gateway_enhancement_agent.gap_analyzer import GapAnalyzer
from gateway_enhancement_agent.state_store import StateStore
from gateway_enhancement_agent.target_inventory import TargetInventory


@dataclass
class EmailConfig:
    enabled: bool
    recipient: str
    from_address: str
    subject_prefix: str
    interval_days: int
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    history_days: int

    @classmethod
    def from_env(cls) -> EmailConfig:
        raw = load_json("email.json")
        env_on = os.environ.get("WEEKLY_EMAIL_ENABLED", "").strip().lower()
        enabled = bool(raw.get("enabled", True))
        if env_on in {"0", "false", "no"}:
            enabled = False
        elif env_on in {"1", "true", "yes"}:
            enabled = True
        recipient = os.environ.get("WEEKLY_EMAIL_TO", raw.get("recipient", "shashankcse@gmail.com")).strip()
        from_addr = os.environ.get("WEEKLY_EMAIL_FROM", raw.get("from_address", "")).strip()
        if not from_addr:
            from_addr = os.environ.get("SMTP_USER", recipient)
        return cls(
            enabled=enabled,
            recipient=recipient,
            from_address=from_addr,
            subject_prefix=raw.get("subject_prefix", "[Gateway Agent]"),
            interval_days=int(os.environ.get("WEEKLY_EMAIL_INTERVAL_DAYS", raw.get("interval_days", 7))),
            smtp_host=os.environ.get("SMTP_HOST", raw.get("smtp_host", "smtp.gmail.com")),
            smtp_port=int(os.environ.get("SMTP_PORT", raw.get("smtp_port", 587))),
            smtp_use_tls=str(os.environ.get("SMTP_USE_TLS", raw.get("smtp_use_tls", True))).lower()
            not in {"0", "false", "no"},
            history_days=int(os.environ.get("WEEKLY_EMAIL_HISTORY_DAYS", raw.get("history_days", 7))),
        )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recent_cycles(state: dict[str, Any], days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent: list[dict[str, Any]] = []
    for entry in reversed(state.get("history", [])):
        started = _parse_ts(entry.get("started_at"))
        if started and started >= cutoff:
            recent.append(entry)
    return recent


def build_weekly_summary() -> dict[str, Any]:
    repo = target_repo()
    inv = TargetInventory().snapshot()
    analyzer = GapAnalyzer()
    matrix = analyzer.build_matrix()
    top_gaps = matrix[:8]
    backlog = BacklogStore().load().get("items", {})
    state = StateStore().load()
    cfg = EmailConfig.from_env()
    recent = _recent_cycles(state, cfg.history_days)

    status_counts: dict[str, int] = {}
    merges = 0
    impl_ok = 0
    for c in recent:
        status_counts[c.get("status", "unknown")] = status_counts.get(c.get("status", "unknown"), 0) + 1
        meta = c.get("metadata") or {}
        if meta.get("merge_succeeded"):
            merges += 1
        if meta.get("local_implementation_succeeded"):
            impl_ok += 1

    backlog_open = sum(1 for i in backlog.values() if i.get("status") == "open")
    backlog_closed = sum(1 for i in backlog.values() if i.get("status") == "closed")
    backlog_scheduled = sum(1 for i in backlog.values() if i.get("status") == "scheduled")

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "target_repo": str(repo),
        "inventory": {
            "gateway_routes": inv.get("gateway_route_count", 0),
            "partial_gap_endpoints": inv.get("partial_gap_count", 0),
            "gateway_tests": inv.get("gateway_test_files", []),
        },
        "gap_matrix_total": len(matrix),
        "top_gaps": [
            {
                "gap_id": g.gap_id,
                "title": g.title,
                "score": g.score,
                "coverage": g.coverage,
                "competitors": g.competitor_ids,
            }
            for g in top_gaps
        ],
        "backlog": {
            "open": backlog_open,
            "closed": backlog_closed,
            "scheduled": backlog_scheduled,
            "total": len(backlog),
        },
        "cycles": {
            "total": state.get("cycle_count", 0),
            "recent_window_days": cfg.history_days,
            "recent_count": len(recent),
            "status_counts": status_counts,
            "merges_succeeded": merges,
            "implementations_succeeded": impl_ok,
            "last_cycle": state.get("last_cycle"),
        },
    }


def weekly_summary_markdown(summary: dict[str, Any]) -> str:
    inv = summary["inventory"]
    backlog = summary["backlog"]
    cycles = summary["cycles"]
    last = cycles.get("last_cycle") or {}
    last_meta = last.get("metadata") or {}
    lines = [
        "# Gateway Weekly Summary",
        "",
        f"Generated: {summary['generated_at']}",
        f"Target repo: `{summary['target_repo']}`",
        "",
        "## Gateway inventory",
        "",
        f"- Gateway routes: **{inv['gateway_routes']}**",
        f"- Partial/Gap endpoints: **{inv['partial_gap_endpoints']}**",
        f"- Prioritized gaps: **{summary['gap_matrix_total']}**",
        "",
        "## Top gaps",
        "",
        "| Score | ID | Coverage | Title |",
        "| --- | --- | --- | --- |",
    ]
    for g in summary["top_gaps"]:
        lines.append(
            f"| {g['score']} | `{g['gap_id']}` | {g.get('coverage') or '—'} | {g['title'][:60]} |"
        )
    lines.extend(
        [
            "",
            "## Backlog",
            "",
            f"- Open: **{backlog['open']}**",
            f"- Scheduled: **{backlog['scheduled']}**",
            f"- Closed: **{backlog['closed']}**",
            f"- Total tracked: **{backlog['total']}**",
            "",
            f"## Agent activity (last {cycles['recent_window_days']} days)",
            "",
            f"- Cycles run: **{cycles['recent_count']}** (all-time: {cycles['total']})",
            f"- Status breakdown: {cycles['status_counts'] or '—'}",
            f"- Local implementations succeeded: **{cycles['implementations_succeeded']}**",
            f"- Autonomous merges succeeded: **{cycles['merges_succeeded']}**",
            "",
            "## Last cycle",
            "",
            f"- Cycle: **#{last.get('cycle_id', '—')}**",
            f"- Status: **{last.get('status', '—')}**",
            f"- Active gap: `{last.get('active_gap_id', '—')}`",
            f"- Title: {last_meta.get('active_gap_title', '—')}",
        ]
    )
    if last_meta.get("merge_commit_sha"):
        lines.append(f"- Last merge commit: `{last_meta['merge_commit_sha']}`")
    lines.append("")
    return "\n".join(lines)


def weekly_summary_subject(summary: dict[str, Any]) -> str:
    cfg = EmailConfig.from_env()
    inv = summary["inventory"]
    open_gaps = summary["backlog"]["open"]
    return (
        f"{cfg.subject_prefix} Weekly summary — "
        f"{inv['partial_gap_endpoints']} partial/gap endpoints, {open_gaps} open backlog items"
    )
