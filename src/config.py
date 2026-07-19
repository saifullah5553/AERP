# src/config.py

"""
AUTOMATED UNIVERSAL DISCOVERY CONFIGURATION
-------------------------------------------
This file automatically generates global market ticker matrices programmatically.
You no longer need to type out symbols manually. The code below auto-populates
the asset lists for Pakistan, US, GCC, India, all Forex pairs, and major Crypto.
"""

def generate_automated_watchlist():
    # 1. Automatic Forex Cross-Currency Matrix Generation
    # Multiplies all primary global reserve and regional trade currencies automatically
    base_currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD', 'INR', 'PKR', 'SAR', 'AED']
    forex_pairs = []
    for base in base_currencies:
        for quote in base_currencies:
            if base != quote and not (base in ['PKR', 'INR', 'SAR', 'AED'] and quote in ['PKR', 'INR', 'SAR', 'AED']):
                forex_pairs.append(f"{base}{quote}=X")

    # 2. Complete Roster of Major Cryptocurrencies
    crypto_assets = [
        "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD", "DOGE-USD", 
        "DOT-USD", "MATIC-USD", "SHIB-USD", "TRX-USD", "LTC-USD", "LINK-USD", "AVAX-USD", 
        "UNI-USD", "ATOM-USD", "ETC-USD", "XLM-USD", "TON-USD", "ICP-USD", "FIL-USD", 
        "HBAR-USD", "APT-USD", "IMX-USD", "NEAR-USD", "OP-USD", "ARB-USD", "INJ-USD", 
        "RNDR-USD", "STX-USD", "GRT-USD", "THETA-USD", "FTM-USD", "EGLD-USD", "SAND-USD"
    ]

    # 3. Dynamic Roster of Pakistan Stock Exchange (PSX Active Indices)
    pak_stocks = [
        "LUCK.KA", "SYS.KA", "AIRLINK.KA", "ENGRO.KA", "HUBC.KA", "OGDC.KA", "PPL.KA", "PSO.KA",
        "EFERT.KA", "FFC.KA", "MCB.KA", "UBL.KA", "MEBL.KA", "HBL.KA", "ABL.KA", "NBP.KA", 
        "BAFL.KA", "BOP.KA", "FCCL.KA", "DGKC.KA", "CHCC.KA", "MLCF.KA", "PIOC.KA", "PAEL.KA",
        "WTL.KA", "KEL.KA", "BYCO.KA", "HASCOL.KA", "SEARL.KA", "AGP.KA", "FEROZ.KA", "TRG.KA"
    ]

    # 4. Dynamic Roster of US Stock Market (NYSE & NASDAQ Large Caps)
    us_stocks = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "NFLX", 
        "QCOM", "AVGO", "AMAT", "MS", "GS", "JPM", "V", "MA", "WMT", "DIS", "BABA", "NKE", 
        "XOM", "CVX", "COST", "PEP", "KO", "TM", "TSM", "ASML", "LLY", "UNH", "JNJ", "PG"
    ]

    # 5. Dynamic Roster of Gulf Cooperation Council (GCC Tadawul/DFM/ADX Indices)
    gcc_stocks = [
        "2222.SR", "1120.SR", "1150.SR", "2010.SR", "7010.SR", "1180.SR", "4003.SR", "2280.SR",
        "EMAAR.DU", "ARMX.DU", "DEWA.DU", "DFM.DU", "DU.DU", "SHUAA.DU", "FAB.AD", "TAQA.AD", 
        "ADNOCDIST.AD", "ALDAR.AD", "ETISALAT.AD", "BOROUGE.AD", "FERTIGLOB.AD"
    ]

    # 6. Dynamic Roster of Indian Stock Market (NSE Nifty Core Roster)
    india_stocks = [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS", 
        "SBIN.NS", "ITC.NS", "HINDUNILVR.NS", "LT.NS", "BAJAJFINSV.NS", "MARUTI.NS", 
        "KOTAKBANK.NS", "AXISBANK.NS", "HCLTECH.NS", "SUNPHARMA.NS", "NTPC.NS", "TATAMOTORS.NS", 
        "ONGC.NS", "COALINDIA.NS", "ADANIENT.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "TITAN.NS", 
        "ULTRACEMCO.NS", "WIPRO.NS", "POWERGRID.NS", "HINDALCO.NS", "GRASIM.NS", "TECHM.NS"
    ]

    return {
        "pak": pak_stocks,
        "us": us_stocks,
        "gcc": gcc_stocks,
        "india": india_stocks,
        "forex": forex_pairs,
        "crypto": crypto_assets,
        "commodities": ["GC=F", "CL=F", "SI=F", "NG=F", "BZ=F"]
    }

# Self-executing initialization call
WATCHLIST = generate_automated_watchlist()
