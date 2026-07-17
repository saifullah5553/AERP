import yfinance as yf
from src.config import WATCHLIST

def fetch_market_data():
    print("🚀 Starting Market Data Engine...")
    all_data = {}
    
    for category, tickers in WATCHLIST.items():
        print(f"Fetching {category} assets...")
        for ticker in tickers:
            try:
                asset = yf.Ticker(ticker)
                
                # 1. Fetch historical prices first (this endpoint is highly stable)
                df = asset.history(period="1y")
                
                if not df.empty:
                    # 2. Fetch metadata with its own safety bubble
                    info_data = {}
                    try:
                        info_data = asset.info
                        if not info_data or not isinstance(info_data, dict):
                            info_data = {}
                    except Exception as info_err:
                        print(f"⚠️ Note: Yahoo metadata restricted for {ticker}. Using fallback profile.")
                    
                    # 3. Apply safe defaults if Yahoo blocks the profile info
                    if not info_data.get('longName'):
                        info_data['longName'] = f"{ticker} Asset"
                    if not info_data.get('sector'):
                        info_data['sector'] = category
                    if not info_data.get('industry'):
                        info_data['industry'] = "Publicly Traded Equity"
                        
                    all_data[ticker] = {
                        "history": df,
                        "info": info_data
                    }
                    print(f"✅ Successfully loaded historical data for {ticker}")
                else:
                    print(f"⚠️ No price history data returned for {ticker}")
            except Exception as e:
                print(f"❌ Error fetching {ticker}: {e}")
                
    return all_data
