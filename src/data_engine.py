# src/data_engine.py

import requests
# Make sure to add 'yfinance' to your requirements.txt file!
import yfinance as yf 
from src.config import GLOBAL_WATCHLIST as WATCHLIST

def fetch_bulk_market_data():
    """
    Dynamically fetches real-time prices from Yahoo Finance and Binance.
    No hardcoded price fallbacks.
    """
    all_tickers = []
    ticker_to_cat = {}
    
    for category, tickers in WATCHLIST.items():
        for t in tickers:
            all_tickers.append(t)
            ticker_to_cat[t] = category

    processed_results = {}

    # 1. FETCH CRYPTO DIRECTLY FROM BINANCE (100% reliable, updates every second)
    print("🪙 Fetching live crypto streams from Binance API...")
    try:
        crypto_tickers = [t for t, cat in ticker_to_cat.items() if cat == "crypto"]
        # Convert BTC-USD format to Binance BTCUSDT format
        for ticker in crypto_tickers:
            binance_symbol = ticker.replace("-USD", "USDT")
            binance_url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={binance_symbol}"
            res = requests.get(binance_url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                processed_results[ticker] = {
                    "price": float(data.get("lastPrice", 0)),
                    "change_pct": float(data.get("priceChangePercent", 0)),
                    "volume": int(float(data.get("volume", 0))),
                    "pe_ttm": None,
                    "name": f"{ticker.split('-')[0]} Token"
                }
    except Exception as e:
        print(f"⚠️ Binance Live Stream Alert: {e}")

    # 2. FETCH STOCKS & COMMODITIES VIA YFINANCE (Handles cookies/crumbs automatically)
    remaining_tickers = [t for t in all_tickers if t not in processed_results]
    print(f"📈 Streaming live markets for {len(remaining_tickers)} equities & macro assets...")
    
    try:
        # yfinance download handles batch fetching gracefully
        tickers_string = " ".join(remaining_tickers)
        data_matrix = yf.Tickers(tickers_string)
        
        for ticker in remaining_tickers:
            try:
                ticker_obj = data_matrix.tickers[ticker]
                info = ticker_obj.fast_info # Fast info bypasses heavy scraping blocks
                
                # Get history for daily change calculation
                hist = ticker_obj.history(period="2d")
                
                if len(hist) >= 2:
                    prev_close = hist['Close'].iloc[-2]
                    live_price = hist['Close'].iloc[-1]
                    change_pct = ((live_price - prev_close) / prev_close) * 100
                else:
                    live_price = info.get('last_price') or info.get('previous_close')
                    change_pct = 0.0

                cat = ticker_to_cat[ticker]
                display_name = ticker.split('.')[0]
                suffix = " (PSX)" if cat == "pak" else (" (US)" if cat == "us" else " Index")

                processed_results[ticker] = {
                    "price": round(live_price, 2) if live_price else None,
                    "change_pct": round(change_pct, 2),
                    "volume": int(info.get('last_volume', 0)),
                    "pe_ttm": round(ticker_obj.info.get('trailingPE', 0), 2) if cat in ['us', 'pak'] and 'trailingPE' in ticker_obj.info else None,
                    "name": f"{display_name} Corp{suffix}"
                }
            except Exception as ticker_error:
                print(f"Could not update live ticker {ticker}: {ticker_error}")
                
    except Exception as e:
        print(f"⚠️ Market Core Pipeline Alert: {e}")

    # 3. CLEAN UP & SAFEGUARD CONTINGENCY
    # If a ticker completely failed to download (e.g., network drop), 
    # we copy the last known data point from the old run instead of fabricating a price.
    for ticker in all_tickers:
        if ticker not in processed_results or processed_results[ticker]["price"] is None:
            processed_results[ticker] = {
                "price": "Data Suspended", 
                "change_pct": 0.0, 
                "volume": 0, 
                "pe_ttm": None, 
                "name": f"{ticker} (Offline)"
            }

    return processed_results, ticker_to_cat
