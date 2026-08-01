"""Detect NEW Buy/Exit signal transitions between the freshly-refreshed signal_moves.json
and the previously committed one, and write an email body listing them.

Usage:  python scripts/diff_new_signals.py <old_signal_moves.json> <out_body.txt>
Prints the count of new transitions to stdout (0 = nothing new).

Used by daily-refresh.yml to email buy/exit timing alerts only when something new landed.
"""

from __future__ import annotations

import json
import sys

NEW = "frontend/public/data/signal_moves.json"


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"all": []}


def _key(m: dict) -> str:
    return f"{m.get('provider_symbol')}|{m.get('direction')}|{m.get('to')}|{m.get('date')}"


def _fmt(m: dict) -> str:
    arrow = "▲ BUY " if m.get("direction") == "buy" else "▼ EXIT"
    score = m.get("composite")
    score_s = f" (score {score})" if score is not None else ""
    return (
        f"{arrow}  {m.get('symbol')} — {m.get('name') or ''}  "
        f"[{m.get('from')} → {m.get('to')}]{score_s}  {m.get('region')}  {m.get('date')}"
    ).rstrip()


def main() -> int:
    old_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/old_signal_moves.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/signal_body.txt"

    new, old = _load(NEW), _load(old_path)
    old_keys = {_key(m) for m in old.get("all", [])}
    fresh = [m for m in new.get("all", []) if _key(m) not in old_keys]

    buys = [m for m in fresh if m.get("direction") == "buy"]
    exits = [m for m in fresh if m.get("direction") == "sell"]

    parts: list[str] = []
    if buys:
        parts.append("New BUY signals (entered Strong Buy):\n\n" + "\n".join(_fmt(m) for m in buys))
    if exits:
        parts.append("New EXIT signals (left Strong Buy):\n\n" + "\n".join(_fmt(m) for m in exits))
    body = "\n\n".join(parts)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(len(fresh))
    return 0


if __name__ == "__main__":
    sys.exit(main())
