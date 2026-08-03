from __future__ import annotations

import csv
from pathlib import Path

from app.ingestion import ohlc_store
from app.ingestion.symbols import (
    build_registry,
    norm_key,
    resolve,
    stockanalysis,
    yahoo,
)

# Every one of these was verified against the live providers - a wrong spelling does not error,
# it 404s and reads as "this company has no data".


def test_yahoo_is_exchange_spelling_plus_suffix() -> None:
    assert yahoo("us", "BRK-B") == "BRK-B"
    assert yahoo("india", "M&M") == "M&M.NS"
    assert yahoo("india", "BAJAJ-AUTO") == "BAJAJ-AUTO.NS"
    assert yahoo("australia", "BHP") == "BHP.AX"
    assert yahoo("psx", "LUCK") == "LUCK.KA"


def test_stockanalysis_spellings_differ_per_market() -> None:
    # US uses a dot where the SEC uses a dash; India uses an underscore for both '-' and '&'.
    assert stockanalysis("us", "BRK-B") == "BRK.B"
    assert stockanalysis("india", "BAJAJ-AUTO") == "BAJAJ_AUTO"
    assert stockanalysis("india", "M&M") == "M_M"
    assert stockanalysis("australia", "BHP") == "BHP"
    assert stockanalysis("psx", "LUCK") == "LUCK"


def test_norm_key_matches_across_providers() -> None:
    # The transform to stockanalysis is lossy: '_' could have been '-' or '&'. Comparisons must
    # go through the normalised key, never by inverting the transform.
    assert norm_key("M&M") == norm_key("M_M") == norm_key("M-M")
    assert norm_key("BRK-B") == norm_key("BRK.B")


def test_registry_prefers_the_real_listed_slug(tmp_path: Path) -> None:
    listed = tmp_path / "universe"
    listed.mkdir()
    with open(listed / "india.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "name"])
        w.writerow(["ODDCASE", "Odd Case Ltd"])

    slugs = {norm_key("ODD-CASE"): "ODDCASE"}
    # A listing that does not follow the rule still resolves, because what the site actually
    # serves beats what we derived.
    assert resolve("india", "ODD-CASE", slugs)["stockanalysis"] == "ODDCASE"


def test_build_registry_writes_one_row_per_company(tmp_path: Path) -> None:
    rows = [
        {"region": "india", "symbol": "M&M", "name": "Mahindra"},
        {"region": "india", "symbol": "RELIANCE", "name": "Reliance"},
        {"region": "us", "symbol": "BRK-B", "name": "Berkshire"},
    ]
    counts = build_registry(rows, out_dir=tmp_path / "symbols",
                            listed_dir=tmp_path / "no-listings")
    assert counts == {"india": 2, "us": 1}

    with open(tmp_path / "symbols" / "india.csv", encoding="utf-8") as fh:
        got = {r["symbol"]: (r["yahoo"], r["stockanalysis"]) for r in csv.DictReader(fh)}
    assert got == {"M&M": ("M&M.NS", "M_M"), "RELIANCE": ("RELIANCE.NS", "RELIANCE")}


# ── OHLC store ────────────────────────────────────────────────────────────

BARS = [
    {"date": "2026-07-29", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
    {"date": "2026-07-30", "open": 1.5, "high": 3, "low": 1.4, "close": 2.5, "volume": 200},
]


def test_bars_are_stored_and_reloaded(tmp_path: Path) -> None:
    assert ohlc_store.save_bars("psx", "LUCK", BARS, store=tmp_path) == 2
    got = ohlc_store.load_bars("psx", "LUCK", store=tmp_path)
    assert sorted(got) == ["2026-07-29", "2026-07-30"]
    assert got["2026-07-30"][4] == "2.5"


def test_appending_is_idempotent_and_never_rewrites_history(tmp_path: Path) -> None:
    ohlc_store.save_bars("psx", "LUCK", BARS, store=tmp_path)
    # Same dates again, with different numbers - a restatement, or a bad fetch. Either way the
    # stored bar wins: silently replacing it would corrupt a backtest undetectably.
    changed = [{**BARS[0], "close": 99.0}, BARS[1]]
    assert ohlc_store.save_bars("psx", "LUCK", changed, store=tmp_path) == 0
    assert ohlc_store.load_bars("psx", "LUCK", store=tmp_path)["2026-07-29"][4] == "1.5"


def test_new_bars_merge_into_existing_history_in_order(tmp_path: Path) -> None:
    ohlc_store.save_bars("psx", "LUCK", BARS[1:], store=tmp_path)
    # An earlier bar arriving later must slot in, not append out of order.
    assert ohlc_store.save_bars("psx", "LUCK", BARS[:1], store=tmp_path) == 1
    with open(tmp_path / "psx" / "LUCK.csv", encoding="utf-8") as fh:
        dates = [r["date"] for r in csv.DictReader(fh)]
    assert dates == ["2026-07-29", "2026-07-30"]


def test_bars_from_chart_skips_gaps() -> None:
    res = {
        "timestamp": [1753747200, 1753833600, 1753920000],
        "indicators": {"quote": [{
            "open": [1, None, 3], "high": [2, None, 4],
            "low": [0.5, None, 2], "close": [1.5, None, 3.5], "volume": [10, None, 30],
        }]},
    }
    bars = ohlc_store.bars_from_chart(res)
    # A null close is a non-trading day, not a zero.
    assert [b["close"] for b in bars] == [1.5, 3.5]


def test_reserved_windows_name_is_skipped_not_crashed(tmp_path: Path) -> None:
    assert ohlc_store.save_bars("australia", "PRN", BARS, store=tmp_path) == 0


# ── Windows device names ──────────────────────────────────────────────────

def test_reserved_device_names_are_recognised() -> None:
    from app.core.safe_path import is_reserved, safe_file

    # CON is a real US ticker (Concentra Group). On Windows `company/CON.json` is the console,
    # not a file: exists() says True and the read then blocks forever at 0% CPU. That wedged
    # the quality-history job five times before it was found.
    assert is_reserved("CON.json")
    assert is_reserved("PRN.AX.json")
    assert is_reserved("nul.json")
    assert not is_reserved("CONN.json")
    assert not is_reserved("AAPL.json")

    assert safe_file(Path("company"), "CON.json") is None
    assert safe_file(Path("company"), "AAPL.json") == Path("company") / "AAPL.json"


def test_news_query_names_the_country() -> None:
    from types import SimpleNamespace

    from app.ingestion.news import _query_for

    # A quoted name still matches inside a longer one: "Systems Limited" (Pakistan) pulled back
    # Persistent Systems Limited's Indian results, which read as Systems having reported.
    psx = SimpleNamespace(name="Systems Limited", symbol="SYS", country="PK")
    assert _query_for(psx) == '"Systems Limited" Pakistan'

    us = SimpleNamespace(name="Apple Inc", symbol="AAPL", country="US")
    assert _query_for(us) == '"Apple Inc"'

    unnamed = SimpleNamespace(name=None, symbol="XYZ", country="IN")
    assert _query_for(unnamed) == "XYZ stock India"
