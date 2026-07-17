import yfinance as yf
import requests
from src.config import WATCHLIST

def get_camouflaged_session():
    """Creates a requests session configured to mimic a desktop web browser browser."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive'
    })
    return session

def fetch_market_data():
    print("🚀 Running AERP Browser Camouflage Data Engine...")
    all_data = {}
    session = get_camouflaged_session()
    
    for category, tickers in WATCHLIST.items():
        print(f"Pulling live data matrix for category: [{category.upper()}]")
        for ticker in tickers:
            try:
                # Directing yfinance to use our custom masqueraded network browser session
                asset = yf.Ticker(ticker, session=session)
                
                # Fetch live historical daily charts
                df = asset.history(period="1mo")
                
                if not df.empty:
                    # Explicitly pull official quarterly and annual statement sheets
                    try:
                        q_financials = asset.quarterly_financials
                        balance_sheet = asset.balance_sheet
                    except Exception:
                        q_financials = None
                        balance_sheet = None
                        
                    all_data[ticker] = {
                        "history": df,
                        "quarterly_financials": q_financials,
                        "balance_sheet": balance_sheet,
                        "category": category,
                        "info": asset.info if isinstance(asset.info, dict) else {}
                    }
                    print(f"✅ Downloaded historical data & financial statements for {ticker}")
                else:
                    print(f"⚠️ Empty price matrix returned for {ticker}")
            except Exception as e:
                print(f"❌ Network issue reading {ticker}: {e}")
                
    return all_data
