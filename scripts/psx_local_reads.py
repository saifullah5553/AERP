"""Technical reads for the PSX names Yahoo will not serve to GitHub's runners.

Yahoo answers 404 from CI for HUBC, AHCL, AVN, ALTN and BNL and serves them normally here, so this
machine reads them. CI keeps a read for PSX_KEEP_READ_DAYS and then blanks it, which is why this is
a scheduled task ("AERP PSX Local Reads") and not a one-off. It runs after the PSX close, so the
newest bar is a finished session.

Publishes the five company files and those five rows of the screener, nothing else. The rows are
spliced into the tip's screener on each push attempt, so no other row can go back in time. The
commit says [skip ci]: the Daily deploys it, which keeps the site to one deploy a day.

    psx_local_reads.py            read and publish
    psx_local_reads.py --dry-run  read and report, publish nothing
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "backend"), str(REPO / "scripts")]

import tip_files  # noqa: E402

NAMES = ("HUBC", "AHCL", "AVN", "ALTN", "BNL")
DATA = "frontend/public/data"
SCREENER = f"{DATA}/screener.json"
# The technical pass blanks the score and its gate, and the Daily's later passes put them back.
# Those passes need every company's peers, which five rows do not have, so the published values
# stand here. Without this HUBC's composite fell from 72 to 53 and its buy became a hold.
FUNDAMENTAL_FIELDS = ("quality_score", "quality_grade", "fundamental_score", "quality_passed",
                      "quality_improving", "strategy_action", "strategy_conviction", "entry_score")
MESSAGE = "data: PSX technical reads CI cannot fetch (HUBC, AHCL, AVN, ALTN, BNL) [skip ci]\n"


def show(tip: str, path: str) -> bytes:
    return tip_files.git("cat-file", "-p", f"{tip}:{path}", text=False)


def newer_reads(before: dict[str, dict], after: dict[str, dict]) -> dict[str, dict]:
    """Only a read that moved forward. A name Yahoo stopped serving must not publish a blank."""
    return {symbol: row for symbol, row in after.items()
            if row.get("technical_score") is not None
            and str(row.get("technical_as_of") or "")
            > str(before[symbol].get("technical_as_of") or "")}


def keep_fundamentals(before: dict, after: dict) -> dict:
    """The row the technical pass wrote, with the fundamental side as published."""
    return {**after, **{field: before.get(field) for field in FUNDAMENTAL_FIELDS}}


def splice(rows: list[dict], reads: dict[str, dict]) -> list[dict]:
    return [reads.get(row.get("provider_symbol"), row) for row in rows]


def company_file(symbol: str) -> str:
    return f"{DATA}/company/{symbol}.json"


def read(tip: str, work: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """The real technical pass on the tip's files, in a scratch directory. Returns before, after."""
    rows = json.loads(show(tip, SCREENER))
    small = [r for r in rows if r.get("region") == "psx" and r.get("symbol") in NAMES]
    (work / "company").mkdir()
    (work / "screener.json").write_text(json.dumps(small), encoding="utf-8")
    (work / "macro_regime.json").write_bytes(show(tip, f"{DATA}/macro_regime.json"))
    for row in small:
        symbol = row["provider_symbol"]
        (work / "company" / f"{symbol}.json").write_bytes(show(tip, company_file(symbol)))
    # Reconciliation is against the tip's pack, not whatever this checkout last saw.
    (REPO / "data/prices/psx.json.gz").write_bytes(show(tip, "data/prices/psx.json.gz"))

    from app.ingestion.score_unify import unify
    from app.ingestion.tech_refresh import refresh_technicals

    others = tuple({r.get("region") for r in rows} - {"psx"})
    print(refresh_technicals(work, skip_regions=others))
    before = {r["provider_symbol"]: r for r in small}
    screener = work / "screener.json"
    rows = json.loads(screener.read_text(encoding="utf-8"))
    screener.write_text(json.dumps([keep_fundamentals(before[r["provider_symbol"]], r)
                                    for r in rows]), encoding="utf-8")
    for symbol in before:
        page = work / "company" / f"{symbol}.json"
        doc = json.loads(page.read_text(encoding="utf-8"))
        doc["strategy"] = json.loads(show(tip, company_file(symbol))).get("strategy")
        page.write_text(json.dumps(doc), encoding="utf-8")
    unify(work)
    after = json.loads(screener.read_text(encoding="utf-8"))
    return before, {r["provider_symbol"]: r for r in after}


def publish(start: str, reads: dict[str, dict], work: Path) -> int:
    files = [company_file(symbol) for symbol in reads]
    for symbol in reads:
        page = work / "company" / f"{symbol}.json"
        (REPO / company_file(symbol)).write_bytes(page.read_bytes())

    def on_tip(tip: str) -> None:
        moved = tip_files.git("diff", "--name-only", start, tip, "--", *files)
        if moved:   # A rescore landed under us. The next run reads the new page.
            raise RuntimeError(f"changed while reading: {moved.split()}")
        rows = json.loads(show(tip, SCREENER))
        (REPO / SCREENER).write_text(json.dumps(splice(rows, reads)), encoding="utf-8")

    with tempfile.TemporaryDirectory() as scratch:
        message = Path(scratch) / "message.txt"
        message.write_text(MESSAGE, encoding="utf-8")
        return tip_files.push(str(message), [SCREENER, *files], prepare=on_tip)


def main() -> int:
    logging.disable(logging.INFO)
    sys.stdout.reconfigure(encoding="utf-8")
    os.chdir(REPO / "backend")
    tip = tip_files.fetch_tip()
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        before, after = read(tip, work)
        reads = newer_reads(before, after)
        for symbol, row in after.items():
            print(symbol, before[symbol].get("technical_as_of"), "->", row.get("technical_as_of"),
                  row.get("technical_score"), row.get("composite_score"), row.get("signal"),
                  "NEW" if symbol in reads else "kept")
        if not reads:
            print("no newer read")
            return 0
        if "--dry-run" in sys.argv:
            return 0
        return publish(tip, reads, work)


if __name__ == "__main__":
    sys.exit(main())
