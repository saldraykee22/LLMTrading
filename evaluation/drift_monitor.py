import logging
import json
from pathlib import Path
from datetime import datetime, timezone

from data.sentiment_store import SentimentStore
from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

class DriftMonitor:
    """LLM Concept Drift ve İsabet Oranı Takipçisi."""
    
    def __init__(self):
        self.store = SentimentStore()
        self.accuracy_cache_file = DATA_DIR / "agent_accuracy.json"
        
    def _save_accuracy_cache(self, symbol: str, accuracy: float):
        data = {}
        if self.accuracy_cache_file.exists():
            with open(self.accuracy_cache_file, "r") as f:
                data = json.load(f)
        data[symbol] = accuracy
        with open(self.accuracy_cache_file, "w") as f:
            json.dump(data, f)
            
    def get_agent_accuracy(self, symbol: str) -> float:
        """Kayıtlı isabet oranını döner. Yoksa 1.0 (Güvenli kabul et)."""
        if self.accuracy_cache_file.exists():
            with open(self.accuracy_cache_file, "r") as f:
                data = json.load(f)
                return data.get(symbol, 1.0)
        return 1.0
        
    def evaluate_drift(self, symbol: str, current_price: float) -> float:
        """Ajanın geçmiş sentiment tahminleri ile anlık fiyatı kıyaslayarak isabet oranını hesaplar."""
        records = self.store.load(symbol, last_n=5)
        if len(records) < 2:
            return 1.0 
            
        correct = 0
        total = 0
        
        for r in records[:-1]:
            if r.price > 0 and current_price > 0: 
                price_change = current_price - r.price
                signal_dir = 1 if r.sentiment_score > 0 else -1 if r.sentiment_score < 0 else 0
                price_dir = 1 if price_change > 0 else -1 if price_change < 0 else 0
                
                if signal_dir == price_dir or signal_dir == 0:
                    correct += 1
                total += 1
                
        accuracy = (correct / total) if total > 0 else 1.0
        logger.info(f"[Drift Monitor] {symbol} Agent Accuracy: %{accuracy*100:.1f}")
        self._save_accuracy_cache(symbol, float(accuracy))
        return float(accuracy)
