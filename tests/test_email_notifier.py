from __future__ import annotations

from unittest.mock import MagicMock, patch

from gateway_enhancement_agent.email_notifier import EmailNotifier
from gateway_enhancement_agent.weekly_summary import EmailConfig


def _relay_cfg(**overrides: object) -> EmailConfig:
    base = dict(
        enabled=True,
        recipient="shashankcse@gmail.com",
        from_address="shashankcse@gmail.com",
        subject_prefix="[Gateway Agent]",
        interval_hours=2,
        smtp_mode="relay",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_use_tls=True,
        smtp_auth=True,
        history_days=1,
    )
    base.update(overrides)
    return EmailConfig(**base)


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


def test_send_skips_without_smtp_credentials(mock_target_repo, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    notifier = EmailNotifier(_relay_cfg())
    notifier.state_file = tmp_path / "email_state.json"
    result = notifier.send_weekly_report(force=True)
    assert result["sent"] is False
    assert "SMTP credentials" in result.get("error", "")


def test_local_smtp_does_not_require_credentials(mock_target_repo, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    notifier = EmailNotifier(_local_cfg())
    notifier.state_file = tmp_path / "email_state.json"
    with patch("gateway_enhancement_agent.email_notifier.smtplib.SMTP") as smtp_cls:
        server = MagicMock()
        smtp_cls.return_value.__enter__.return_value = server
        result = notifier.send_weekly_report(force=True)
    assert result["sent"] is True
    assert result["smtp_mode"] == "local"
    server.login.assert_not_called()
    server.starttls.assert_not_called()
    server.sendmail.assert_called_once()


def test_due_when_never_sent(mock_target_repo, tmp_path) -> None:
    notifier = EmailNotifier(_local_cfg())
    notifier.state_file = tmp_path / "email_state.json"
    assert notifier.due() is True


def test_not_due_within_interval(mock_target_repo, tmp_path) -> None:
    notifier = EmailNotifier(_local_cfg())
    notifier.state_file = tmp_path / "email_state.json"
    notifier.save_state({"last_sent_at": "2099-01-01T00:00:00+00:00", "last_error": None})
    assert notifier.due() is False
