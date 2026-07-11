"""Central logging configuration.

Logs go to both the console and a rotating file in logs/. Secrets are never
logged (the notifier and config modules are careful never to pass credentials
into log calls).
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "monitor.log"

_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logging once and return the app logger."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers if called more than once.
    if root.handlers:
        return logging.getLogger("elal")

    formatter = logging.Formatter(_FMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Quiet down noisy third-party loggers.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("primp").setLevel(logging.WARNING)

    return logging.getLogger("elal")
