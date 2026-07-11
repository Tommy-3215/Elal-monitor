"""Flight search via Google Flights data (the ``fast_flights`` library).

This module replaces Tom's original ``scraper.py``. His version drove a real
browser against elal.com and had to cope with bot-walls, CAPTCHAs and
hand-calibrated CSS selectors. This version asks Google Flights for the same
availability over a plain HTTPS request -- no browser, no login, no CAPTCHA --
which is what makes it reliable enough to run unattended in the cloud.

Everything downstream (filtering, de-dup, ranking, notifications) is unchanged
from Tom's design and does not depend on where the data came from.
"""
from __future__ import annotations

import logging
from typing import List

from fast_flights import FlightData, Passengers, get_flights

from .config import Settings
from .models import Itinerary, parse_price

log = logging.getLogger("elal.search")


class SearchError(Exception):
    """Raised when a search can't be completed (network / upstream change)."""


def search_one_date(s: Settings, date_str: str) -> List[Itinerary]:
    """Return every economy option Google Flights lists for one date.

    Raises SearchError on failure so the caller can report it rather than
    silently returning nothing.
    """
    try:
        result = get_flights(
            flight_data=[FlightData(
                date=date_str,
                from_airport=s.origin,
                to_airport=s.destination,
            )],
            trip="one-way",
            seat="economy",
            passengers=Passengers(adults=s.passengers),
            fetch_mode=s.fetch_mode,
        )
    except Exception as exc:  # noqa: BLE001 -- upstream lib raises broad errors
        raise SearchError(f"search failed for {date_str}: {exc}") from exc

    raw = getattr(result, "flights", None) or []
    itineraries: List[Itinerary] = []
    for f in raw:
        try:
            itineraries.append(Itinerary(
                search_date=date_str,
                origin=s.origin,
                destination=s.destination,
                airlines=(getattr(f, "name", "") or "").strip(),
                depart_time=(getattr(f, "departure", "") or "").strip(),
                arrive_time=(getattr(f, "arrival", "") or "").strip(),
                duration=(getattr(f, "duration", "") or "").strip(),
                stops=_coerce_stops(getattr(f, "stops", 0)),
                price_display=(getattr(f, "price", "") or "").strip() or "—",
                price_value=parse_price(getattr(f, "price", None)),
                is_best=bool(getattr(f, "is_best", False)),
            ))
        except Exception as exc:  # noqa: BLE001 -- skip a malformed row, keep going
            log.warning("[%s] skipped an unparseable result: %s", date_str, exc)

    log.info("[%s] %d economy options returned.", date_str, len(itineraries))
    return itineraries


def _coerce_stops(value) -> int:
    """fast_flights usually gives an int; be defensive about strings/None."""
    if isinstance(value, int):
        return max(0, value)
    if value is None:
        return 0
    try:
        return max(0, int(str(value).strip().split()[0]))
    except (ValueError, IndexError):
        # "Nonstop" -> 0, anything unrecognised -> 0
        return 0
