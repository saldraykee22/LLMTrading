import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

from agents.graph import run_analysis
from data.market_data import MarketDataClient
from models.technical_analyzer import TechnicalAnalyzer

# Piyasa verisi al
client = MarketDataClient()
df = client.fetch_ohlcv("BTC/USDT", "1h", days=7)

# DataFrame'i JSON-serializable forma çevir
df_copy = df.copy()
df_copy["datetime"] = df_copy["datetime"].astype(str)

# Teknik analiz
analyzer = TechnicalAnalyzer()
tech_result = analyzer.analyze(df)

# Dict formatına çevir
tech_signals = tech_result.to_dict() if hasattr(tech_result, "to_dict") else tech_result

# Market data hazırla (JSON serializable)
market_data = {
    "current_price": float(df["close"].iloc[-1]),
    "open": float(df["open"].iloc[-1]),
    "high": float(df["high"].iloc[-1]),
    "low": float(df["low"].iloc[-1]),
    "volume": float(df["volume"].iloc[-1]),
    "ohlcv": df_copy.to_dict(),
}

print("Running full agent analysis...")
result = run_analysis(
    "BTC/USDT", market_data=market_data, technical_signals=tech_signals
)

print("=" * 50)
print("RESULT:")
trade_dec = result.get("trade_decision", {})
print(f"Action: {trade_dec.get('action', 'N/A')}")
print(f"Amount: {trade_dec.get('amount', 0)}")
reasoning = trade_dec.get("reasoning", "N/A")
if reasoning and len(str(reasoning)) > 200:
    reasoning = str(reasoning)[:200] + "..."
print(f"Reasoning: {reasoning}")
print(f"Phase: {result.get('phase', 'N/A')}")
