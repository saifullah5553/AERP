"""Detect NEW PSX announcements between the freshly-exported catalysts.json and the
previously committed one, and write an email body listing them.

Usage:  python scripts/diff_new_alerts.py <old_catalysts.json> <out_body.txt>
Prints the count of new announcements to stdout (0 = nothing new).

Used by refresh-data.yml to email alerts only when something new actually landed.
"""

from __future__ import annotations

import json
import sys

NEW = "frontend/public/data/catalysts.json"


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"by_symbol": {}}


def _ids(cat: dict) -> set[str]:
    out: set[str] = set()
    for sym, evs in (cat.get("by_symbol") or {}).items():
        for e in evs:
            out.add(f"{sym}|{e.get('title')}|{e.get('date')}")
    return out


def main() -> int:
    old_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/old_catalysts.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/alert_body.txt"

    new, old = _load(NEW), _load(old_path)
    fresh = _ids(new) - _ids(old)

    lines: list[str] = []
    for sym, evs in (new.get("by_symbol") or {}).items():
        for e in evs:
            if f"{sym}|{e.get('title')}|{e.get('date')}" in fresh:
                pdf = e.get("pdf_url") or ""
                lines.append(f"• {sym} — {e.get('title')} ({e.get('date')})\n  {pdf}".rstrip())

    body = (
        "New PSX announcements:\n\n" + "\n\n".join(lines) if lines else ""
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(len(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
