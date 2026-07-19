# src/config.py

import requests

def get_dynamic_ticker_universe():
    print("Fetching live global ticker lists...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    # 1. Dynamic US Market (Top 100 High-Volume Nasdaq/NYSE Market Caps)
    # Pulls directly from an open financial data repository mirror
    us_stocks = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "NFLX", "AVGO", "QCOM", "JPM", "V", "MS", "GS", "WMT", "DIS", "XOM", "CVX"]
    try:
        res = requests.get("https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.txt", headers=headers, timeout=5)
        if res.status_code == 200:
            downloaded = [ticker.strip() for ticker in res.text.split("\n") if ticker.strip() and "^" not in ticker][:80]
            if downloaded: us_stocks = list(set(us_stocks + downloaded))
    except Exception:
        pass # Fallback to standard core set if repository mirror drops

    # 2. Pakistan Stock Exchange (PSX Active Components)
    pak_base = ["LUCK", "SYS", "AIRLINK", "ENGRO", "HUBC", "OGDC", "PPL", "PSO", "EFERT", "FFC", "MCB", "UBL", "MEBL", "HBL", "BAFL", "FCCL", "DGKC", "MLCF", "PAEL", "TRG", "WTL", "KEL"]
    pak_stocks = [f"{ticker}.KA" for ticker in pak_base]

    # 3. India Stock Exchange (NSE Core Components)
    india_base = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "BHARTIARTL", "SBIN", "ITC", "HINDUNILVR", "LT", "BAJAJFINSV", "MARUTI", "AXISBANK", "TATAMOTORS", "WIPRO", "TECHM"]
    india_stocks = [f"{ticker}.NS" for ticker in india_base]

    # 4. GCC Markets (Tadawul Saudi Arabia & Dubai/ADX Emirates)
    gcc_stocks = ["2222.SR", "1120.SR", "1150.SR", "2010.SR", "7010.SR", "EMAAR.DU", "ARMX.DU", "DEWA.DU", "FAB.AD", "ALDAR.AD", "ETISALAT.AD"]

    # 5. Forex Global Matrix Generation
    currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'INR', 'PKR', 'SAR', 'AED']
    forex_pairs = []
    for base in ['USD', 'EUR', 'GBP']:
        for quote in currencies:
            if base != quote and quote not in ['SAR', 'AED', 'PKR']:
                forex_pairs.append(f"{base}{quote}=X")

    # 6. Crypto Universe
    crypto_assets = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD", "DOGE-USD", "DOT-USD", "LINK-USD", "AVAX-USD", "NEAR-USD", "MATIC-USD"]

    return {
        "pak": pak_stocks,
        "us": us_stocks,
        "gcc": gcc_stocks,
        "india": india_stocks,
        "forex": forex_pairs,
        "crypto": crypto_assets,
        "commodities": ["GC=F", "CL=F", "SI=F", "NG=F"]
    }

GLOBAL_WATCHLIST = get_dynamic_ticker_universe()
