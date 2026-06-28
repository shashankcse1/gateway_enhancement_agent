from __future__ import annotations

from unittest.mock import patch

from gateway_enhancement_agent.email_notifier import EmailNotifier
from gateway_enhancement_agent.weekly_summary import EmailConfig


def test_send_skips_without_smtp_credentials(mock_target_repo, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    cfg = EmailConfig(
        enabled=True,
        recipient="shashankcse@gmail.com",
        from_address="shashankcse@gmail.com",
        subject_prefix="[Gateway Agent]",
        interval_hours=2,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_use_tls=True,
        history_days=7,
    )
    notifier = EmailNotifier(cfg)
    notifier.state_file = tmp_path / "email_state.json"
    result = notifier.send_weekly_report(force=True)
    assert result["sent"] is False
    assert "SMTP credentials" in result.get("error", "")


def test_due_when_never_sent(mock_target_repo, tmp_path) -> None:
    cfg = EmailConfig(
        enabled=True,
        recipient="shashankcse@gmail.com",
        from_address="shashankcse@gmail.com",
        subject_prefix="[Gateway Agent]",
        interval_hours=2,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_use_tls=True,
        history_days=1,
    )
    notifier = EmailNotifier(cfg)
    notifier.state_file = tmp_path / "email_state.json"
    assert notifier.due() is True


def test_not_due_within_interval(mock_target_repo, tmp_path) -> None:
    cfg = EmailConfig(
        enabled=True,
        recipient="shashankcse@gmail.com",
        from_address="shashankcse@gmail.com",
        subject_prefix="[Gateway Agent]",
        interval_hours=2,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_use_tls=True,
        history_days=1,
    )
    notifier = EmailNotifier(cfg)
    notifier.state_file = tmp_path / "email_state.json"
    notifier.save_state({"last_sent_at": "2099-01-01T00:00:00+00:00", "last_error": None})
    assert notifier.due() is False
