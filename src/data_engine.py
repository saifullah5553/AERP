# src/data_engine.py

import requests
from src.config import GLOBAL_WATCHLIST

def fetch_bulk_market_data():
    """
    Queries hundreds of global stocks, currencies, and cryptos simultaneously
    in clusters using a high-performance multi-ticker query pipe.
    """
    # Flatten out all tickers from our dynamically populated configuration maps
    all_tickers = []
    ticker_to_cat = {}
    
    for category, tickers in GLOBAL_WATCHLIST.items():
        for t in tickers:
            all_tickers.append(t)
            ticker_to_cat[t] = category

    # Unique values only
    all_tickers = list(set(all_tickers))
    
    # Process requests in chunks of 100 to stay safely under API data matrix maximum envelopes
    chunk_size = 100
    processed_results = {}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    print(f"🚀 Initializing bulk pipeline for {len(all_tickers)} global assets...")

    for i in range(0, len(all_tickers), chunk_size):
        chunk = all_tickers[i:i + chunk_size]
        symbols_string = ",".join(chunk)
        
        # Public multi-ticker high-speed query endpoint
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols_string}"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                quotes = data.get("quoteResponse", {}).get("result", [])
                
                for quote in quotes:
                    symbol = quote.get("symbol")
                    processed_results[symbol] = {
                        "price": quote.get("regularMarketPrice"),
                        "change_pct": quote.get("regularMarketChangePercent", 0.0),
                        "volume": quote.get("regularMarketVolume", 0),
                        "pe_ttm": quote.get("trailingPE"),
                        "market_cap": quote.get("marketCap"),
                        "name": quote.get("longName") or quote.get("shortName") or symbol,
                        "currency": quote.get("currency", "USD")
                    }
        except Exception as e:
            print(f"⚠️ Batch pipeline window failure context: {e}")
            continue

    print(f"📊 Live streaming ingestion complete. Successfully synced data records for {len(processed_results)} assets.")
    return processed_results, ticker_to_cat
