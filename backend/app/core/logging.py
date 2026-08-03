"""Central logging configuration.

Structured-ish console logging that is readable in local dev and greppable in
production log aggregators. Call :func:`configure_logging` once at startup.
"""

from __future__ import annotations

import logging
import sys

from app.core.config import settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = logging.DEBUG if settings.debug else logging.INFO
    # stderr, not stdout. Some CLI commands emit machine-readable output that gets piped -
    # the fundamentals refresh pipes a symbol list straight into the scraper - and a log line
    # sharing stdout is read as data. It arrived as a symbol named
    # "... | INFO | results_watch.pick: 1 reported + 5 stale backstop".
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet down chatty third parties.
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
