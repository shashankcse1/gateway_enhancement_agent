from __future__ import annotations

from unittest.mock import patch

from gateway_enhancement_agent.email_notifier import EmailNotifier
from gateway_enhancement_agent.weekly_summary import EmailConfig


def test_send_skips_without_smtp_credentials(mock_target_repo, monkeypatch) -> None:
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    cfg = EmailConfig(
        enabled=True,
        recipient="shashankcse@gmail.com",
        from_address="shashankcse@gmail.com",
        subject_prefix="[Gateway Agent]",
        interval_days=7,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_use_tls=True,
        history_days=7,
    )
    result = EmailNotifier(cfg).send_weekly_report(force=True)
    assert result["sent"] is False
    assert "SMTP credentials" in result.get("error", "")


def test_due_when_never_sent(mock_target_repo) -> None:
    cfg = EmailConfig(
        enabled=True,
        recipient="shashankcse@gmail.com",
        from_address="shashankcse@gmail.com",
        subject_prefix="[Gateway Agent]",
        interval_days=7,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_use_tls=True,
        history_days=7,
    )
    notifier = EmailNotifier(cfg)
    assert notifier.due() is True
