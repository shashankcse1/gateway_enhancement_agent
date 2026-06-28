"""Build weekly gateway enhancement summary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from gateway_enhancement_agent.backlog import BacklogStore
from gateway_enhancement_agent.capability_coverage import CapabilityCoverage
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
    interval_hours: int
    smtp_mode: str
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    smtp_auth: bool
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
        smtp_mode = os.environ.get("SMTP_MODE", raw.get("smtp_mode", "local")).strip().lower()
        interval_hours = raw.get("interval_hours")
        if interval_hours is None and raw.get("interval_days") is not None:
            interval_hours = int(raw["interval_days"]) * 24
        interval_hours = int(
            os.environ.get(
                "EMAIL_INTERVAL_HOURS",
                os.environ.get("WEEKLY_EMAIL_INTERVAL_HOURS", interval_hours or 2),
            )
        )

        if smtp_mode == "local":
            smtp_host = os.environ.get("SMTP_HOST", raw.get("smtp_host", "127.0.0.1"))
            smtp_port = int(os.environ.get("SMTP_PORT", raw.get("smtp_port", 25)))
            smtp_use_tls = False
            smtp_auth = False
        else:
            smtp_host = os.environ.get("SMTP_HOST", raw.get("smtp_host", "smtp.gmail.com"))
            smtp_port = int(os.environ.get("SMTP_PORT", raw.get("smtp_port", 587)))
            smtp_use_tls = str(os.environ.get("SMTP_USE_TLS", raw.get("smtp_use_tls", True))).lower() not in {
                "0",
                "false",
                "no",
            }
            smtp_auth = str(os.environ.get("SMTP_AUTH", raw.get("smtp_auth", True))).lower() not in {
                "0",
                "false",
                "no",
            }

        from_addr = os.environ.get("WEEKLY_EMAIL_FROM", raw.get("from_address", "")).strip()
        if not from_addr:
            from_addr = os.environ.get("SMTP_FROM", "").strip()
        if not from_addr:
            from_addr = os.environ.get("SMTP_USER", "").strip()
        if not from_addr:
            from_addr = "gateway-agent@localhost" if smtp_mode == "local" else recipient

        return cls(
            enabled=enabled,
            recipient=recipient,
            from_address=from_addr,
            subject_prefix=raw.get("subject_prefix", "[Gateway Agent]"),
            interval_hours=max(1, interval_hours),
            smtp_mode=smtp_mode,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_use_tls=smtp_use_tls,
            smtp_auth=smtp_auth,
            history_days=int(os.environ.get("WEEKLY_EMAIL_HISTORY_DAYS", raw.get("history_days", 1))),
        )

    @classmethod
    def report_limits(cls) -> dict[str, int]:
        raw = load_json("email.json")
        return {
            "gap_matrix_limit": int(os.environ.get("EMAIL_GAP_MATRIX_LIMIT", raw.get("gap_matrix_limit", 25))),
            "capability_matrix_limit": int(
                os.environ.get("EMAIL_CAPABILITY_MATRIX_LIMIT", raw.get("capability_matrix_limit", 40))
            ),
        }


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


def _build_performance_summary(recent: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    phase_at_failure: dict[str, int] = {}
    merges = impl_ok = val_ok = 0
    for c in recent:
        status = c.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        meta = c.get("metadata") or {}
        if meta.get("merge_succeeded"):
            merges += 1
        if meta.get("local_implementation_succeeded"):
            impl_ok += 1
        if meta.get("validation_passed"):
            val_ok += 1
        if status == "failed":
            phase = c.get("phase", "unknown")
            phase_at_failure[phase] = phase_at_failure.get(phase, 0) + 1
    total = len(recent)
    completed = status_counts.get("completed", 0)
    failed = status_counts.get("failed", 0)
    success_rate = round((completed / total) * 100, 1) if total else 0.0
    return {
        "window_cycles": total,
        "status_counts": status_counts,
        "success_rate_pct": success_rate,
        "failed_cycles": failed,
        "completed_cycles": completed,
        "implementations_succeeded": impl_ok,
        "merges_succeeded": merges,
        "validations_passed": val_ok,
        "failures_by_phase": phase_at_failure,
    }


def _coverage_status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def build_weekly_summary() -> dict[str, Any]:
    repo = target_repo()
    inv = TargetInventory().snapshot()
    analyzer = GapAnalyzer()
    matrix = analyzer.build_matrix()
    limits = EmailConfig.report_limits()
    gap_matrix_limit = limits["gap_matrix_limit"]
    capability_limit = limits["capability_matrix_limit"]
    coverage_builder = CapabilityCoverage()
    coverage_rows = coverage_builder.to_json()
    top_gaps = matrix[:8]
    gap_matrix_rows = matrix[:gap_matrix_limit]
    capability_matrix_rows = coverage_rows[:capability_limit]
    backlog = BacklogStore().load().get("items", {})
    state = StateStore().load()
    cfg = EmailConfig.from_env()
    recent = _recent_cycles(state, cfg.history_days)
    performance = _build_performance_summary(recent)

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
        "gap_matrix_published": len(gap_matrix_rows),
        "gap_matrix": [
            {
                "gap_id": g.gap_id,
                "title": g.title,
                "score": g.score,
                "coverage": g.coverage,
                "source": g.source,
                "route": g.route,
                "competitors": g.competitor_ids,
            }
            for g in gap_matrix_rows
        ],
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
        "capability_matrix_total": len(coverage_rows),
        "capability_matrix_published": len(capability_matrix_rows),
        "capability_matrix": capability_matrix_rows,
        "capability_status_counts": _coverage_status_counts(coverage_rows),
        "performance": performance,
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
    performance = summary.get("performance") or {}
    capability_counts = summary.get("capability_status_counts") or {}
    last = cycles.get("last_cycle") or {}
    last_meta = last.get("metadata") or {}
    lines = [
        "# Gateway Agent Summary",
        "",
        f"Generated: {summary['generated_at']}",
        f"Target repo: `{summary['target_repo']}`",
        "",
        "## Agent performance",
        "",
        f"- Window cycles: **{performance.get('window_cycles', 0)}** (last {cycles['recent_window_days']} day(s))",
        f"- Success rate: **{performance.get('success_rate_pct', 0)}%** "
        f"({performance.get('completed_cycles', 0)} completed / {performance.get('failed_cycles', 0)} failed)",
        f"- Implementations succeeded: **{performance.get('implementations_succeeded', 0)}**",
        f"- Validations passed: **{performance.get('validations_passed', 0)}**",
        f"- Autonomous merges succeeded: **{performance.get('merges_succeeded', 0)}**",
    ]
    failures_by_phase = performance.get("failures_by_phase") or {}
    if failures_by_phase:
        lines.append(f"- Failures by phase: `{failures_by_phase}`")
    lines.extend(
        [
            "",
            "## Gateway inventory",
            "",
            f"- Gateway routes: **{inv['gateway_routes']}**",
            f"- Partial/Gap endpoints: **{inv['partial_gap_endpoints']}**",
            f"- Prioritized gaps: **{summary['gap_matrix_total']}**",
            "",
            "## Gap matrix",
            "",
            f"Showing **{summary.get('gap_matrix_published', 0)}** of **{summary['gap_matrix_total']}** prioritized items.",
            "",
            "| Score | ID | Coverage | Source | Title |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for g in summary.get("gap_matrix", []):
        lines.append(
            f"| {g['score']} | `{g['gap_id']}` | {g.get('coverage') or '—'} | {g.get('source') or '—'} | {g['title'][:55]} |"
        )
    if summary.get("gap_matrix_total", 0) > summary.get("gap_matrix_published", 0):
        remaining = summary["gap_matrix_total"] - summary["gap_matrix_published"]
        lines.append(f"\n_…and {remaining} more gap items._")
    lines.extend(
        [
            "",
            "## Capability coverage matrix",
            "",
            f"Status counts: full **{capability_counts.get('full', 0)}**, "
            f"partial **{capability_counts.get('partial', 0)}**, "
            f"gap **{capability_counts.get('gap', 0)}**, "
            f"unknown **{capability_counts.get('unknown', 0)}**",
            "",
            f"Showing **{summary.get('capability_matrix_published', 0)}** of "
            f"**{summary.get('capability_matrix_total', 0)}** competitor capabilities.",
            "",
            "| Priority | Competitor | Capability | Status | Routes |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in summary.get("capability_matrix", []):
        routes = row.get("matched_routes") or []
        route_preview = ", ".join(routes[:2]) or "—"
        if len(routes) > 2:
            route_preview += f" (+{len(routes) - 2})"
        lines.append(
            f"| {row.get('priority', '—')} | {row.get('competitor_name', '—')} | "
            f"{row.get('label', '—')} | {row.get('status', '—')} | {route_preview} |"
        )
    if summary.get("capability_matrix_total", 0) > summary.get("capability_matrix_published", 0):
        remaining = summary["capability_matrix_total"] - summary["capability_matrix_published"]
        lines.append(f"\n_…and {remaining} more capability rows._")
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
            "",
            "## Last cycle",
            "",
            f"- Cycle: **#{last.get('cycle_id', '—')}**",
            f"- Status: **{last.get('status', '—')}**",
            f"- Phase: **{last.get('phase', '—')}**",
            f"- Active gap: `{last.get('active_gap_id', '—')}`",
            f"- Title: {last_meta.get('active_gap_title', '—')}",
        ]
    )
    if last.get("errors"):
        lines.append(f"- Errors: {last['errors'][:2]}")
    if last_meta.get("merge_commit_sha"):
        lines.append(f"- Last merge commit: `{last_meta['merge_commit_sha']}`")
    lines.append("")
    return "\n".join(lines)


def weekly_summary_subject(summary: dict[str, Any]) -> str:
    cfg = EmailConfig.from_env()
    inv = summary["inventory"]
    perf = summary.get("performance") or {}
    caps = summary.get("capability_status_counts") or {}
    return (
        f"{cfg.subject_prefix} Summary — "
        f"{summary.get('gap_matrix_total', 0)} gaps, "
        f"{caps.get('gap', 0)} capability gaps, "
        f"{perf.get('success_rate_pct', 0)}% cycle success"
    )
