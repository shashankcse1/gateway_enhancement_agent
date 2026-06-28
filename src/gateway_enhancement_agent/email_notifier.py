"""Send gateway summary email via SMTP on a configurable interval."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from gateway_enhancement_agent.config import runtime_dir
from gateway_enhancement_agent.weekly_summary import (
    EmailConfig,
    build_weekly_summary,
    weekly_summary_markdown,
    weekly_summary_subject,
)


class EmailNotifier:
    def __init__(self, config: EmailConfig | None = None) -> None:
        self.config = config or EmailConfig.from_env()
        self.state_file = runtime_dir() / "email_state.json"

    def load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"last_sent_at": None, "last_error": None}
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def save_state(self, payload: dict[str, Any]) -> None:
        self.state_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def due(self) -> bool:
        if not self.config.enabled:
            return False
        state = self.load_state()
        last = state.get("last_sent_at")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        except ValueError:
            return True
        return datetime.now(timezone.utc) - last_dt >= timedelta(hours=self.config.interval_hours)

    def send_weekly_report(self, *, force: bool = False) -> dict[str, Any]:
        if not self.config.enabled:
            return {"sent": False, "skipped": "Summary email disabled"}
        if not force and not self.due():
            return {"sent": False, "skipped": "Not due yet"}

        summary = build_weekly_summary()
        body = weekly_summary_markdown(summary)
        subject = weekly_summary_subject(summary)
        recipient = self.config.recipient

        smtp_user = os.environ.get("SMTP_USER", "").strip()
        smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
        if self.config.smtp_auth and (not smtp_user or not smtp_password):
            msg = (
                "SMTP credentials missing. Set SMTP_USER and SMTP_PASSWORD in .env "
                "(or use SMTP_MODE=local for macOS Postfix on 127.0.0.1:25)."
            )
            self.save_state({**self.load_state(), "last_error": msg})
            return {"sent": False, "error": msg, "summary": summary}

        try:
            self._send_smtp(
                subject=subject,
                body=body,
                recipient=recipient,
                smtp_user=smtp_user,
                smtp_password=smtp_password,
            )
            sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            report_stem = f"summary_{sent_at[:10]}_{sent_at[11:16].replace(':', '')}"
            report_path = runtime_dir() / f"{report_stem}.md"
            report_path.write_text(body, encoding="utf-8")
            matrix_path = runtime_dir() / f"{report_stem}_gap_matrix.json"
            matrix_path.write_text(
                json.dumps(summary.get("gap_matrix", []), indent=2) + "\n", encoding="utf-8"
            )
            coverage_path = runtime_dir() / f"{report_stem}_capability_matrix.json"
            coverage_path.write_text(
                json.dumps(summary.get("capability_matrix", []), indent=2) + "\n", encoding="utf-8"
            )
            performance_path = runtime_dir() / f"{report_stem}_performance.json"
            performance_path.write_text(
                json.dumps(summary.get("performance", {}), indent=2) + "\n", encoding="utf-8"
            )
            self.save_state(
                {
                    "last_sent_at": sent_at,
                    "last_error": None,
                    "last_recipient": recipient,
                    "smtp_mode": self.config.smtp_mode,
                    "smtp_host": self.config.smtp_host,
                }
            )
            return {
                "sent": True,
                "recipient": recipient,
                "subject": subject,
                "sent_at": sent_at,
                "report_path": str(report_path),
                "gap_matrix_path": str(matrix_path),
                "capability_matrix_path": str(coverage_path),
                "performance_path": str(performance_path),
                "smtp_mode": self.config.smtp_mode,
                "smtp_host": self.config.smtp_host,
            }
        except Exception as exc:  # noqa: BLE001
            self.save_state({**self.load_state(), "last_error": str(exc)})
            return {"sent": False, "error": str(exc), "summary": summary}

    def _send_smtp(
        self,
        *,
        subject: str,
        body: str,
        recipient: str,
        smtp_user: str,
        smtp_password: str,
    ) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.from_address
        msg["To"] = recipient
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=60) as server:
            if self.config.smtp_use_tls:
                context = ssl.create_default_context()
                server.starttls(context=context)
            if self.config.smtp_auth:
                server.login(smtp_user, smtp_password)
            server.sendmail(msg["From"], [recipient], msg.as_string())


def maybe_send_weekly_report() -> dict[str, Any]:
    return EmailNotifier().send_weekly_report(force=False)
