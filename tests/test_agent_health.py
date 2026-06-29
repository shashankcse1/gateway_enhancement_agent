from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from gateway_enhancement_agent.agent_health import (
    HealthAlertConfig,
    HealthAlertState,
    assess_agent_health,
)
from gateway_enhancement_agent.email_notifier import EmailNotifier
from gateway_enhancement_agent.weekly_summary import EmailConfig


def _local_cfg(**overrides: object) -> EmailConfig:
    base = dict(
        enabled=True,
        recipient="shashankcse@gmail.com",
        from_address="gateway-agent@localhost",
        subject_prefix="[Gateway Agent]",
        interval_hours=2,
        smtp_mode="local",
        smtp_host="127.0.0.1",
        smtp_port=25,
        smtp_use_tls=False,
        smtp_auth=False,
        history_days=1,
    )
    base.update(overrides)
    return EmailConfig(**base)


def test_assess_healthy_when_launch_running_and_recent_cycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    (runtime / "state.json").write_text(
        """{
  "cycle_count": 5,
  "last_cycle": {
    "cycle_id": 5,
    "started_at": "%s",
    "phase": "release_prep",
    "status": "done"
  },
  "history": []
}"""
        % now.isoformat(),
        encoding="utf-8",
    )
    cfg = HealthAlertConfig(
        enabled=True,
        recipient="test@example.com",
        max_stale_hours=3,
        stuck_running_hours=2,
        consecutive_failure_threshold=3,
        alert_cooldown_hours=2,
        launch_agent_label="com.gateway.enhancement-agent",
        check_ollama=False,
        loop_interval_seconds=3600,
    )
    report = assess_agent_health(
        config=cfg,
        launch_status={"running": True, "loaded": True, "pid": 123, "state": "running"},
    )
    assert report["healthy"] is True
    assert report["issues"] == []


def test_assess_unhealthy_when_launch_agent_down(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    cfg = HealthAlertConfig(
        enabled=True,
        recipient="test@example.com",
        max_stale_hours=3,
        stuck_running_hours=2,
        consecutive_failure_threshold=3,
        alert_cooldown_hours=2,
        launch_agent_label="com.gateway.enhancement-agent",
        check_ollama=False,
        loop_interval_seconds=3600,
    )
    report = assess_agent_health(
        config=cfg,
        launch_status={"running": False, "loaded": False, "reason": "not loaded"},
    )
    assert report["healthy"] is False
    assert any(issue["code"] == "launch_agent_down" for issue in report["issues"])


def test_health_alert_skips_when_healthy(mock_target_repo, tmp_path) -> None:
    notifier = EmailNotifier(_local_cfg())
    notifier.state_file = tmp_path / "email_state.json"
    with patch("gateway_enhancement_agent.email_notifier.assess_agent_health") as assess:
        assess.return_value = {"healthy": True, "checked_at": "2026-01-01T00:00:00+00:00", "issues": []}
        result = notifier.send_health_alert(force=True)
    assert result["skipped"] == "Agent healthy"


def test_health_alert_sends_when_unhealthy(mock_target_repo, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    notifier = EmailNotifier(_local_cfg())
    notifier.state_file = tmp_path / "email_state.json"
    report = {
        "healthy": False,
        "checked_at": "2026-01-01T00:00:00+00:00",
        "issues": [{"code": "launch_agent_down", "severity": "critical", "message": "down"}],
        "launch_agent": {"label": "com.gateway.enhancement-agent", "running": False},
        "last_cycle": {},
        "cycle_count": 0,
        "ollama": {"required": False, "ok": True},
    }
    with patch("gateway_enhancement_agent.email_notifier.assess_agent_health", return_value=report):
        with patch("gateway_enhancement_agent.email_notifier.smtplib.SMTP") as smtp_cls:
            server = MagicMock()
            smtp_cls.return_value.__enter__.return_value = server
            result = notifier.send_health_alert(force=True)
    assert result["sent"] is True
    server.sendmail.assert_called_once()


def test_alert_cooldown(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    state = HealthAlertState()
    recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    state.save({"last_alert_at": recent})
    assert state.alert_due(2) is False
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(microsecond=0).isoformat()
    state.save({"last_alert_at": old})
    assert state.alert_due(2) is True
