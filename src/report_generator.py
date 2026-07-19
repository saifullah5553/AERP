# src/report_generator.py

import random
import json
# We import the WATCHLIST directly from the config file we created above
from src.config import WATCHLIST 

def build_dynamic_fallback_data():
    """
    AUTOMATED GENERATION ENGINE
    ---------------------------
    This function reads your master WATCHLIST from src/config.py dynamically.
    It automatically builds names, assigns realistic price floors, creates auditing text,
    and randomizes a balanced array of technical pattern strategies.
    """
    
    # A structural registry to map your base tickers to pretty, human-readable corporate names
    ASSET_NAME_REGISTRY = {
        # Pak Assets
        "LUCK.KA": "Lucky Cement Limited", "SYS.KA": "Systems Limited", 
        "AIRLINK.KA": "Air Link Communication", "ENGRO.KA": "Engro Corporation Limited",
        "HUBC.KA": "Hub Power Company", "OGDC.KA": "Oil & Gas Development Co.",
        "PPL.KA": "Pakistan Petroleum Limited", "PSO.KA": "Pakistan State Oil",
        # US Assets
        "AAPL": "Apple Inc.", "NVDA": "NVIDIA Corporation", "MSFT": "Microsoft Corporation",
        "TSLA": "Tesla Inc.", "AMZN": "Amazon.com Inc.", "GOOGL": "Alphabet Inc.",
        "META": "Meta Platforms Inc.", "AMD": "Advanced Micro Devices",
        # GCC Assets
        "2222.SR": "Saudi Arabian Oil Co. (Aramco)", "1120.SR": "Al Rajhi Bank",
        "EMAAR.DU": "Emaar Properties PJSC", "FAB.AD": "First Abu Dhabi Bank",
        "TAQA.AD": "Abu Dhabi National Energy", "ALINMA.SR": "Alinma Bank",
        # Commodities
        "GC=F": "Gold Spot Bullion", "CL=F": "Crude Oil WTI", 
        "SI=F": "Silver Spot Contract", "NG=F": "Natural Gas Futures", "BZ=F": "Brent Crude Oil",
        # Forex
        "EURUSD=X": "EUR / USD", "GBPUSD=X": "GBP / USD", "USDJPY=X": "USD / JPY",
        "AUDUSD=X": "AUD / USD", "USDCAD=X": "USD / CAD",
        # Crypto
        "BTC-USD": "Bitcoin USD", "ETH-USD": "Ethereum USD", "SOL-USD": "Solana USD",
        "BNB-USD": "BNB USD", "XRP-USD": "Ripple USD"
    }

    # Archetypal Technical Candlestick and Chart Matrix Indicators (Bullish Setups)
    BULLISH_PATTERNS = [
        "🔮 Bullish Marubozu", "📈 Ascending Triangle", "🚩 Bullish Flag (Pennant)",
        "🌅 Morning Star (Structural Bottom)", "⚓ Double Bottom Base", "📈 Bullish Engulfing Setup",
        "🙃 Inverse Head & Shoulders", "🔨 Hammer Matrix", "🌊 Elliott Wave 3: Main Impulse Surge",
        "🌊 Elliott Wave 1: Initial Accumulation", "🌊 Elliott Wave 5: Blow-off Top Peak"
    ]
    
    # Archetypal Technical Candlestick and Chart Matrix Indicators (Bearish/Correction Setups)
    BEARISH_PATTERNS = [
        "⚠️ Hanging Man (Bearish Omen)", "🏛️ Double Top Resistance", "💫 Shooting Star",
        "👤 Head & Shoulders Top", "📉 Bearish Engulfing Setup", "📉 Descending Triangle",
        "🌊 Elliott Wave 4: Complex Flat Correction", "🌊 Elliott Wave structural Breakdown",
        "🌊 Elliott Wave Phase: Final Capitulation"
    ]

    fallback_data = []

    # Safely verify that the watchlist is loaded properly from config.py
    if isinstance(WATCHLIST, dict):
        for category, tickers in WATCHLIST.items():
            for ticker in tickers:
                
                # 1. Look up name from registry. If a layman adds a totally new asset, 
                # this logic auto-creates a clean name so the program never crashes.
                name = ASSET_NAME_REGISTRY.get(ticker)
                if not name:
                    clean_ticker = ticker.replace(".KA","").replace("=X","").replace("-USD","").replace(".SR","").replace("=F","").replace(".DU","").replace(".AD","")
                    name = f"{clean_ticker} Asset Record"

                # 2. Define structural details, currency signs, and dynamic price spreads based on what asset category it belongs to
                if category == "pak":
                    price = f"PKR {random.uniform(50.0, 800.0):.2f}"
                    fd = "Q1 2026 Audited Balance Sheet"
                elif category == "us":
                    price = f"${random.uniform(50.0, 950.0):.2f}"
                    fd = "Q3 2026 SEC Form 10-Q Audited"
                elif category == "gcc":
                    currency = "SAR" if ".SR" in ticker else ("AED" if (".DU" in ticker or ".AD" in ticker) else "OMR")
                    price = f"{currency} {random.uniform(2.0, 120.0):.2f}"
                    fd = "Q2 2026 Tadawul Corporate Audit" if currency == "SAR" else "Q2 2026 DFM/ADX Financial Audit"
                elif category == "crypto":
                    if "BTC" in ticker:
                        price = f"${random.uniform(60000.0, 75000.0):.2f}"
                    elif "ETH" in ticker:
                        price = f"${random.uniform(3000.0, 4200.0):.2f}"
                    else:
                        price = f"${random.uniform(0.10, 600.0):.2f}"
                    fd = "Real-Time On-Chain Transaction & Yield Data"
                elif category == "forex":
                    # Forex requires 4 decimal points precision (e.g., 1.0924) unless it's the Japanese Yen (USDJPY)
                    price = f"{random.uniform(130.0, 160.0):.4f}" if "JPY" in ticker else f"{random.uniform(0.6, 1.4):.4f}"
                    fd = "Q2 2026 ECB/Fed Macro Ledger Metrics"
                elif category == "commodities":
                    price = f"${random.uniform(1.5, 2500.0):.2f}"
                    fd = "Monthly Global Logistics Demand & Supply Ledger"
                else:
                    price = f"{random.uniform(10.0, 500.0):.2f}"
                    fd = "2026 General Corporate Ledger Audit"

                # 3. Randomly select a balanced mixture of market patterns to assign to the dashboard indicators
                chosen_pool = random.choice([BULLISH_PATTERNS, BEARISH_PATTERNS])
                patterns = random.sample(chosen_pool, random.randint(2, 3))
                
                # 4. Pack everything neatly into the expected structural system design map
                fallback_data.append({
                    "t": ticker,
                    "n": name,
                    "c": category,
                    "p": price,
                    "fd": fd,
                    "pat": patterns
                })

    return fallback_data

# --- PREVIEW RUN FOR TESTING ---
if __name__ == "__main__":
    print("🔄 Running Dynamic Asset Pipeline Generation Engine...")
    
    # Generate the dynamic array instantly
    generated_list = build_dynamic_fallback_data()
    
    print(f"✅ Success! Generated a total of {len(generated_list)} dynamic assets.")
    print("\nHere is a preview of the first 2 dynamic assets in the data array:")
    print(json.dumps(generated_list[:2], indent=4))
