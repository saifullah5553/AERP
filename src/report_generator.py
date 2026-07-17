import os
from jinja2 import Template
from src.data_engine import fetch_market_data
from src.analysis_engine import run_ranking_engine

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Equity Research Platform (AERP)</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 40px; }
        h1 { color: #38bdf8; border-bottom: 2px solid #334155; padding-bottom: 10px; margin-bottom: 5px; }
        .status-banner { background: #1e293b; border-left: 4px solid #f59e0b; padding: 12px; margin-bottom: 20px; border-radius: 4px; font-size: 0.9rem; color: #cbd5e1; }
        .card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; margin-top: 20px; }
        .card { background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        .ticker { font-size: 1.5rem; font-weight: bold; color: #38bdf8; }
        .company-name { font-size: 0.9rem; color: #94a3b8; margin-bottom: 15px; }
        .score-row { display: flex; justify-content: space-between; margin: 6px 0; font-size: 0.95rem; }
        .overall-box { background: #0f172a; padding: 12px; border-radius: 8px; text-align: center; margin-top: 15px; border: 1px solid #0284c7;}
        .rating-num { font-size: 1.8rem; font-weight: bold; color: #4ade80; }
        .stars { color: #f59e0b; font-size: 1.2rem; }
    </style>
</head>
<body>
    <h1>AI Equity Research Platform (AERP) - Daily Report</h1>
    
    {% if using_backup %}
    <div class="status-banner">
        ⚠️ <strong>Notice:</strong> Yahoo Finance restricted live connections from GitHub cloud datacenters. The AERP Backup Engine has automatically activated to populate your custom platform interface with simulated data.
    </div>
    {% else %}
    <p style="color: #94a3b8;">Automated Market Analysis Engine Live Status Updates</p>
    {% endif %}
    
    <div class="card-grid">
        {% for stock in stocks %}
        <div class="card">
            <div class="ticker">{{ stock.ticker }}</div>
            <div class="company-name">{{ stock.name }} | Price: ${{ stock.price }}</div>
            <hr style="border-color: #334155;">
            <div class="score-row"><span>Technical Score:</span> <strong>{{ stock.tech_score }}</strong></div>
            <div class="score-row"><span>Fundamental Score:</span> <strong>{{ stock.fund_score }}</strong></div>
            <div class="score-row"><span>Volume Score:</span> <strong>{{ stock.vol_score }}</strong></div>
            <div class="score-row"><span>Momentum Score:</span> <strong>{{ stock.mom_score }}</strong></div>
            
            <div class="overall-box">
                <div>Overall Rating</div>
                <div class="rating-num">{{ stock.overall }} / 100</div>
                <div class="stars">{{ stock.stars }}</div>
            </div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
"""

def generate_daily_report():
    raw_data = fetch_market_data()
    analysis_results = run_ranking_engine(raw_data)
    
    using_backup = False
    
    # Fallback Mechanism: If live data is empty due to cloud network blockades, inject your target list
    if not analysis_results:
        print("⚠️ Live feed blocked by server provider. Activating AERP Internal Simulation Suite...")
        using_backup = True
        analysis_results = [
            {"ticker": "LUCK.KA", "name": "Lucky Cement Limited", "tech_score": 93, "fund_score": 91, "vol_score": 88, "mom_score": 96, "overall": 93, "stars": "★★★★★", "price": 725.40},
            {"ticker": "SYS.KA", "name": "Systems Limited", "tech_score": 91, "fund_score": 88, "vol_score": 85, "mom_score": 92, "overall": 90, "stars": "★★★★★", "price": 412.00},
            {"ticker": "AIRLINK.KA", "name": "Air Link Communication", "tech_score": 65, "fund_score": 72, "vol_score": 66, "mom_score": 69, "overall": 68, "stars": "★★★☆☆", "price": 54.80},
            {"ticker": "AAPL", "name": "Apple Inc.", "tech_score": 85, "fund_score": 95, "vol_score": 80, "mom_score": 88, "overall": 89, "stars": "★★★★☆", "price": 178.20},
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "tech_score": 98, "fund_score": 92, "vol_score": 95, "mom_score": 99, "overall": 96, "stars": "★★★★★", "price": 875.10},
            {"ticker": "BTC-USD", "name": "Bitcoin USD", "tech_score": 74, "fund_score": 50, "vol_score": 88, "mom_score": 82, "overall": 72, "stars": "★★★☆☆", "price": 64500.00}
        ]
    
    os.makedirs("public", exist_ok=True)
    
    template = Template(HTML_TEMPLATE)
    rendered_html = template.render(stocks=analysis_results, using_backup=using_backup)
    
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(rendered_html)
        
    print("✨ Static HTML Dashboard updated successfully.")

if __name__ == "__main__":
    generate_daily_report()
