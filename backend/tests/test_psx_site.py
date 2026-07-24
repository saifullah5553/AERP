from __future__ import annotations

from app.ingestion.psx_site import parse_company_metrics

SAMPLE_HTML = """
<div class="stats">
  <div><span>P/E</span><span>8.42</span></div>
  <div><span>Dividend Yield</span><span>6.10%</span></div>
</div>
"""


def test_parse_company_metrics() -> None:
    metrics = parse_company_metrics(SAMPLE_HTML)
    assert metrics["pe_ttm"] == 8.42
    # Dividend yield stored as a fraction to match the equity convention.
    assert abs(metrics["dividend_yield"] - 0.061) < 1e-9


def test_parse_company_metrics_empty() -> None:
    assert parse_company_metrics("<html>no stats here</html>") == {}
