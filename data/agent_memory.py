"""
Agent Memory Store Modülü
==========================
VectorStore'u saran yüksek seviyeli işlemler sağlar.
Benzer geçmiş işlemleri sorgulama, sonuç güncelleme ve öğrenme özetleri üretme.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from data.vector_store import AgentMemoryStore

logger = logging.getLogger(__name__)


class AgentMemoryStoreWrapper:
    """VectorStore'u yüksek seviyeli işlemlerle saran sınıf."""

    def __init__(self, vector_store: AgentMemoryStore | None = None):
        self._store = vector_store or AgentMemoryStore()

    def store_trade_context(
        self,
        trade_data: dict[str, Any],
        symbol: str,
        tags: list[str] | None = None,
    ) -> str | None:
        """Tam işlem bağlamını hafızaya kaydeder."""
        if not self._store.collection:
            return None

        action = trade_data.get("action", "hold")
        confidence = trade_data.get("confidence", 0.0)
        entry_price = trade_data.get("entry_price", 0.0)
        stop_loss = trade_data.get("stop_loss", 0.0)
        take_profit = trade_data.get("take_profit", 0.0)
        regime = trade_data.get("market_regime", "unknown")
        rsi = trade_data.get("rsi", 0)
        macd_hist = trade_data.get("macd_hist", 0)
        atr = trade_data.get("atr", 0)
        volume_ratio = trade_data.get("volume_ratio", 1.0)
        sentiment_score = trade_data.get("sentiment_score", 0)
        news_summary = trade_data.get("news_summary", "")

        doc_parts = [
            f"Symbol: {symbol}",
            f"Action: {action} (confidence={confidence:.2f})",
            f"Entry: {entry_price}, SL: {stop_loss}, TP: {take_profit}",
            f"Regime: {regime}",
            f"RSI: {rsi}, MACD Hist: {macd_hist}, ATR: {atr}",
            f"Volume Ratio: {volume_ratio}",
            f"Sentiment: {sentiment_score}",
            f"News: {news_summary}",
        ]
        doc_text = " | ".join(doc_parts)

        effective_tags = tags or []
        if sentiment_score > 0.3:
            effective_tags.append("bullish_sentiment")
        elif sentiment_score < -0.3:
            effective_tags.append("bearish_sentiment")
        if regime == "high_volatility":
            effective_tags.append("high_volatility")
        elif regime == "low_volatility":
            effective_tags.append("low_volatility")
        if rsi < 30:
            effective_tags.append("oversold")
        elif rsi > 70:
            effective_tags.append("overbought")
        if not effective_tags:
            effective_tags.append("neutral")

        ts = datetime.now(timezone.utc)
        metadata: dict[str, Any] = {
            "symbol": symbol,
            "action": action,
            "accuracy": trade_data.get("accuracy", 0.0),
            "timestamp": ts.isoformat(),
            "market_regime": regime,
            "tags": ",".join(effective_tags),
            "entry_price": entry_price,
            "source": "trade_context",
        }

        doc_id = f"trade_{symbol}_{ts.timestamp()}"

        try:
            self._store.collection.add(
                documents=[doc_text],
                metadatas=[metadata],
                ids=[doc_id],
            )
            logger.debug("İşlem bağlamı kaydedildi: %s", doc_id)
            return doc_id
        except Exception as e:
            logger.error("İşlem bağlamı kayıt hatası: %s", e)
            return None

    def query_similar_trades(
        self,
        symbol: str,
        action: str | None = None,
        regime: str | None = None,
        top_k: int = 5,
        query_text: str | None = None,
    ) -> list[dict]:
        """Benzer geçmiş işlemleri bulur."""
        if not self._store.collection:
            return []

        try:
            where_clause: dict[str, Any] = {"symbol": symbol}
            if action:
                where_clause["action"] = action
            if regime:
                where_clause["market_regime"] = regime

            query_params: dict[str, Any] = {
                "n_results": top_k,
                "where": where_clause,
            }

            if query_text is not None:
                query_params["query_texts"] = [query_text]
            else:
                query_params["query_texts"] = [
                    f"Symbol: {symbol}, Action: {action or 'any'}, Regime: {regime or 'any'}"
                ]

            results = self._store.collection.query(**query_params)

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
                            "action": meta.get("action"),
                            "accuracy": meta.get("accuracy"),
                            "market_regime": meta.get("market_regime", "unknown"),
                            "entry_price": meta.get("entry_price", 0),
                            "context": doc[:500],
                            "tags": tags_str.split(",") if tags_str else [],
                            "timestamp": meta.get("timestamp", ""),
                            "similarity_score": 1.0 - distance
                            if distance is not None
                            else None,
                        }
                    )
            return history
        except Exception as e:
            logger.error("Benzer işlem sorgu hatası: %s", e)
            return []

    def update_trade_outcome(
        self,
        trade_id: str,
        actual_pnl: float,
        was_correct: bool,
    ) -> bool:
        """İşlem kapandıktan sonra accuracy skorunu günceller."""
        if not self._store.collection:
            return False

        try:
            existing = self._store.collection.get(ids=[trade_id], include=["metadatas"])
            if not existing or not existing.get("ids"):
                logger.warning("İşlem bulunamadı: %s", trade_id)
                return False

            current_meta = existing["metadatas"][0]
            old_accuracy = current_meta.get("accuracy", 0.0)

            if was_correct:
                new_accuracy = min(1.0, old_accuracy + 0.1)
            else:
                new_accuracy = max(0.0, old_accuracy - 0.1)

            current_meta["accuracy"] = new_accuracy
            current_meta["actual_pnl"] = actual_pnl
            current_meta["was_correct"] = was_correct
            current_meta["outcome_recorded"] = True

            self._store.collection.update(
                ids=[trade_id],
                metadatas=[current_meta],
            )
            logger.info(
                "İşlem sonucu güncellendi: %s → accuracy: %.2f (PnL: %.4f)",
                trade_id,
                new_accuracy,
                actual_pnl,
            )
            return True
        except Exception as e:
            logger.error("İşlem sonucu güncelleme hatası: %s", e)
            return False

    def get_learning_summary(self, symbol: str, last_n: int = 20) -> dict[str, Any]:
        """Son N işlemin performans özetini döndürür."""
        if not self._store.collection:
            return {"error": "VectorStore kullanılamıyor"}

        try:
            all_entries = self._store.collection.get(
                where={"symbol": symbol},
                include=["metadatas", "documents"],
            )

            if not all_entries or not all_entries.get("ids"):
                return {
                    "symbol": symbol,
                    "total_trades": 0,
                    "message": "No trade history found",
                }

            entries = list(
                zip(
                    all_entries["metadatas"],
                    all_entries["documents"],
                )
            )
            entries.sort(
                key=lambda x: x[0].get("timestamp", ""),
                reverse=True,
            )
            recent = entries[:last_n]

            total = len(recent)
            correct = sum(1 for m, _ in recent if m.get("accuracy", 0) >= 0.5)
            avg_accuracy = (
                sum(m.get("accuracy", 0) for m, _ in recent) / total if total > 0 else 0
            )

            action_counts: dict[str, int] = {}
            regime_counts: dict[str, int] = {}
            for m, _ in recent:
                act = m.get("action", "unknown")
                reg = m.get("market_regime", "unknown")
                action_counts[act] = action_counts.get(act, 0) + 1
                regime_counts[reg] = regime_counts.get(reg, 0) + 1

            action_accuracy: dict[str, list[float]] = {}
            for m, _ in recent:
                act = m.get("action", "unknown")
                action_accuracy.setdefault(act, []).append(m.get("accuracy", 0))

            best_action = max(
                action_accuracy.items(),
                key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
                default=("none", []),
            )

            return {
                "symbol": symbol,
                "total_trades": total,
                "correct_predictions": correct,
                "accuracy_rate": correct / total if total > 0 else 0,
                "avg_accuracy": avg_accuracy,
                "action_distribution": action_counts,
                "regime_distribution": regime_counts,
                "best_performing_action": best_action[0],
                "best_action_avg_accuracy": (
                    sum(best_action[1]) / len(best_action[1]) if best_action[1] else 0
                ),
            }
        except Exception as e:
            logger.error("Öğrenme özeti hatası: %s", e)
            return {"error": str(e)}

    def get_retrospective_lessons(
        self, symbol: str, last_n: int = 5
    ) -> list[dict[str, Any]]:
        """Retrospektif analiz derslerini döndürür."""
        if not self._store.collection:
            return []

        try:
            all_entries = self._store.collection.get(
                where={"symbol": symbol},
                include=["metadatas", "documents"],
            )

            if not all_entries or not all_entries.get("ids"):
                return []

            lessons = []
            for i, meta in enumerate(all_entries["metadatas"]):
                if meta.get("action") == "losing_trade" or "retrospective" in meta.get(
                    "tags", ""
                ):
                    lessons.append(
                        {
                            "root_cause_category": meta.get(
                                "root_cause_category", "unknown"
                            ),
                            "lesson": all_entries["documents"][i][:500],
                            "accuracy": meta.get("accuracy", 0),
                            "timestamp": meta.get("timestamp", ""),
                        }
                    )

            lessons.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return lessons[:last_n]
        except Exception as e:
            logger.error("Retrospektif ders sorgu hatası: %s", e)
            return []
