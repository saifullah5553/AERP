import yfinance as yf
import pandas as pd
from src.config import WATCHLIST

def fetch_market_data():
    print("🚀 Starting Market Data Engine...")
    all_data = {}

    for category, tickers in WATCHLIST.items():
        print(f"Fetching {category} assets...")
        for ticker in tickers:
            try:
                asset = yf.Ticker(ticker)
                df = asset.history(period="1y")
                if not df.empty:
                    all_data[ticker] = {
                        "history": df,
                        "info": asset.info
                    }
                    print(f"✅ Successfully loaded {ticker}")
                else:
                    print(f"⚠️ No data returned for {ticker}")
            except Exception as e:
                print(f"❌ Error fetching {ticker}: {e}")

    return all_data

if __name__ == "__main__":
    data = fetch_market_data()
