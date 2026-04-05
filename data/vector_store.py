import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR
import chromadb

logger = logging.getLogger(__name__)
STORE_DIR = DATA_DIR / "vector_cache"

class AgentMemoryStore:
    """ChromaDB tabanlı RAG hafıza sistemi."""

    def __init__(self, store_dir: Path | None = None):
        self._dir = store_dir or STORE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            self.client = chromadb.PersistentClient(path=str(self._dir))
            # Cümle transformerları (all-MiniLM-L6-v2) otomatik dahil olur.
            self.collection = self.client.get_or_create_collection(name="trade_memory")
        except Exception as e:
            logger.error("ChromaDB başlatılamadı (Memory devre dışı): %s", e)
            self.collection = None

    def _build_context_text(self, state: dict[str, Any]) -> str:
        """Piyasa durumunu gömülmeye hazır bir metne dönüştürür."""
        market = state.get("market_data", {})
        news = state.get("news_data", [])
        tech = state.get("technical_signals", {})
        
        price = market.get("current_price", 0)
        vix = tech.get("vix", 0)
        macd_hist = tech.get("macd", {}).get("histogram", 0)
        
        news_titles = " | ".join(n.get("title", "") for n in news[:2])
        return f"Price: {price}, VIX: {vix}, MACD Hist: {macd_hist}. News: {news_titles}"

    def store_decision(self, state: dict[str, Any], accuracy_score: float = 0.0):
        """Ajanın verdiği kararı ve o anki durumu kaydeder."""
        if not self.collection:
            return
            
        symbol = state.get("symbol", "UNKNOWN")
        decision = state.get("trade_decision", {})
        action = decision.get("action", "hold")
        
        doc_text = self._build_context_text(state)
        metadata = {
            "symbol": symbol,
            "action": action,
            "accuracy": float(accuracy_score),
            "timestamp": datetime.now().isoformat()
        }
        
        doc_id = f"{symbol}_{datetime.now().timestamp()}"
        
        try:
            self.collection.add(
                documents=[doc_text],
                metadatas=[metadata],
                ids=[doc_id]
            )
            logger.debug("Karar hafızaya işlendi: %s", doc_id)
        except Exception as e:
            logger.error("Vektör db kayıt hatası: %s", e)

    def query_similar_conditions(self, state: dict[str, Any], n_results: int = 3) -> list[dict]:
        """Şu anki piyasa durumuna en çok benzeyen geçmiş durumları sorgular."""
        if not self.collection:
            return []
            
        symbol = state.get("symbol", "UNKNOWN")
        query_text = self._build_context_text(state)
        
        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where={"symbol": symbol}
            )
            
            history = []
            if results and results.get("metadatas") and len(results["metadatas"]) > 0:
                for i, meta in enumerate(results["metadatas"][0]):
                    doc = results["documents"][0][i]
                    history.append({
                        "past_action": meta.get("action"),
                        "past_accuracy": meta.get("accuracy"),
                        "market_context": doc[:100] + "..."
                    })
            return history
        except Exception as e:
            logger.error("Vektör sorgu hatası: %s", e)
            return []
