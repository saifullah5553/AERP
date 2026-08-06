"""One spelling per sector, and an asset class on every row.

Two faults, and neither was only cosmetic.

SECTORS CAME IN TWO CASES. 19 PSX sectors existed as both "Cement" and "CEMENT" - 71 distinct
strings where there are 52 sectors. The filter listed each twice, which is how it was noticed,
but the damage was in the scoring: peer margins are bucketed on the raw string, so "CEMENT"
formed a second group of one company that never reached MIN_PEER_GROUP. Those companies were
graded against the absolute anchors instead of against their own industry, silently.

ASSET CLASS WAS MOSTLY NULL. 503 of 6,034 US rows carried "equity" - the original S&P 500
universe, never backfilled as it grew to six thousand. The frontend filters on strict equality
(`r.asset_class === q.asset_class`), so selecting Equity returned those 503 and hid the rest.
9,961 of 11,109 rows across all markets had no class at all.

Both are fixed by deriving rather than storing: a row's class follows from what it is, so a
universe that grows cannot leave it behind.
"""

from __future__ import annotations

from collections import Counter

from app.core.logging import get_logger

log = get_logger(__name__)

# A non-equity carries its asset class AS its sector - the convention the sector store already
# follows, so forex pairs and indices are not left looking like companies with a missing field.
NON_EQUITY_SECTORS = {
    "forex": "forex",
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "index": "index",
    "indices": "index",
    "commodity": "commodity",
    "commodities": "commodity",
    "etf": "etf",
}
DEFAULT_ASSET_CLASS = "equity"


def canonical_map(values: list[str]) -> dict[str, str]:
    """Pick one spelling per sector, keyed by the case-folded name.

    Data-driven rather than a fixed rule: the majority spelling wins, so the canonical form is
    whatever the sources already agree on and no name is invented. Title-casing everything
    would have been simpler and would have renamed sectors nobody asked to rename.

    Ties break towards the variant that is not shouting, then alphabetically, so the result is
    the same on every run regardless of row order.
    """
    counts: dict[str, Counter] = {}
    for raw in values:
        name = (raw or "").strip()
        if name:
            counts.setdefault(name.casefold(), Counter())[name] += 1

    out: dict[str, str] = {}
    for key, variants in counts.items():
        best = max(variants.items(), key=lambda kv: (kv[1], not kv[0].isupper(), kv[0]))
        out[key] = best[0]
    return out


def asset_class_for(sector: str | None, existing: str | None = None) -> str:
    """What kind of instrument this row is. Never None - that is the whole point.

    An existing value is kept when it is one we recognise, so a row already classified by the
    universe loader is not reclassified by a sector that happens to look like something else.
    """
    if existing:
        known = str(existing).strip().lower()
        if known in set(NON_EQUITY_SECTORS.values()) | {DEFAULT_ASSET_CLASS}:
            return known
    return NON_EQUITY_SECTORS.get((sector or "").strip().casefold(), DEFAULT_ASSET_CLASS)


def normalize_snapshot(data_dir) -> dict[str, int]:
    """Normalise the screener AND the per-company files from ONE canonical map.

    They are two views of the same securities and were disagreeing in both directions: the
    company files carried an asset class for all 11,135 names while the screener had one for
    1,050, and both carried the same 19 sectors under two spellings. Deriving the map from the
    screener - the superset - and applying it to both is what keeps a company page and its row
    in the grid saying the same thing.
    """
    import json
    from pathlib import Path

    out = Path(data_dir)
    rows = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    mapping = canonical_map([r.get("sector") for r in rows if r.get("sector")])
    stats = normalize_rows(rows, mapping)
    (out / "screener.json").write_text(json.dumps(rows, separators=(",", ":")),
                                       encoding="utf-8")

    touched = 0
    for path in (out / "company").glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        before = (doc.get("sector"), doc.get("asset_class"))
        sector = (doc.get("sector") or "").strip()
        if sector:
            doc["sector"] = mapping.get(sector.casefold(), sector)
        doc["asset_class"] = asset_class_for(doc.get("sector"), doc.get("asset_class"))
        if (doc.get("sector"), doc.get("asset_class")) != before:
            try:
                path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
                touched += 1
            except OSError:
                continue
    stats["company_files"] = touched
    log.info("taxonomy: %d company files rewritten", touched)

    # sector_stats is joined to a company by an exact sector string on the Company vs Sector
    # card, and it is built from the DATABASE while the pages are built from the snapshot. PSX
    # arrived from there in capitals - "CEMENT" against the screener's "Cement" - so the card
    # silently returned nothing for 450 of 453 PSX companies. Nothing errored; the panel simply
    # was not there.
    stats["sector_stats"] = _normalize_sector_stats(out, mapping)
    return stats


def _normalize_sector_stats(out, mapping: dict[str, str]) -> int:
    import json

    path = out / "sector_stats.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    changed = 0
    for entries in doc.values():
        for entry in entries or []:
            name = (entry.get("sector") or "").strip()
            if not name:
                continue
            canon = mapping.get(name.casefold())
            # Only rewrite to a spelling the screener actually uses. A sector the snapshot has
            # never heard of - the US stats speak GICS, "Financials" where the screener says
            # "Financial Services" - is a different taxonomy, not a different capitalisation,
            # and renaming it here would invent a match that does not exist.
            if canon and canon != entry["sector"]:
                entry["sector"] = canon
                changed += 1
    if changed:
        path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    log.info("taxonomy: %d sector_stats labels realigned with the screener", changed)
    return changed


def normalize_rows(rows: list[dict], mapping: dict[str, str] | None = None) -> dict[str, int]:
    """Collapse sector spellings and give every row an asset class. Mutates in place."""
    if mapping is None:
        mapping = canonical_map([r.get("sector") for r in rows if r.get("sector")])

    renamed = classified = 0
    for row in rows:
        sector = (row.get("sector") or "").strip()
        if sector:
            canon = mapping.get(sector.casefold(), sector)
            if canon != row.get("sector"):
                row["sector"] = canon
                renamed += 1
        elif row.get("sector") is not None:
            # An empty string is not a sector; it groups every unlabelled row together and
            # then reads as a real bucket on the filter.
            row["sector"] = None

        was = row.get("asset_class")
        row["asset_class"] = asset_class_for(row.get("sector"), was)
        if row["asset_class"] != was:
            classified += 1

    distinct = len({r["sector"] for r in rows if r.get("sector")})
    log.info("taxonomy: %d sector labels rewritten, %d asset classes set, %d distinct sectors",
             renamed, classified, distinct)
    return {"renamed": renamed, "classified": classified, "sectors": distinct}
