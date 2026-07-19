# src/config.py

"""
MASTER WATCHLIST CONFIGURATION
------------------------------
As a user, this is the ONLY place you need to make changes. 
If you want to add or remove any stock, crypto, forex pair, or commodity, 
simply add its symbol (ticker) to the appropriate list below.
"""

WATCHLIST = {
    # Pakistan Stock Exchange Assets
    "pak": [
        "LUCK.KA",     # Lucky Cement
        "SYS.KA",      # Systems Limited
        "AIRLINK.KA",  # Air Link Communication
        "ENGRO.KA",    # Engro Corporation
        "HUBC.KA",     # Hub Power Company
        "OGDC.KA",     # Oil & Gas Development
        "PPL.KA",      # Pakistan Petroleum
        "PSO.KA"       # Pakistan State Oil
    ],
    
    # US Stock Market Assets
    "us": [
        "AAPL",        # Apple Inc.
        "NVDA",        # NVIDIA Corporation
        "MSFT",        # Microsoft Corporation
        "TSLA",        # Tesla Inc.
        "AMZN",        # Amazon
        "GOOGL",       # Alphabet (Google)
        "META",        # Meta Platforms
        "AMD"          # Advanced Micro Devices
    ],
    
    # Gulf Cooperation Council (GCC) Markets
    "gcc": [
        "2222.SR",     # Saudi Aramco
        "1120.SR",     # Al Rajhi Bank
        "EMAAR.DU",    # Emaar Properties
        "FAB.AD",      # First Abu Dhabi Bank
        "TAQA.AD",     # Abu Dhabi National Energy
        "ALINMA.SR"    # Alinma Bank
    ],
    
    # Commodities Futures
    "commodities": [
        "GC=F",        # Gold Spot
        "CL=F",        # Crude Oil WTI
        "SI=F",        # Silver Spot
        "NG=F",        # Natural Gas
        "BZ=F"         # Brent Crude
    ],
    
    # Forex (Foreign Exchange Currency Pairs)
    "forex": [
        "EURUSD=X",    # EUR / USD
        "GBPUSD=X",    # GBP / USD
        "USDJPY=X",    # USD / JPY
        "AUDUSD=X",    # AUD / USD
        "USDCAD=X"     # USD / CAD
    ],
    
    # Cryptocurrency Assets
    "crypto": [
        "BTC-USD",     # Bitcoin
        "ETH-USD",     # Ethereum
        "SOL-USD",     # Solana
        "BNB-USD",     # BNB
        "XRP-USD"      # Ripple XRP
        # ✨ YOU CAN ADD ANY NEW TOKEN HERE (e.g., "ADA-USD", "DOGE-USD") AND IT WILL AUTOMATICALLY WORK!
    ]
}
