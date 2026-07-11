"""Data model for a parsed flight option.

Adapted from Tom's original models.py. His version modelled per-segment flight
numbers scraped from EL AL's site; Google Flights gives us airline names, times,
stops and price instead, so the fields match that -- but the ideas that made his
version nice (a stable fingerprint for de-duplication, an ``has_elal`` flag, a
human-readable summary) are kept.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional


def parse_price(raw: Optional[str]) -> Optional[float]:
    """'$1,738' -> 1738.0 ; None/'Price unavailable' -> None."""
    if not raw:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", raw.replace(",", ""))
    return float(m.group()) if m else None


@dataclass
class Itinerary:
    search_date: str            # the date we searched, YYYY-MM-DD
    origin: str
    destination: str
    airlines: str               # e.g. "EL AL" or "EL AL, American"
    depart_time: str            # human string, e.g. "8:10 PM on Tue, Jul 28"
    arrive_time: str
    duration: str               # e.g. "18 hr 25 min"
    stops: int
    price_display: str          # e.g. "$1,738" (as shown)
    price_value: Optional[float]  # numeric for comparisons, or None
    is_best: bool = False       # Google flagged it among the "best" options

    @property
    def depart_date(self) -> str:
        return self.search_date

    @property
    def has_elal(self) -> bool:
        return "el al" in (self.airlines or "").lower()

    @property
    def stops_label(self) -> str:
        if self.stops == 0:
            return "nonstop"
        return f"{self.stops} stop" + ("s" if self.stops > 1 else "")

    def fingerprint(self) -> str:
        """Stable id for de-dup. Deliberately excludes price, so a price change
        does not look like a brand-new flight -- price drops are handled
        separately by the store."""
        key = "|".join([
            self.search_date, self.origin, self.destination,
            self.airlines.lower(), self.depart_time, str(self.stops),
        ])
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def human_summary(self) -> str:
        star = " ⭐" if self.is_best else ""
        return (
            f"{self.depart_date} · {self.price_display}{star}\n"
            f"  {self.airlines} · {self.stops_label} · {self.duration}\n"
            f"  depart {self.depart_time} → arrive {self.arrive_time}"
        )

    def one_line(self) -> str:
        tag = "EL AL" if self.has_elal else self.airlines
        return (f"{self.depart_date}  {self.price_display:>8}  "
                f"{self.stops_label:<8}  {tag} ({self.duration})")
