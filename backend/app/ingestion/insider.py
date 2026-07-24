"""Insider-transaction ingestion from SEC EDGAR Form 4 filings (free, keyless).

For each US security (identified by CIK), we read its recent Form 4 filings from
the SEC submissions API and parse the ownership XML into transactions. Only
open-market purchases (code P) and sales (code S) are treated as buy/sell signals;
grants and option exercises are recorded but excluded from the buy/sell score.

HTTP is injectable for testing, and the XML parser is a pure function tested
against a sample filing — no network needed to test the logic.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.corporate import InsiderTransaction
from app.models.enums import AssetClass, InsiderTransactionType
from app.models.market import Security

log = get_logger(__name__)

HEADERS = {"User-Agent": "AERP equity research (contact: admin@aerp.local)"}
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

# Form 4 transaction code → our type. P/S are the informative open-market trades.
CODE_MAP = {
    "P": InsiderTransactionType.BUY,
    "S": InsiderTransactionType.SELL,
    "A": InsiderTransactionType.GRANT,
    "M": InsiderTransactionType.EXERCISE,
    "F": InsiderTransactionType.EXERCISE,
}


@dataclass(slots=True)
class Form4Ref:
    accession: str          # with dashes, e.g. 0001234567-25-000123
    primary_doc: str
    filing_date: date | None


@dataclass(slots=True)
class InsiderTxn:
    owner: str | None
    title: str | None
    transaction_date: date | None
    transaction_type: InsiderTransactionType
    shares: float | None
    price: float | None
    value: float | None


def _f(text: str | None) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text[:10]) if text else None
    except (TypeError, ValueError):
        return None


def parse_form4(xml_text: str) -> list[InsiderTxn]:
    """Parse a Form 4 ownership XML into transactions (namespace-free schema)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName")
    rel = root.find(".//reportingOwner/reportingOwnerRelationship")
    title = None
    if rel is not None:
        title = rel.findtext("officerTitle")
        if not title:
            flags = [t for t, tag in (("Director", "isDirector"), ("Officer", "isOfficer"),
                                      ("10% Owner", "isTenPercentOwner"))
                     if (rel.findtext(tag) or "").strip() in {"1", "true"}]
            title = ", ".join(flags) or None

    out: list[InsiderTxn] = []
    for txn in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = (txn.findtext(".//transactionCoding/transactionCode") or "").strip().upper()
        ttype = CODE_MAP.get(code)
        if ttype is None:
            continue
        shares = _f(txn.findtext(".//transactionAmounts/transactionShares/value"))
        price = _f(txn.findtext(".//transactionAmounts/transactionPricePerShare/value"))
        value = shares * price if shares is not None and price is not None else None
        out.append(
            InsiderTxn(
                owner=owner,
                title=title,
                transaction_date=_date(txn.findtext(".//transactionDate/value")),
                transaction_type=ttype,
                shares=shares,
                price=price,
                value=value,
            )
        )
    return out


class EdgarClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        return self._client

    def recent_form4(self, cik: str, limit: int = 20) -> list[Form4Ref]:
        try:
            resp = self._http().get(SUBMISSIONS_URL.format(cik=cik), headers=HEADERS)
            resp.raise_for_status()
            recent = resp.json().get("filings", {}).get("recent", {})
        except Exception as exc:
            log.warning("EDGAR submissions failed for CIK %s: %s", cik, exc)
            return []
        forms = recent.get("form", [])
        accs = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        dates = recent.get("filingDate", [])
        refs: list[Form4Ref] = []
        for i, form in enumerate(forms):
            if form != "4":
                continue
            refs.append(Form4Ref(accs[i], docs[i] if i < len(docs) else "",
                                 _date(dates[i]) if i < len(dates) else None))
            if len(refs) >= limit:
                break
        return refs

    def fetch_form4_xml(self, cik: str, ref: Form4Ref) -> str | None:
        acc_nodash = ref.accession.replace("-", "")
        # primaryDocument is often the XSL *viewer* path (e.g. "xslF345X06/form4.xml");
        # the raw ownership XML is the same basename without the viewer prefix.
        doc = ref.primary_doc.rsplit("/", 1)[-1]
        if not doc.endswith(".xml"):
            return None  # only the machine-readable ownership XML is parseable
        url = ARCHIVE_URL.format(cik=int(cik), acc=acc_nodash, doc=doc)
        try:
            resp = self._http().get(url, headers=HEADERS)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            log.warning("EDGAR doc failed (%s): %s", url, exc)
            return None


def ingest_insider_for_security(
    db: Session, client: EdgarClient, security: Security, filings_limit: int = 20
) -> int:
    if not security.cik:
        return 0
    written = 0
    for ref in client.recent_form4(security.cik, limit=filings_limit):
        xml_text = client.fetch_form4_xml(security.cik, ref)
        if not xml_text:
            continue
        for txn in parse_form4(xml_text):
            if txn.transaction_date is None:
                continue
            db.add(
                InsiderTransaction(
                    security_id=security.id,
                    transaction_date=txn.transaction_date,
                    insider_name=txn.owner,
                    insider_title=txn.title,
                    transaction_type=txn.transaction_type,
                    shares=txn.shares,
                    price=txn.price,
                    value=txn.value,
                )
            )
            written += 1
    return written


def ingest_insider(
    db: Session, client: EdgarClient, limit: int | None = None, filings_limit: int = 20
) -> dict[str, int]:
    """Ingest insider transactions for US equities that have a CIK."""
    stmt = select(Security).where(
        Security.asset_class == AssetClass.EQUITY,
        Security.cik.is_not(None),
        Security.is_active.is_(True),
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    securities = list(db.scalars(stmt))
    covered = 0
    total = 0
    for security in securities:
        n = ingest_insider_for_security(db, client, security, filings_limit)
        if n:
            covered += 1
            total += n
            db.commit()
    result = {"securities": len(securities), "covered": covered, "transactions": total}
    log.info("ingest_insider: %s", result)
    return result
