import time
import yfinance as yf
from src.config import WATCHLIST

def fetch_market_data():
    """
    Throttled, Fault-Tolerant Market Data Fetcher.
    Introduces explicit cooling windows between API requests to bypass provider 429 locks.
    """
    print("📥 Initializing Throttled Data Engine...")
    data_package = {}
    
    # Dynamically flatten the watchlist regardless of structure configuration
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

    # Execute throttled loops over target asset tokens
    for ticker, category in items_to_fetch:
        print(f"🔄 Requesting context array for {ticker} [{category}]...")
        try:
            # REQUEST THROTTLING: Cooling delay to safeguard provider boundaries
            time.sleep(2.0)
            
            asset = yf.Ticker(ticker)
            
            # Extract daily pricing metrics over a rolling 3-month window
            hist = asset.history(period="3mo", interval="1d")
            
            if hist.empty:
                print(f"⚠️ Warning: Received empty history footprint for {ticker}. Skipping asset.")
                continue
                
            # Safely extract supplementary balance sheet metrics
            try:
                q_fin = asset.quarterly_financials
            except Exception:
                q_fin = None
                
            # Safely extract corporate naming matrices
            try:
                info = asset.info
                if not info or "longName" not in info:
                    info = {"longName": f"{ticker} Asset"}
            except Exception:
                info = {"longName": f"{ticker} Asset"}
                
            # Build valid dictionary entry
            data_package[ticker] = {
                "history": hist,
                "quarterly_financials": q_fin,
                "info": info,
                "category": category
            }
            
        except Exception as e:
            # FAULT-TOLERANT EXCEPTION WRAPPER: Logs issues instead of terminating process
            print(f"⚠️ Safe Skip: Network issue reading {ticker}: {e}. Continuing processing matrix...")
            continue
            
    print(f"📋 Data compilation phase terminated. Successfully populated {len(data_package)} live components.")
    return data_package
