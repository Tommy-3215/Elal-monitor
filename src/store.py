"""JSON-backed store of already-seen itineraries and their best price.

Extends Tom's original de-dup store. His stored a flat set of fingerprints so
the same option never alerted twice. This one also remembers the lowest price
we've seen for each fingerprint, so we can additionally alert when a known
option gets meaningfully cheaper -- without spamming on every tiny fluctuation.

In the cloud the file lives at state/seen.json and is committed back to the
repo after each run, so memory survives between scheduled runs.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("elal.store")


class SeenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        # fingerprint -> {"best_price": float|null, "date": str, "summary": str}
        self._seen: Dict[str, dict] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    self._seen = data
            except (json.JSONDecodeError, OSError):
                log.warning("Could not read seen store; starting fresh.")
                self._seen = {}

    def classify(self, fingerprint: str, price: Optional[float],
                 drop_threshold: float) -> Optional[str]:
        """Decide whether this option is worth alerting on.

        Returns "new" for a first-time option, "cheaper" for a known option
        whose price dropped by at least ``drop_threshold``, or None to stay
        quiet.
        """
        rec = self._seen.get(fingerprint)
        if rec is None:
            return "new"
        best = rec.get("best_price")
        if price is not None and best is not None and price <= best - drop_threshold:
            return "cheaper"
        return None

    def record(self, fingerprint: str, price: Optional[float],
               date: str, summary: str) -> None:
        rec = self._seen.get(fingerprint, {})
        prev = rec.get("best_price")
        best = price if prev is None else (
            prev if price is None else min(prev, price))
        self._seen[fingerprint] = {
            "best_price": best,
            "date": date,
            "summary": summary,
        }
        self._dirty = True

    def save(self) -> bool:
        """Persist if anything changed. Returns True if the file was written."""
        if not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._seen, indent=2, sort_keys=True))
            self._dirty = False
            return True
        except OSError as exc:
            log.warning("Could not persist seen store: %s", exc)
            return False
