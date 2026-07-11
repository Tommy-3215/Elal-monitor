"""Notification dispatch.

Supported channels (chosen via NOTIFY_CHANNEL):
  - email       : SMTP email (zero-cost, reliable) — supports multiple recipients
  - email_sms   : free carrier email-to-SMS gateway (works but carrier-dependent)
  - discord     : Discord webhook
  - telegram    : Telegram bot

Credentials are read from Settings (which reads env). Nothing sensitive is logged.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from .config import Settings

log = logging.getLogger("elal.notifier")


class Notifier:
    def __init__(self, settings: "Settings") -> None:
        self.s = settings

    # ---- public API -------------------------------------------------------
    def send(self, subject: str, body: str) -> bool:
        """Send a message via the configured channel. Returns success bool."""
        channel = self.s.notify_channel
        try:
            if channel == "email":
                return self._send_email(self.s.email_to_list, subject, body)
            if channel == "email_sms":
                # SMS gateways ignore subject; keep the body short.
                return self._send_email([self.s.sms_gateway_address], subject, body)
            if channel == "discord":
                return self._send_discord(f"**{subject}**\n{body}")
            if channel == "telegram":
                return self._send_telegram(f"{subject}\n{body}")
            log.error("Unknown notify channel: %s", channel)
            return False
        except Exception as exc:  # never let a notify failure crash the loop
            log.exception("Notification via %s failed: %s", channel, exc)
            return False

    # ---- channel implementations -----------------------------------------
    def _send_email(self, recipients, subject: str, body: str) -> bool:
        # Accept a single address or a list; normalize to a clean list.
        if isinstance(recipients, str):
            recipients = [recipients]
        recipients = [r.strip() for r in recipients if r and r.strip()]
        if not recipients:
            log.error("No email recipients configured.")
            return False

        msg = EmailMessage()
        msg["From"] = self.s.email_from or self.s.smtp_user
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(self.s.smtp_user, self.s.smtp_password)
            # Explicit recipient list ensures every address gets delivered.
            server.send_message(msg, to_addrs=recipients)
        log.info("Email sent to %d recipient(s): %s", len(recipients), ", ".join(recipients))
        return True

    def _send_discord(self, content: str) -> bool:
        resp = requests.post(
            self.s.discord_webhook_url,
            json={"content": content[:1900]},
            timeout=20,
        )
        resp.raise_for_status()
        log.info("Discord notification sent")
        return True

    def _send_telegram(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.s.telegram_bot_token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": self.s.telegram_chat_id, "text": text[:4000]},
            timeout=20,
        )
        resp.raise_for_status()
        log.info("Telegram notification sent")
        return True
