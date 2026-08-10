"""What the platform carries, and what it refuses to carry.

Two rules meet in `apply_to_rows`, and they are different KINDS of rule. The per-symbol lists
are evidence - this ticker returned nothing on every statement page. The asset-class set is a
decision about what the platform is for. Both are tested here because both drop rows, and a
row dropped by mistake is a company that silently stops existing.
"""

from __future__ import annotations

from app.ingestion import exclusions
from app.ingestion.exclusions import KEEP_ASSET_CLASSES, apply_to_rows


def _rows(*specs: tuple[str, str, str]) -> list[dict]:
    return [{"symbol": s, "region": r, "asset_class": a} for s, r, a in specs]


def test_etfs_are_dropped(monkeypatch) -> None:
    monkeypatch.setattr(exclusions, "load_all", dict)
    kept, dropped = apply_to_rows(_rows(
        ("SPY", "us", "etf"), ("QQQ", "us", "etf"), ("AAPL", "us", "equity")))
    assert [r["symbol"] for r in kept] == ["AAPL"]
    assert dropped == 2


def test_the_four_asset_classes_the_user_asked_for_survive(monkeypatch) -> None:
    monkeypatch.setattr(exclusions, "load_all", dict)
    kept, dropped = apply_to_rows(_rows(
        ("AAPL", "us", "equity"), ("EURUSD=X", "global", "forex"),
        ("BTC-USD", "global", "crypto"), ("GC=F", "global", "commodity")))
    assert dropped == 0
    assert len(kept) == 4


def test_index_rows_survive(monkeypatch) -> None:
    """The regime engine reads ^GSPC and friends off these rows for its Index Trend.

    Dropping them would blank a signal on every market's regime card - so `index` is in the
    keep set deliberately, not by oversight.
    """
    monkeypatch.setattr(exclusions, "load_all", dict)
    kept, _ = apply_to_rows(_rows(("^GSPC", "global", "index"), ("^NSEI", "global", "index")))
    assert len(kept) == 2
    assert "index" in KEEP_ASSET_CLASSES


def test_a_row_with_no_asset_class_is_treated_as_equity(monkeypatch) -> None:
    """Older rows predate the field. Defaulting to 'drop' would delete most of the universe."""
    monkeypatch.setattr(exclusions, "load_all", dict)
    kept, dropped = apply_to_rows([{"symbol": "LUCK", "region": "psx"}])
    assert dropped == 0 and len(kept) == 1


def test_symbol_exclusions_still_apply(monkeypatch) -> None:
    monkeypatch.setattr(exclusions, "load_all", lambda: {"us": {"DEAD"}})
    kept, dropped = apply_to_rows(_rows(("DEAD", "us", "equity"), ("AAPL", "us", "equity")))
    assert [r["symbol"] for r in kept] == ["AAPL"]
    assert dropped == 1


def test_an_exclusion_is_scoped_to_its_own_market(monkeypatch) -> None:
    """Tickers collide across exchanges - PSX's ENGRO is not the US symbol of the same name."""
    monkeypatch.setattr(exclusions, "load_all", lambda: {"us": {"ABL"}})
    kept, dropped = apply_to_rows(_rows(("ABL", "us", "equity"), ("ABL", "psx", "equity")))
    assert dropped == 1
    assert [r["region"] for r in kept] == ["psx"]


def test_the_asset_class_rule_applies_with_no_exclusion_files(monkeypatch) -> None:
    """The early return on an empty exclusion list used to skip the class filter entirely."""
    monkeypatch.setattr(exclusions, "load_all", dict)
    kept, dropped = apply_to_rows(_rows(("SPY", "us", "etf")))
    assert kept == [] and dropped == 1
