import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR
import chromadb

logger = logging.getLogger(__name__)
STORE_DIR = DATA_DIR / "vector_cache"


class AgentMemoryStore:
    """ChromaDB tabanlı RAG hafıza sistemi - Singleton."""

    _instance: "AgentMemoryStore | None" = None
    _class_lock = threading.Lock()

    def __new__(cls, store_dir: Path | None = None) -> "AgentMemoryStore":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
                cls._instance._lock = threading.RLock()
            return cls._instance

    def __init__(self, store_dir: Path | None = None):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._dir = store_dir or STORE_DIR
            self._dir.mkdir(parents=True, exist_ok=True)
            self._client = None
            self._collection = None
            self._init_failed = False
            self._shutdown_registered = False
            self._initialized = True

    @classmethod
    def get_instance(cls) -> "AgentMemoryStore":
        """Singleton instance al."""
        return cls()

    @classmethod
    def close_all(cls) -> None:
        """Singleton instance'ı kapat."""
        if cls._instance:
            cls._instance.close()
            cls._instance = None

    @property
    def collection(self):
        if self._collection is not None or self._init_failed:
            return self._collection
            
        with self._lock:
            # Double check inside lock
            if self._collection is not None or self._init_failed:
                return self._collection
                
            try:
                self._client = chromadb.PersistentClient(path=str(self._dir))
                self._collection = self._client.get_or_create_collection(name="trade_memory")
            except Exception as e:
                logger.error("ChromaDB başlatılamadı (Memory devre dışı): %s", e)
                self._init_failed = True
            return self._collection

    def _generate_semantic_tags(self, state: dict[str, Any]) -> list[str]:
        """Piyasa durumuna göre semantik etiketler üretir."""
        tags: list[str] = []
        tech = state.get("technical_signals", {})
        market = state.get("market_data", {})
        sentiment = state.get("sentiment", {})

        price = market.get("current_price", 0)
        ema20 = tech.get("ema20", 0)
        ema50 = tech.get("ema50", 0)
        sma200 = tech.get("sma200", 0)
        rsi = (
            tech.get("rsi", {}).get("value", 50)
            if isinstance(tech.get("rsi"), dict)
            else tech.get("rsi", 50)
        )
        vix = tech.get("vix", 0)
        macd_data = tech.get("macd", {})
        macd_hist = macd_data.get("histogram", 0) if isinstance(macd_data, dict) else 0
        bb_data = tech.get("bollinger_bands", {})
        atr = (
            tech.get("atr", {}).get("value", 0)
            if isinstance(tech.get("atr"), dict)
            else tech.get("atr", 0)
        )
        volume_ratio = market.get("volume_ratio", 1.0)
        sentiment_score = sentiment.get("sentiment_score", 0)

        if price > ema20 > ema50:
            tags.append("bullish_trend")
        elif price < ema20 < ema50:
            tags.append("bearish_trend")

        if isinstance(rsi, (int, float)):
            if rsi < 30:
                tags.append("oversold")
            elif rsi > 70:
                tags.append("overbought")

        if isinstance(macd_hist, (int, float)):
            if macd_hist > 0:
                tags.append("macd_bullish")
            else:
                tags.append("macd_bearish")

        if isinstance(vix, (int, float)):
            if vix > 30:
                tags.append("high_volatility")
            elif vix < 15:
                tags.append("low_volatility")

        if isinstance(atr, (int, float)) and atr > 0 and price > 0:
            atr_pct = (atr / price) * 100
            if atr_pct > 3:
                tags.append("high_atr")

        if isinstance(volume_ratio, (int, float)) and volume_ratio > 1.5:
            tags.append("high_volume")

        if isinstance(sentiment_score, (int, float)):
            if sentiment_score > 0.3:
                tags.append("bullish_sentiment")
            elif sentiment_score < -0.3:
                tags.append("bearish_sentiment")

        if sma200 > 0 and price > sma200:
            tags.append("above_sma200")
        elif sma200 > 0 and price < sma200:
            tags.append("below_sma200")

        if isinstance(bb_data, dict):
            upper = bb_data.get("upper", 0)
            lower = bb_data.get("lower", 0)
            if upper > 0 and lower > 0:
                bb_position = (price - lower) / (upper - lower)
                if bb_position > 0.9:
                    tags.append("near_bb_upper")
                elif bb_position < 0.1:
                    tags.append("near_bb_lower")

        now = datetime.now(timezone.utc)
        if now.month in (2, 5, 8, 11):
            tags.append("earnings_season")

        if not tags:
            tags.append("neutral")

        return tags

    def _determine_market_regime(self, state: dict[str, Any]) -> str:
        """VIX ve volatiliteye göre piyasa rejimini belirler."""
        tech = state.get("technical_signals", {})
        vix = tech.get("vix", 0)
        atr = (
            tech.get("atr", {}).get("value", 0)
            if isinstance(tech.get("atr"), dict)
            else tech.get("atr", 0)
        )
        market = state.get("market_data", {})
        price = market.get("current_price", 1)

        if isinstance(vix, (int, float)) and vix > 30:
            return "high_volatility"

        if (
            isinstance(atr, (int, float))
            and isinstance(price, (int, float))
            and price > 0
        ):
            atr_pct = (atr / price) * 100
            if atr_pct > 3:
                return "high_volatility"

        if isinstance(vix, (int, float)) and vix < 15:
            return "low_volatility"

        return "normal"

    def _build_context_text(self, state: dict[str, Any]) -> str:
        """Piyasa durumunu gömülmeye hazır zengin bir metne dönüştürür."""
        market = state.get("market_data", {})
        news = state.get("news_data", [])
        tech = state.get("technical_signals", {})
        sentiment = state.get("sentiment", {})
        decision = state.get("trade_decision", {})

        price = market.get("current_price", 0)
        vix = tech.get("vix", 0)
        rsi_data = tech.get("rsi", {})
        rsi_value = rsi_data.get("value", 0) if isinstance(rsi_data, dict) else rsi_data
        rsi_signal = rsi_data.get("signal", "") if isinstance(rsi_data, dict) else ""
        macd_data = tech.get("macd", {})
        macd_line = (
            macd_data.get("macd", 0) if isinstance(macd_data, dict) else macd_data
        )
        macd_signal = macd_data.get("signal", 0) if isinstance(macd_data, dict) else 0
        macd_hist = macd_data.get("histogram", 0) if isinstance(macd_data, dict) else 0
        atr_data = tech.get("atr", {})
        atr_value = atr_data.get("value", 0) if isinstance(atr_data, dict) else atr_data
        ema20 = tech.get("ema20", 0)
        ema50 = tech.get("ema50", 0)
        sma200 = tech.get("sma200", 0)
        bb_data = tech.get("bollinger_bands", {})
        bb_upper = bb_data.get("upper", 0) if isinstance(bb_data, dict) else 0
        bb_lower = bb_data.get("lower", 0) if isinstance(bb_data, dict) else 0
        bb_position = 0
        if isinstance(bb_data, dict) and bb_upper > 0 and bb_lower > 0 and price > 0:
            bb_position = (price - bb_lower) / (bb_upper - bb_lower)
        volume_ratio = market.get("volume_ratio", 1.0)
        market_regime = self._determine_market_regime(state)

        sentiment_score = sentiment.get("sentiment_score", 0)
        sentiment_confidence = sentiment.get("confidence", 0)
        sentiment_signal = sentiment.get("signal", "neutral")

        news_titles = " | ".join(n.get("title", "") for n in news[:3])

        action = decision.get("action", "hold")
        confidence = decision.get("confidence", 0)

        context_parts = [
            f"Symbol: {state.get('symbol', 'UNKNOWN')}",
            f"Price: {price}",
            f"VIX: {vix}",
            f"Market Regime: {market_regime}",
            f"RSI: {rsi_value} ({rsi_signal})",
            f"MACD: line={macd_line}, signal={macd_signal}, hist={macd_hist}",
            f"ATR: {atr_value}",
            f"EMA20: {ema20}, EMA50: {ema50}, SMA200: {sma200}",
            f"BB Position: {bb_position:.2f} (upper={bb_upper}, lower={bb_lower})",
            f"Volume Ratio: {volume_ratio}",
            f"Sentiment: {sentiment_signal} (score={sentiment_score}, confidence={sentiment_confidence})",
            f"Decision: {action} (confidence={confidence})",
            f"News: {news_titles}",
        ]
        return " | ".join(context_parts)

    def store_decision(self, state: dict[str, Any], accuracy_score: float = 0.0):
        """Ajanın verdiği kararı ve o anki durumu kaydeder."""
        if not self.collection:
            return

        symbol = state.get("symbol", "UNKNOWN")
        decision = state.get("trade_decision", {})
        action = decision.get("action", "hold")

        doc_text = self._build_context_text(state)
        tags = self._generate_semantic_tags(state)
        market_regime = self._determine_market_regime(state)

        metadata: dict[str, Any] = {
            "symbol": symbol,
            "action": action,
            "accuracy": float(accuracy_score),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_regime": market_regime,
            "tags": ",".join(tags),
        }

        doc_id = f"{symbol}_{datetime.now(timezone.utc).timestamp()}"

        try:
            self.collection.add(
                documents=[doc_text], metadatas=[metadata], ids=[doc_id]
            )
            logger.debug("Karar hafızaya işlendi: %s", doc_id)
        except Exception as e:
            logger.error("Vektör db kayıt hatası: %s", e)

    def query_similar_conditions(
        self,
        state: dict[str, Any] | None = None,
        n_results: int = 3,
        symbols: list[str] | None = None,
        query_text: str | None = None,
    ) -> list[dict]:
        """Şu anki piyasa durumuna en çok benzeyen geçmiş durumları sorgular."""
        if not self.collection:
            return []

        if query_text is None and state is not None:
            query_text = self._build_context_text(state)
        elif query_text is None:
            return []

        if state is not None and symbols is None:
            symbols = [state.get("symbol", "UNKNOWN")]

        try:
            where_clause: dict[str, Any] | None = None
            if symbols is not None:
                if len(symbols) == 1:
                    where_clause = {"symbol": symbols[0]}
                else:
                    where_clause = {"symbol": {"$in": symbols}}

            query_params: dict[str, Any] = {
                "query_texts": [query_text],
                "n_results": n_results,
            }
            if where_clause is not None:
                query_params["where"] = where_clause

            results = self.collection.query(**query_params)

            history = []
            if results and results.get("metadatas") and len(results["metadatas"]) > 0:
                for i, meta in enumerate(results["metadatas"][0]):
                    doc = results["documents"][0][i]
                    dist = results.get("distances", [[]])
                    distance = (
                        dist[0][i]
                        if dist and len(dist) > 0 and len(dist[0]) > i
                        else None
                    )
                    tags_str = meta.get("tags", "")
                    history.append(
                        {
                            "past_action": meta.get("action"),
                            "past_accuracy": meta.get("accuracy"),
                            "market_context": doc[:500],
                            "market_regime": meta.get("market_regime", "unknown"),
                            "tags": tags_str.split(",") if tags_str else [],
                            "similarity_score": 1.0 - distance
                            if distance is not None
                            else None,
                        }
                    )
            return history
        except Exception as e:
            logger.error("Vektör sorgu hatası: %s", e)
            return []

    def prune_entries_older_than(self, days: int = 30) -> int:
        """Belirtilen günden eski kayıtları temizler."""
        if not self.collection:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        try:
            all_entries = self.collection.get(include=["metadatas"])
            if not all_entries or not all_entries.get("ids"):
                return 0

            ids_to_delete = []
            for i, meta in enumerate(all_entries.get("metadatas", [])):
                entry_ts = meta.get("timestamp", "")
                if entry_ts and entry_ts < cutoff:
                    ids_to_delete.append(all_entries["ids"][i])

            if ids_to_delete:
                self.collection.delete(ids=ids_to_delete)
                logger.info(
                    "Eski kayıtlar temizlendi: %d adet (%d günden eski)",
                    len(ids_to_delete),
                    days,
                )

            return len(ids_to_delete)
        except Exception as e:
            logger.error("Prune hatası: %s", e)
            return 0

    def query_lessons(
        self, symbol: str | None = None, n_results: int = 5
    ) -> list[dict]:
        """Retrospektif analiz derslerini sorgular."""
        if not self.collection:
            return []

        try:
            where_clause: dict[str, Any] | None = None
            if symbol:
                where_clause = {"symbol": symbol}

            query_params: dict[str, Any] = {
                "query_texts": ["lesson learned losing trade mistake"],
                "n_results": n_results,
            }
            if where_clause is not None:
                query_params["where"] = where_clause

            results = self.collection.query(**query_params)

            lessons = []
            if results and results.get("metadatas") and len(results["metadatas"]) > 0:
                for i, meta in enumerate(results["metadatas"][0]):
                    doc = results["documents"][0][i]
                    lessons.append(
                        {
                            "root_cause": meta.get("root_cause_category", ""),
                            "lesson_learned": doc[:300],
                            "category": meta.get("root_cause_category", "unknown"),
                            "accuracy": meta.get("accuracy", 0.0),
                            "market_regime": meta.get("market_regime", "unknown"),
                            "timestamp": meta.get("timestamp", ""),
                        }
                    )
            return lessons
        except Exception as e:
            logger.error("Lessons query hatası: %s", e)
            return []

    def update_accuracy(self, symbol: str, timestamp: str, new_accuracy: float) -> bool:
        """Belirtilen kaydın accuracy skorunu günceller."""
        if not self.collection:
            return False

        try:
            doc_id = f"{symbol}_{timestamp}"
            existing = self.collection.get(ids=[doc_id], include=["metadatas"])
            if not existing or not existing.get("ids"):
                logger.warning("Accuracy güncellenemedi, kayıt bulunamadı: %s", doc_id)
                return False

            current_meta = existing["metadatas"][0]
            current_meta["accuracy"] = float(new_accuracy)

            self.collection.update(
                ids=[doc_id],
                metadatas=[current_meta],
            )
            logger.debug("Accuracy güncellendi: %s → %.2f", doc_id, new_accuracy)
            return True
        except Exception as e:
            logger.error("Accuracy güncelleme hatası: %s", e)
            return False
    
    def close(self) -> None:
        """ChromaDB bağlantısını kapat."""
        if self._client:
            try:
                self._client.close()
                logger.info("ChromaDB connection closed")
            except Exception as e:
                logger.warning("ChromaDB close error: %s", e)
            finally:
                self._client = None
                self._collection = None
