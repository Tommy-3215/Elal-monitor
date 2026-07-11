"""Configuration, loaded from environment variables (.env supported locally).

No credentials are hard-coded. Everything sensitive comes from the environment
(a local .env file when developing, GitHub Actions secrets when running in the
cloud).

This is adapted from Tom's original config.py. The search parameters and alert
rules are his; the browser/selector settings are gone because the cloud version
reads Google Flights data directly instead of driving a browser.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(_PROJECT_ROOT / ".env")
except Exception:
    # python-dotenv is optional; in CI the env is provided by the workflow.
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent

STATE_DIR = _PROJECT_ROOT / "state"
SEEN_STORE_PATH = STATE_DIR / "seen.json"


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_float_or_none(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _date_range(start: str, end: str) -> List[str]:
    """Inclusive list of YYYY-MM-DD strings between start and end."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    if e < s:
        s, e = e, s
    out, cur = [], s
    while cur <= e:
        out.append(cur.isoformat())
        cur = cur.fromordinal(cur.toordinal() + 1)
    return out


@dataclass
class Settings:
    # --- Search parameters ---
    origin: str = ""
    # US gateways Tom could be met at, flown nonstop by EL AL. A parent meets
    # him there and they fly on to Austin separately.
    destinations: List[str] = field(default_factory=list)
    date_start: str = ""
    date_end: str = ""
    passengers: int = 1

    # Baseline you are trying to beat. Any bookable economy itinerary that
    # departs before this date is "earlier" and worth alerting on. Because we
    # only search dates in [date_start, date_end], everything found is already
    # earlier -- this is kept for the alert wording and as a safety check.
    current_departure_date: str = ""

    # Prefer EL AL / EL AL codeshare itineraries (ranked first in alerts).
    prefer_elal: bool = True

    # --- Alert tuning (keep the noise down) ---
    # A minor can't fly a connection unaccompanied, so this must stay 0 unless
    # the plan changes: 0 = nonstop only.
    max_stops: int = 0
    # Only alert on flights actually operated by EL AL (Tom's carrier). Other
    # airlines also fly some of these routes nonstop -- flip this off to include
    # them if you'd consider rebooking off EL AL.
    require_elal: bool = True
    # Ignore anything above this price, if set (leave blank for no ceiling).
    max_price: Optional[float] = None
    # Only keep the best this-many options per date (ranked EL AL first, then
    # cheapest). Prevents a flood on the first run.
    top_per_date: int = 3
    # Re-alert on a price drop only if it falls by at least this many dollars.
    price_drop_threshold: float = 25.0

    # --- Politeness (between per-date searches) ---
    per_search_min_delay: float = 1.5
    per_search_max_delay: float = 4.0
    # fast_flights fetch mode: "common" (browserless HTTP, best for cloud)
    # or "fallback" (adds a headless browser locally if the HTTP path fails).
    fetch_mode: str = "common"

    # --- Notifications --- (unchanged from Tom's design)
    notify_channel: str = "email"  # email | email_sms | discord | telegram

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""
    sms_gateway_address: str = ""
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    log_level: str = "INFO"

    dates: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Read env at construction time (not at class-definition time) so that
        # changing a value and re-running actually takes effect -- this is the
        # bug we fixed from the original.
        self.origin = os.getenv("ORIGIN", "TLV").upper()
        raw_dests = os.getenv("DESTINATIONS") or os.getenv("DESTINATION") \
            or "JFK,EWR,BOS,MIA,LAX"
        self.destinations = [d.strip().upper() for d in raw_dests.split(",") if d.strip()]
        self.date_start = os.getenv("DATE_START", "2026-07-21")
        self.date_end = os.getenv("DATE_END", "2026-08-03")
        self.passengers = _get_int("PASSENGERS", 1)
        self.current_departure_date = os.getenv("CURRENT_DEPARTURE_DATE", "2026-08-04")
        self.prefer_elal = _get_bool("PREFER_ELAL", True)

        self.max_stops = _get_int("MAX_STOPS", 0)
        self.require_elal = _get_bool("REQUIRE_ELAL", True)
        self.max_price = _get_float_or_none("MAX_PRICE")
        self.top_per_date = _get_int("TOP_PER_DATE", 3)
        self.price_drop_threshold = float(_get_int("PRICE_DROP_THRESHOLD", 25))

        self.fetch_mode = os.getenv("FETCH_MODE", "common").lower()

        self.notify_channel = os.getenv("NOTIFY_CHANNEL", "email").lower()
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = _get_int("SMTP_PORT", 587)
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.email_from = os.getenv("EMAIL_FROM", "")
        self.email_to = os.getenv("EMAIL_TO", "")
        self.sms_gateway_address = os.getenv("SMS_GATEWAY_ADDRESS", "")
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

        self.dates = _date_range(self.date_start, self.date_end)

    @property
    def email_to_list(self) -> List[str]:
        return [addr.strip() for addr in self.email_to.split(",") if addr.strip()]

    def validate_notify(self) -> Optional[str]:
        """Return an error string if the chosen channel is misconfigured."""
        c = self.notify_channel
        if c == "email":
            if not (self.smtp_host and self.smtp_user and self.smtp_password
                    and self.email_to_list):
                return "email channel needs SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_TO"
        elif c == "email_sms":
            if not (self.smtp_host and self.smtp_user and self.smtp_password
                    and self.sms_gateway_address):
                return "email_sms needs SMTP_* creds and SMS_GATEWAY_ADDRESS"
        elif c == "discord":
            if not self.discord_webhook_url:
                return "discord needs DISCORD_WEBHOOK_URL"
        elif c == "telegram":
            if not (self.telegram_bot_token and self.telegram_chat_id):
                return "telegram needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        else:
            return f"unknown NOTIFY_CHANNEL '{c}'"
        return None


def load_settings() -> Settings:
    return Settings()
