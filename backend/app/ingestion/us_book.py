"""The US model portfolio from 6 November 2026: analysts' growth and our score, 15 names.

THE RULE, set by the user. Two months after each quarter ends:

    Zacks EPS growth of 15% or more on all three of F0, F1 and F2
    our fundamental score 70 or above
    listed on the NYSE or NASDAQ, wherever the company is based, at any size
    at least three analysts
    the 15 highest scores, no sector above 25%

A foreign filer's score is only as good as its reporting basis, so one without an entry in
us_reporting_basis.json waits until it has one. That is a check on the data, not a rule about
domicile: it leaves the list the moment its score can be trusted.

Estimates cannot be reconstructed: Zacks serves today's consensus and nothing here holds an old one.
So this is a forward record, written down on the day and never rebuilt, and the quarters before it
stay as they were under the rule that produced them. data/symbols/us_book.json is that record. It
holds tickers and our own scores, and no Zacks figure: the screen is read locally and only its
result is kept, because this repository is public.

A rebalance is added by `us-book-rebalance`, from a CSV of ticker,f0,f1,f2,analysts in percent.
F2 growth has no line of its own in the Zacks screener, so it is F2 / F1 consensus, and a name with
a non-positive F0 or F1 is left out of the CSV, because a percentage on a loss means nothing.

Measured only by proxy so far, and not proven. Do not describe it as an edge.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Container
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

BOOK_JSON = Path(__file__).resolve().parents[3] / "data" / "symbols" / "us_book.json"
SIZE = 15
MIN_GROWTH = 15.0
MIN_SCORE = 70.0
MIN_ANALYSTS = 3
EXCHANGES = ("NYSE", "NASDAQ")
HOME = "United States"


def load_book(path: Path = BOOK_JSON) -> list[dict]:
    """The dated rebalances, oldest first. [] leaves the ledger as it was."""
    try:
        return sorted(json.loads(path.read_text(encoding="utf-8"))["rebalances"],
                      key=lambda step: step["trade_on"])
    except (OSError, json.JSONDecodeError, KeyError):
        return []


def _key(symbol: object) -> str:
    return str(symbol).upper().replace("/", "-").replace(".", "-")


def read_screen(path: Path) -> dict[str, dict[str, float]]:
    """The Zacks screen, by ticker. Unreadable rows are dropped rather than passed."""
    out: dict[str, dict[str, float]] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                out[_key(row["ticker"])] = {name: float(row[name])
                                            for name in ("f0", "f1", "f2", "analysts")}
            except (KeyError, TypeError, ValueError):
                continue
    return out


def qualifies(row: dict, screen: dict[str, dict[str, float]], domicile: dict[str, str],
              basis: Container[str] = ()) -> bool:
    symbol = row.get("symbol")
    estimate = screen.get(_key(symbol))
    score = row.get("quality_score")
    verified = domicile.get(_key(symbol)) == HOME or symbol in basis
    return (row.get("region") == "us" and row.get("market_code") in EXCHANGES
            and estimate is not None
            and all(estimate[name] >= MIN_GROWTH for name in ("f0", "f1", "f2"))
            and estimate["analysts"] >= MIN_ANALYSTS
            and isinstance(score, int | float) and score >= MIN_SCORE and verified
            # No chart means it has stopped trading, and a position needs a price to fill at.
            and bool(row.get("technical_as_of")))


def select(rows: list[dict], screen: dict[str, dict[str, float]], domicile: dict[str, str],
           basis: Container[str] = ()) -> tuple[dict[str, float], int]:
    """The picks with their scores, best first, and how many names qualified."""
    from app.ingestion.rebalance_ledger import capped_picks

    pool = sorted((r for r in rows if qualifies(r, screen, domicile, basis)),
                  key=lambda r: -r["quality_score"])
    ranked = [(r["symbol"], r["quality_score"]) for r in pool]
    names = {r["symbol"]: r for r in pool}
    picks = capped_picks(ranked, names, SIZE)
    return {symbol: score for symbol, score in ranked if symbol in picks}, len(pool)


def add_rebalance(picks: dict[str, float], pool: int, trade_on: str, results_for: str, label: str,
                  path: Path = BOOK_JSON) -> None:
    """Write one rebalance. Refuses a date already recorded: the record is not rebuilt."""
    if len(picks) < SIZE:
        raise ValueError(f"only {len(picks)} names qualified, the rule holds {SIZE}")
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rebalances": []}
    if any(step["trade_on"] == trade_on for step in doc["rebalances"]):
        raise ValueError(f"{trade_on} is already recorded")
    doc["rebalances"].append({"trade_on": trade_on, "results_for": results_for, "label": label,
                              "pool": pool, "picks": picks})
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
