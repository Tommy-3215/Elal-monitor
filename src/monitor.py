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
from .search import SearchError, search_one
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
    if s.require_elal and not itin.has_elal:
        return False
    if s.max_price is not None and itin.price_value is not None \
            and itin.price_value > s.max_price:
        return False
    return True


def rank_key(itin: Itinerary, prefer_elal: bool):
    elal_rank = 0 if (prefer_elal and itin.has_elal) else 1
    price = itin.price_value if itin.price_value is not None else _INF
    return (elal_rank, price, itin.stops)


def best_for_group(itineraries: List[Itinerary], s) -> List[Itinerary]:
    """Filter, de-dup, rank, and keep the top N options for one date+route.

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
    """Search every date across every destination, alert via one digest.

    Returns (n_alerted, n_failed_searches).
    """
    # One search per (date, destination). Shuffle so the access pattern looks
    # less robotic and load spreads across routes rather than hammering one.
    jobs = [(d, dest) for dest in s.destinations for d in s.dates]
    random.shuffle(jobs)
    alerts: List[Tuple[str, Itinerary]] = []   # (reason, itin)
    failed: List[tuple] = []                    # (date, dest) pairs that failed

    for i, (d, dest) in enumerate(jobs):
        try:
            found = search_one(s, d, dest)
        except SearchError as exc:
            log.warning("%s", exc)
            failed.append((d, dest))
            continue

        for itin in best_for_group(found, s):
            reason = seen.classify(itin.fingerprint(), itin.price_value,
                                   s.price_drop_threshold)
            if reason:
                alerts.append((reason, itin))

        if i < len(jobs) - 1:
            time.sleep(random.uniform(s.per_search_min_delay, s.per_search_max_delay))

    # If every single search failed, that's a real breakage worth flagging.
    if failed and len(failed) == len(jobs):
        msg = ("Every search failed this run -- the flight data source may have "
               "changed or be temporarily unreachable. Check the GitHub Actions "
               "log.")
        log.error(msg)
        if not dry_run:
            notifier.send("⚠ EL AL watcher: all searches failed", msg)
        return (0, len(failed))

    if not alerts:
        log.info("Nothing new to report (%d search(es) failed).", len(failed))
        return (0, len(failed))

    subject, body = _compose_digest(alerts, s, failed)

    if dry_run:
        print("\n" + "=" * 70)
        print("DRY RUN -- this email WOULD be sent:\n")
        print("Subject:", subject)
        print("-" * 70)
        print(body)
        print("=" * 70)
        return (len(alerts), len(failed))

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
                    failed: List[tuple]) -> Tuple[str, str]:
    new_ones = [it for r, it in alerts if r == "new"]
    cheaper = [it for r, it in alerts if r == "cheaper"]

    cheapest = min(
        (it.price_value for _r, it in alerts if it.price_value is not None),
        default=None,
    )
    gateways = sorted({it.destination for _r, it in alerts})
    bits = []
    if new_ones:
        bits.append(f"{len(new_ones)} new")
    if cheaper:
        bits.append(f"{len(cheaper)} cheaper")
    summary = ", ".join(bits) or "update"
    price_bit = f", from ${cheapest:,.0f}" if cheapest is not None else ""
    subject = (f"✈ Nonstop EL AL {s.origin}→{'/'.join(gateways)}: "
               f"{summary}{price_bit}")

    carrier = "EL AL " if s.require_elal else ""
    lines = [
        f"Nonstop {carrier}seats out of {s.origin} to a US gateway, before "
        f"Tom's current {s.current_departure_date} flight. Meet him there and "
        f"fly on to Austin together.",
        "",
    ]

    def _section(title: str, items: List[Itinerary]) -> None:
        lines.append(f"══ {title} ══")
        # Group by destination gateway, then by date.
        for gw in sorted({it.destination for it in items}):
            gw_items = [it for it in items if it.destination == gw]
            lines.append(f"  ▸ {s.origin} → {gw}")
            for it in sorted(gw_items, key=lambda x: (x.search_date,
                                                      rank_key(x, s.prefer_elal))):
                for ln in it.human_summary().splitlines():
                    lines.append("  " + ln)
                lines.append("")

    if new_ones:
        _section(f"{len(new_ones)} NEWLY AVAILABLE", new_ones)
    if cheaper:
        _section(f"{len(cheaper)} PRICE DROP(s)", cheaper)

    lines += [
        "To book/change: open EL AL and search the date + gateway above, "
        f"economy, {s.passengers} passenger. Confirm EL AL's unaccompanied-minor "
        "rules when booking.",
        "",
        "(Notify-only — nothing was booked. Prices/availability change fast; "
        "confirm on the airline site before acting.)",
    ]
    if failed:
        shown = ", ".join(f"{d}→{dest}" for d, dest in failed[:8])
        more = "" if len(failed) <= 8 else f" (+{len(failed) - 8} more)"
        lines.append("")
        lines.append(f"Note: {len(failed)} search(es) couldn't be completed this "
                     f"run: {shown}{more}. They'll be retried next run.")
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

    log.info("Watching nonstop%s %s→[%s] | %s..%s | pax=%d | earlier than %s",
             " EL AL" if s.require_elal else "", s.origin,
             ",".join(s.destinations), s.date_start, s.date_end,
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
