import pandas as pd
import numpy as np

def calculate_technical_score(df):
    """Baseline technical scanner calculating RSI and Moving Average breaks"""
    if len(df) < 50:
        return 50
    
    # Simple Moving Averages
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    
    # Simple RSI calculation
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    latest_rsi = rsi.iloc[-1]
    
    score = 50
    # Trend Analysis
    if df['Close'].iloc[-1] > df['SMA_20'].iloc[-1]: score += 15
    if df['SMA_20'].iloc[-1] > df['SMA_50'].iloc[-1]: score += 15
    # RSI Condition
    if 40 <= latest_rsi <= 60: score += 20  # Healthy momentum
    elif latest_rsi > 70: score += 5       # Overbought condition
    elif latest_rsi < 30: score += 10      # Oversold bounce potential
    
    return min(max(score, 10), 100)

def calculate_fundamental_score(info):
    """Extracts fundamental health metrics out of yfinance metadata"""
    score = 50
    try:
        # Check margins
        profit_margin = info.get('profitMargins', 0)
        if profit_margin > 0.15: score += 15
        
        # Check valuation/growth health
        roe = info.get('returnOnEquity', 0)
        if roe > 0.15: score += 15
        
        # Check debt health
        debt_to_equity = info.get('debtToEquity', 100)
        if debt_to_equity < 50: score += 20
    except:
        pass
    return min(max(score, 10), 100)

def run_ranking_engine(market_data):
    print("🧠 Executing Ranking and Scoring Engines...")
    processed_reports = []
    
    for ticker, payload in market_data.items():
        df = payload["history"]
        info = payload["info"]
        
        tech_score = calculate_technical_score(df)
        fund_score = calculate_fundamental_score(info)
        
        # Mocking institutional and volume metrics based on standard derivations
        vol_score = 85 if df['Volume'].iloc[-1] > df['Volume'].rolling(20).mean().iloc[-1] else 65
        mom_score = int(tech_score * 1.05) if tech_score > 70 else int(tech_score * 0.9)
        
        overall_rating = int((tech_score * 0.35) + (fund_score * 0.35) + (vol_score * 0.15) + (mom_score * 0.15))
        overall_rating = min(overall_rating, 100)
        
        stars = "★" * int(overall_rating / 20) + "☆" * (5 - int(overall_rating / 20))
        
        processed_reports.append({
            "ticker": ticker,
            "name": info.get('longName', ticker),
            "tech_score": tech_score,
            "fund_score": fund_score,
            "vol_score": vol_score,
            "mom_score": mom_score,
            "overall": overall_rating,
            "stars": stars,
            "price": round(df['Close'].iloc[-1], 2)
        })
        
    return processed_reports
