"""EL AL earlier-seat monitor -- cloud edition.

Usage:
    python -m src.monitor                # run one cycle and exit (what CI uses)
    python -m src.monitor --dry-run      # run one cycle, print the digest, send nothing
    python -m src.monitor --loop         # run forever locally (checks every interval)
    python -m src.monitor --notify-test  # send a test message and exit

What it does (Tom's rules, unchanged):
  * Searches TLV->AUS economy for every date in your window.
  * Keeps only bookable economy options that are earlier than your current
    departure date, within your max-stops and max-price limits.
  * Alerts on options that are NEW, or that got meaningfully CHEAPER since last
    time. Never alerts twice for the same thing.
  * EL AL / EL AL-codeshare options are ranked first.
  * Never books anything. Notify-only.

The difference from Tom's version is only the data source (Google Flights over a
plain request instead of scraping elal.com) and that it sends one tidy digest
per run instead of one email per flight -- friendlier when watching 14 dates.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import date
from typing import List, Optional, Tuple

from .config import SEEN_STORE_PATH, load_settings
from .logging_setup import setup_logging
from .models import Itinerary
from .notifier import Notifier
from .search import SearchError, search_one_date
from .store import SeenStore

log = setup_logging()

_INF = float("inf")


# --------------------------------------------------------------------------
# Filtering & ranking
# --------------------------------------------------------------------------
def is_earlier_than_current(itin: Itinerary, current_departure: str) -> bool:
    try:
        return date.fromisoformat(itin.depart_date) < date.fromisoformat(current_departure)
    except ValueError:
        return True  # if unparseable, don't silently drop it


def passes_filters(itin: Itinerary, s) -> bool:
    if not is_earlier_than_current(itin, s.current_departure_date):
        return False
    if itin.stops > s.max_stops:
        return False
    if s.max_price is not None and itin.price_value is not None \
            and itin.price_value > s.max_price:
        return False
    return True


def rank_key(itin: Itinerary, prefer_elal: bool):
    elal_rank = 0 if (prefer_elal and itin.has_elal) else 1
    price = itin.price_value if itin.price_value is not None else _INF
    return (elal_rank, price, itin.stops)


def best_per_date(itineraries: List[Itinerary], s) -> List[Itinerary]:
    """Filter, de-dup, rank, and keep only the top N options for a single date.

    Google Flights returns the same itinerary twice (once in its "best" section,
    once in the full list), so we collapse by fingerprint first, keeping the
    cheapest copy.
    """
    by_fp: dict = {}
    for it in itineraries:
        if not passes_filters(it, s):
            continue
        fp = it.fingerprint()
        cur = by_fp.get(fp)
        if cur is None or rank_key(it, s.prefer_elal) < rank_key(cur, s.prefer_elal):
            by_fp[fp] = it
    kept = sorted(by_fp.values(), key=lambda it: rank_key(it, s.prefer_elal))
    return kept[: max(1, s.top_per_date)]


# --------------------------------------------------------------------------
# One cycle
# --------------------------------------------------------------------------
def run_cycle(s, notifier: Notifier, seen: SeenStore,
              dry_run: bool = False) -> Tuple[int, int]:
    """Search every date, alert on new/cheaper options via one digest.

    Returns (n_alerted, n_failed_dates).
    """
    dates = list(s.dates)
    alerts: List[Tuple[str, Itinerary]] = []   # (reason, itin)
    failed_dates: List[str] = []

    for i, d in enumerate(dates):
        try:
            found = search_one_date(s, d)
        except SearchError as exc:
            log.warning("%s", exc)
            failed_dates.append(d)
            continue

        for itin in best_per_date(found, s):
            reason = seen.classify(itin.fingerprint(), itin.price_value,
                                   s.price_drop_threshold)
            if reason:
                alerts.append((reason, itin))

        if i < len(dates) - 1:
            time.sleep(random.uniform(s.per_search_min_delay, s.per_search_max_delay))

    # If every single date failed, that's a real breakage worth flagging.
    if failed_dates and len(failed_dates) == len(dates):
        msg = ("Every date search failed this run -- the flight data source may "
               "have changed or be temporarily unreachable. Check the GitHub "
               "Actions log.")
        log.error(msg)
        if not dry_run:
            notifier.send("⚠ EL AL watcher: all searches failed", msg)
        return (0, len(failed_dates))

    if not alerts:
        log.info("Nothing new to report (%d date(s) failed).", len(failed_dates))
        return (0, len(failed_dates))

    subject, body = _compose_digest(alerts, s, failed_dates)

    if dry_run:
        print("\n" + "=" * 70)
        print("DRY RUN -- this email WOULD be sent:\n")
        print("Subject:", subject)
        print("-" * 70)
        print(body)
        print("=" * 70)
        return (len(alerts), len(failed_dates))

    if notifier.send(subject, body):
        for _reason, itin in alerts:
            seen.record(itin.fingerprint(), itin.price_value,
                        itin.depart_date, itin.one_line())
        seen.save()
        log.info("Alerted on %d option(s); state saved.", len(alerts))
    else:
        log.error("Digest send failed; will retry next run (state not updated).")

    return (len(alerts), len(failed_dates))


def _compose_digest(alerts: List[Tuple[str, Itinerary]], s,
                    failed_dates: List[str]) -> Tuple[str, str]:
    new_ones = [it for r, it in alerts if r == "new"]
    cheaper = [it for r, it in alerts if r == "cheaper"]

    cheapest = min(
        (it.price_value for _r, it in alerts if it.price_value is not None),
        default=None,
    )
    bits = []
    if new_ones:
        bits.append(f"{len(new_ones)} new")
    if cheaper:
        bits.append(f"{len(cheaper)} cheaper")
    summary = ", ".join(bits) or "update"
    price_bit = f", from ${cheapest:,.0f}" if cheapest is not None else ""
    subject = (f"✈ Earlier {s.origin}→{s.destination} economy: "
               f"{summary}{price_bit}")

    lines = [
        f"Earlier economy options for {s.origin} → {s.destination}, before your "
        f"{s.current_departure_date} flight.",
        "",
    ]
    if new_ones:
        lines.append(f"── {len(new_ones)} NEW option(s) ──")
        for it in sorted(new_ones, key=lambda x: (x.search_date, rank_key(x, s.prefer_elal))):
            lines.append(it.human_summary())
            lines.append("")
    if cheaper:
        lines.append(f"── {len(cheaper)} PRICE DROP(s) ──")
        for it in sorted(cheaper, key=lambda x: (x.search_date, rank_key(x, s.prefer_elal))):
            lines.append(it.human_summary())
            lines.append("")

    lines += [
        "To book or change, open EL AL (or Google Flights) and search "
        f"{s.origin} → {s.destination} on the date above, economy, "
        f"{s.passengers} passenger(s).",
        "",
        "(Notify-only — nothing was booked. Prices/availability change fast; "
        "confirm on the airline site before acting.)",
    ]
    if failed_dates:
        lines.append("")
        lines.append(f"Note: {len(failed_dates)} date(s) couldn't be checked this "
                     f"run: {', '.join(failed_dates)}.")
    return subject, "\n".join(lines)


# --------------------------------------------------------------------------
# Entry
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="EL AL earlier-economy-seat monitor (Google Flights, notify-only).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run a cycle and print the digest instead of emailing.")
    parser.add_argument("--loop", action="store_true",
                        help="Keep running locally, checking every CHECK_INTERVAL.")
    parser.add_argument("--notify-test", action="store_true",
                        help="Send a test notification and exit.")
    args = parser.parse_args()

    s = load_settings()
    notifier = Notifier(s)
    seen = SeenStore(SEEN_STORE_PATH)

    if args.notify_test:
        err = s.validate_notify()
        if err:
            log.error("Notification config error: %s", err)
            return 2
        ok = notifier.send("✅ EL AL watcher test",
                           "If you can read this, notifications work.")
        return 0 if ok else 1

    if not args.dry_run:
        err = s.validate_notify()
        if err:
            log.error("Notification config error: %s", err)
            return 2

    log.info("Watching %s→%s | %s..%s | economy | pax=%d | earlier than %s",
             s.origin, s.destination, s.date_start, s.date_end,
             s.passengers, s.current_departure_date)

    if not args.loop:
        run_cycle(s, notifier, seen, dry_run=args.dry_run)
        return 0

    # Local continuous mode (the cloud uses a scheduler instead of this loop).
    interval = 3600
    while True:
        try:
            run_cycle(s, notifier, seen, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001 -- keep the loop alive
            log.exception("Cycle error: %s", exc)
        log.info("Sleeping %ds until next check.", interval)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
