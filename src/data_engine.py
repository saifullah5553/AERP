import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yfinance as yf
from src.config import WATCHLIST

def create_secure_session():
    """
    Creates a resilient network session with browser emulation headers
    and automatic exponential backoff retry policies.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    })
    retry_strategy = Retry(
        total=4,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        backoff_factor=2  # Delays: 2s, 4s, 8s, 16s between retries
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def fetch_market_data():
    """
    Throttled, Session-Insulated Market Data Fetcher.
    Uses explicit session masquerading to bypass GitHub runner IP locks.
    """
    print("📥 Initializing Secure Throttled Data Engine...")
    data_package = {}
    session = create_secure_session()
    
    # Dynamically flatten the watchlist regardless of dictionary or list structure
    items_to_fetch = []
    if isinstance(WATCHLIST, dict):
        for category, tickers in WATCHLIST.items():
            if isinstance(tickers, list):
                for ticker in tickers:
                    items_to_fetch.append((ticker, category))
            elif isinstance(tickers, dict):
                for ticker in tickers.keys():
                    items_to_fetch.append((ticker, category))
    elif isinstance(WATCHLIST, list):
        for ticker in WATCHLIST:
            items_to_fetch.append((ticker, "general"))

    # Execute throttled processing loop over asset tracking list
    for ticker, category in items_to_fetch:
        print(f"🔄 Requesting context array for {ticker} [{category}]...")
        try:
            # Pacing delay to remain underneath provider query rate ceilings
            time.sleep(2.5)
            
            # Mount the authenticated network session into the ticker module
            asset = yf.Ticker(ticker, session=session)
            hist = asset.history(period="3mo", interval="1d")
            
            if hist.empty:
                print(f"⚠️ Warning: Empty historical matrix returned for {ticker}. Skipping.")
                continue
                
            try:
                q_fin = asset.quarterly_financials
            except Exception:
                q_fin = None
                
            try:
                info = asset.info
                if not info or "longName" not in info:
                    info = {"longName": f"{ticker} Asset"}
            except Exception:
                info = {"longName": f"{ticker} Asset"}
                
            data_package[ticker] = {
                "history": hist,
                "quarterly_financials": q_fin,
                "info": info,
                "category": category
            }
            
        except Exception as e:
            print(f"⚠️ Safe Skip: Network limit encountered on {ticker}: {e}. Continuing pipeline matrix...")
            continue
            
    print(f"📋 Data compilation phase terminated. Successfully populated {len(data_package)} live components.")
    return data_package
