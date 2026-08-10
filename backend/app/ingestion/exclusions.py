"""Symbols the platform should not carry, and the evidence for dropping each one.

A company with no financial statements cannot be scored, ranked, or reasoned about. It occupies
a row, dilutes every market count, and appears in screens as a permanent blank. Most are SPACs,
shells, warrants and rights - securities that genuinely file nothing.

The list is EVIDENCE, not judgement. A symbol earns its place here only by returning a 404 on
every statement page it was asked for, with nothing saved: "we could not fetch it" is not the
same fact as "it does not exist", and the difference is a company we would silently lose. A
timeout, a rate-limit or a half-rendered table leaves a symbol in the universe to be retried.

Stored per region as a plain text file so it can be read, edited and argued with by hand:

    data/exclusions/us.txt
"""

from __future__ import annotations

from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

EXCLUSIONS_DIR = Path(__file__).resolve().parents[3] / "data" / "exclusions"


def _path(region: str) -> Path:
    return EXCLUSIONS_DIR / f"{region}.txt"


def load_excluded(region: str) -> set[str]:
    """Symbols to drop for this market. Blank lines and # comments are ignored."""
    path = _path(region)
    if not path.exists():
        return set()
    out: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            sym = line.split("#", 1)[0].strip().upper()
            if sym:
                out.add(sym)
    except OSError:
        return set()
    return out


def load_all() -> dict[str, set[str]]:
    """{region: {symbols}} across every exclusion file present."""
    if not EXCLUSIONS_DIR.exists():
        return {}
    return {p.stem: load_excluded(p.stem) for p in EXCLUSIONS_DIR.glob("*.txt")}


def save_excluded(region: str, symbols: set[str], note: str = "") -> int:
    """Write the list, merged with whatever is already there. Returns the new total."""
    existing = load_excluded(region)
    merged = sorted(existing | {s.strip().upper() for s in symbols if s.strip()})
    EXCLUSIONS_DIR.mkdir(parents=True, exist_ok=True)
    header = [
        f"# {region.upper()} - no financial statements at the source.",
        "# Every symbol here returned a 404 on every statement page, with nothing saved.",
        "# Transient failures (timeouts, half-rendered tables) are NOT listed: those stay in",
        "# the universe and are retried.",
    ]
    if note:
        header.append(f"# {note}")
    _path(region).write_text("\n".join(header + merged) + "\n", encoding="utf-8")
    log.info("exclusions[%s]: %d symbols (%d new)", region, len(merged),
             len(merged) - len(existing))
    return len(merged)


# The asset classes this platform carries. Everything here is either something we can score on
# its own fundamentals (equity) or something we track as a market input (currencies, crypto,
# commodities). ETFs are deliberately absent: a fund files no statements of its own, so it can
# never be scored, ranked or reasoned about here - it is a wrapper around holdings we would
# rather look at directly.
#
# `index` is kept and is NOT browsable filler: the regime engine reads ^GSPC, ^NSEI, ^AXJO and
# ^TASI.SR straight off these rows for each market's Index Trend, and the screener's indices
# bar renders them. Dropping them would blank a signal on every market's regime card.
KEEP_ASSET_CLASSES = frozenset({"equity", "forex", "crypto", "commodity", "index"})


def apply_to_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Drop excluded rows from a screener list. Returns (kept, dropped).

    Two rules, one pass. The per-symbol lists are EVIDENCE - a symbol earns its place by
    returning nothing on every statement page it was asked for. The asset-class rule is a
    DECISION about what the platform is for, and it is expressed as a class rather than as a
    list of tickers on purpose: a list of fourteen ETFs would not catch the fifteenth the next
    universe refresh adds.
    """
    lists = load_all()
    kept = []
    dropped = 0
    for r in rows:
        if (r.get("asset_class") or "equity") not in KEEP_ASSET_CLASSES:
            dropped += 1
            continue
        banned = lists.get(str(r.get("region") or ""), set())
        if banned and str(r.get("symbol") or "").upper() in banned:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped
