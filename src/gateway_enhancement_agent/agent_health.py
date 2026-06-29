"""Detect when the background SDLC agent is unhealthy and format alert emails."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from gateway_enhancement_agent.config import load_json, runtime_dir
from gateway_enhancement_agent.local_llm import LLMConfig, LocalLLMClient
from gateway_enhancement_agent.state_store import StateStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class HealthAlertConfig:
    enabled: bool
    recipient: str
    max_stale_hours: float
    stuck_running_hours: float
    consecutive_failure_threshold: int
    alert_cooldown_hours: float
    launch_agent_label: str
    check_ollama: bool
    loop_interval_seconds: int

    @classmethod
    def from_env(cls) -> HealthAlertConfig:
        raw = load_json("email.json")
        alert = raw.get("health_alert", {})
        env_on = os.environ.get("HEALTH_ALERT_ENABLED", "").strip().lower()
        enabled = bool(alert.get("enabled", True))
        if env_on in {"0", "false", "no"}:
            enabled = False
        elif env_on in {"1", "true", "yes"}:
            enabled = True
        recipient = os.environ.get(
            "HEALTH_ALERT_TO",
            alert.get("recipient", raw.get("recipient", "shashankcse@gmail.com")),
        ).strip()
        loop_interval = int(os.environ.get("LOOP_INTERVAL_SECONDS", alert.get("loop_interval_seconds", 3600)))
        default_stale = (loop_interval / 3600) * 2 + 1
        return cls(
            enabled=enabled,
            recipient=recipient,
            max_stale_hours=float(os.environ.get("HEALTH_ALERT_MAX_STALE_HOURS", alert.get("max_stale_hours", default_stale))),
            stuck_running_hours=float(
                os.environ.get("HEALTH_ALERT_STUCK_HOURS", alert.get("stuck_running_hours", 2))
            ),
            consecutive_failure_threshold=int(
                os.environ.get(
                    "HEALTH_ALERT_FAILURE_THRESHOLD",
                    alert.get("consecutive_failure_threshold", 3),
                )
            ),
            alert_cooldown_hours=float(
                os.environ.get("HEALTH_ALERT_COOLDOWN_HOURS", alert.get("alert_cooldown_hours", 2))
            ),
            launch_agent_label=str(
                alert.get("launch_agent_label", "com.gateway.enhancement-agent")
            ),
            check_ollama=bool(alert.get("check_ollama", True)),
            loop_interval_seconds=loop_interval,
        )


def launch_agent_status(label: str) -> dict[str, Any]:
    uid = os.getuid()
    target = f"gui/{uid}/{label}"
    try:
        result = subprocess.run(
            ["launchctl", "print", target],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"running": False, "loaded": False, "reason": str(exc), "label": label}

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return {"running": False, "loaded": False, "reason": "not loaded", "detail": detail, "label": label}

    pid: int | None = None
    state: str | None = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("pid ="):
            try:
                pid = int(stripped.split("=", 1)[1].strip())
            except ValueError:
                pid = None
        elif lower.startswith("state ="):
            state = stripped.split("=", 1)[1].strip()

    running = pid is not None and pid > 0
    return {
        "running": running,
        "loaded": True,
        "pid": pid,
        "state": state,
        "label": label,
    }


def ollama_status() -> dict[str, Any]:
    enabled = os.environ.get("LOCAL_LLM_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        return {"required": False, "ok": True, "reason": "LOCAL_LLM_ENABLED=0"}
    cfg = LLMConfig.from_env()
    client = LocalLLMClient(cfg)
    try:
        health = client.health()
        ok = health.reachable and health.model_available
        reason = health.error
    except Exception as exc:  # noqa: BLE001
        return {"required": True, "ok": False, "reason": str(exc)}
    return {
        "required": True,
        "ok": ok,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "reason": reason,
    }


def assess_agent_health(
    *,
    config: HealthAlertConfig | None = None,
    launch_status: dict[str, Any] | None = None,
    ollama: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or HealthAlertConfig.from_env()
    store = StateStore()
    state = store.load()
    last_cycle = state.get("last_cycle") or {}
    history = state.get("history") or []
    now = _utc_now()

    issues: list[dict[str, str]] = []
    launch = launch_status if launch_status is not None else launch_agent_status(cfg.launch_agent_label)

    if not launch.get("running"):
        reason = launch.get("reason", "unknown")
        issues.append(
            {
                "code": "launch_agent_down",
                "severity": "critical",
                "message": f"LaunchAgent {cfg.launch_agent_label} is not running ({reason}).",
            }
        )

    started_at = _parse_iso(last_cycle.get("started_at"))
    status = str(last_cycle.get("status", "")).lower()
    cycle_id = last_cycle.get("cycle_id")

    if not last_cycle:
        issues.append(
            {
                "code": "no_cycles",
                "severity": "warning",
                "message": "No SDLC cycles recorded in state.json yet.",
            }
        )
    elif status == "running" and started_at:
        stuck_for = now - started_at
        if stuck_for >= timedelta(hours=cfg.stuck_running_hours):
            issues.append(
                {
                    "code": "cycle_stuck",
                    "severity": "critical",
                    "message": (
                        f"Cycle #{cycle_id} has been running for "
                        f"{stuck_for.total_seconds() / 3600:.1f}h (phase={last_cycle.get('phase')})."
                    ),
                }
            )
    else:
        reference = started_at
        if reference and now - reference >= timedelta(hours=cfg.max_stale_hours):
            issues.append(
                {
                    "code": "cycle_stale",
                    "severity": "critical",
                    "message": (
                        f"Last cycle #{cycle_id} is stale — last activity "
                        f"{reference.isoformat()} ({(now - reference).total_seconds() / 3600:.1f}h ago)."
                    ),
                }
            )

    if cfg.consecutive_failure_threshold > 0 and history:
        recent = history[-cfg.consecutive_failure_threshold :]
        if len(recent) >= cfg.consecutive_failure_threshold:
            failed = all(
                str(item.get("status", "")).lower() in {"failed", "error"}
                or bool(item.get("errors"))
                for item in recent
            )
            if failed:
                issues.append(
                    {
                        "code": "consecutive_failures",
                        "severity": "warning",
                        "message": (
                            f"Last {cfg.consecutive_failure_threshold} cycles failed or reported errors."
                        ),
                    }
                )

    llm = ollama if ollama is not None else (ollama_status() if cfg.check_ollama else {"required": False, "ok": True})
    if llm.get("required") and not llm.get("ok"):
        issues.append(
            {
                "code": "ollama_down",
                "severity": "warning",
                "message": f"Ollama is unreachable ({llm.get('reason', 'unavailable')}).",
            }
        )

    healthy = not issues
    return {
        "healthy": healthy,
        "checked_at": now.replace(microsecond=0).isoformat(),
        "issues": issues,
        "launch_agent": launch,
        "last_cycle": last_cycle,
        "cycle_count": state.get("cycle_count", 0),
        "ollama": llm,
        "config": {
            "max_stale_hours": cfg.max_stale_hours,
            "stuck_running_hours": cfg.stuck_running_hours,
            "loop_interval_seconds": cfg.loop_interval_seconds,
        },
    }


def health_alert_markdown(report: dict[str, Any]) -> str:
    lines = [
        "Gateway Enhancement Agent — HEALTH ALERT",
        "",
        f"Checked at: {report.get('checked_at')}",
        f"Cycles completed: {report.get('cycle_count', 0)}",
        "",
        "Issues detected:",
    ]
    for issue in report.get("issues", []):
        lines.append(f"  - [{issue.get('severity', 'unknown').upper()}] {issue.get('message')}")
    lines.extend(["", "LaunchAgent:"])
    launch = report.get("launch_agent", {})
    lines.append(f"  label:   {launch.get('label')}")
    lines.append(f"  loaded:  {launch.get('loaded')}")
    lines.append(f"  running: {launch.get('running')} (pid={launch.get('pid')}, state={launch.get('state')})")
    last = report.get("last_cycle") or {}
    if last:
        lines.extend(
            [
                "",
                "Last cycle:",
                f"  id:     #{last.get('cycle_id')}",
                f"  status: {last.get('status')}",
                f"  phase:  {last.get('phase')}",
                f"  started:{last.get('started_at')}",
            ]
        )
        if last.get("errors"):
            lines.append("  errors:")
            for err in last["errors"][-5:]:
                lines.append(f"    - {err}")
    ollama = report.get("ollama") or {}
    if ollama.get("required"):
        lines.extend(
            [
                "",
                "Ollama:",
                f"  ok:    {ollama.get('ok')}",
                f"  model: {ollama.get('model')}",
                f"  url:   {ollama.get('base_url')}",
            ]
        )
    lines.extend(
        [
            "",
            "Recovery commands:",
            "  make agent-status",
            "  make login-install",
            "  tail -f ~/Library/Application\\ Support/gateway-enhancement-agent/.runtime/launchd.err.log",
        ]
    )
    return "\n".join(lines) + "\n"


def health_alert_subject(report: dict[str, Any], *, prefix: str = "[Gateway Agent]") -> str:
    codes = [issue.get("code", "issue") for issue in report.get("issues", [])]
    summary = ", ".join(codes[:3]) or "unhealthy"
    return f"{prefix} ALERT — agent not working ({summary})"


class HealthAlertState:
    def __init__(self) -> None:
        self.state_file = runtime_dir() / "health_alert_state.json"

    def load(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"last_alert_at": None, "last_healthy_at": None, "last_error": None}
        import json

        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, Any]) -> None:
        import json

        self.state_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def alert_due(self, cooldown_hours: float) -> bool:
        state = self.load()
        last = state.get("last_alert_at")
        if not last:
            return True
        last_dt = _parse_iso(last)
        if not last_dt:
            return True
        return _utc_now() - last_dt >= timedelta(hours=cooldown_hours)
