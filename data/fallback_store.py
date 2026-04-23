"""
Fallback Audit Log Store
=========================
LLM fallback kullanımlarını audit log olarak saklar.
Retrospektif analiz ve debugging için kullanılır.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

FALLBACK_LOG_FILE = DATA_DIR / "fallback_audit.jsonl"
_fallback_lock = threading.Lock()


class FallbackStore:
    """Fallback kullanımlarını saklayan audit store."""

    def __init__(self) -> None:
        self._log_file = FALLBACK_LOG_FILE
        self._log_file.parent.mkdir(parents=True, exist_ok=True)

    def log_fallback(
        self,
        agent: str,
        reason: str,
        fallback_value: dict[str, Any] | None = None,
        symbol: str | None = None,
        cycle: int | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Fallback kullanımını logla.

        Args:
            agent: Fallback kullanan ajan (sentiment, risk_manager, trader, vb.)
            reason: Fallback nedeni (API error, timeout, JSON parse error, vb.)
            fallback_value: Döndürülen fallback değeri
            symbol: İşlem yapılan sembol
            cycle: Analiz cycle'ı
            extra_data: Ek meta veriler
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "reason": reason,
            "fallback_value": fallback_value,
            "symbol": symbol,
            "cycle": cycle,
            "extra_data": extra_data or {},
        }

        with _fallback_lock:
            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                logger.debug("Fallback audit log kaydedildi: %s → %s", agent, reason)
            except Exception as e:
                logger.error("Fallback audit log yazma hatası: %s", e)

    def get_fallbacks(
        self,
        agent: str | None = None,
        symbol: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Fallback kayıtlarını oku.

        Args:
            agent: Filtre (opsiyonel)
            symbol: Filtre (opsiyonel)
            since: Başlangıç zamanı (opsiyonel)
            limit: Maksimum kayıt sayısı

        Returns:
            Fallback kayıtları listesi
        """
        if not self._log_file.exists():
            return []

        results = []
        cutoff = since.isoformat() if since else None

        try:
            with open(self._log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)

                        # Filtreler
                        if agent and record.get("agent") != agent:
                            continue
                        if symbol and record.get("symbol") != symbol:
                            continue
                        if cutoff and record.get("timestamp", "") < cutoff:
                            continue

                        results.append(record)

                        if len(results) >= limit:
                            break

                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error("Fallback audit log okuma hatası: %s", e)

        # En yeniden eskiye sırala
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results

    def get_fallback_count(
        self,
        agent: str | None = None,
        since: datetime | None = None,
    ) -> int:
        """Fallback sayısını döndür."""
        return len(self.get_fallbacks(agent=agent, since=since, limit=10000))

    def get_fallback_summary(
        self,
        hours: int = 24,
    ) -> dict[str, Any]:
        """
        Son N saatteki fallback özetini döndür.

        Args:
            hours: Son kaç saat

        Returns:
            Özet istatistikler
        """
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        fallbacks = self.get_fallbacks(since=since, limit=10000)

        if not fallbacks:
            return {
                "total_fallbacks": 0,
                "by_agent": {},
                "by_reason": {},
                "most_affected_symbols": [],
            }

        # Ajan bazlı sayım
        by_agent: dict[str, int] = {}
        by_reason: dict[str, int] = {}
        symbol_counts: dict[str, int] = {}

        for fb in fallbacks:
            agent = fb.get("agent", "unknown")
            reason = fb.get("reason", "unknown")
            symbol = fb.get("symbol", "unknown")

            by_agent[agent] = by_agent.get(agent, 0) + 1
            by_reason[reason] = by_reason.get(reason, 0) + 1
            if symbol:
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

        # En çok etkilenen semboller
        sorted_symbols = sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)
        most_affected = [{"symbol": s, "count": c} for s, c in sorted_symbols[:10]]

        return {
            "total_fallbacks": len(fallbacks),
            "by_agent": by_agent,
            "by_reason": by_reason,
            "most_affected_symbols": most_affected,
            "time_range": f"Son {hours} saat",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def clear_old_logs(self, days: int = 7) -> int:
        """
        Eski logları temizle.

        Args:
            days: Kaç günden eski kayıtlar silinecek

        Returns:
            Silinen kayıt sayısı
        """
        if not self._log_file.exists():
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Yeni dosyaya sadece güncel kayıtları yaz
        temp_file = self._log_file.with_suffix(".tmp")
        kept_count = 0
        deleted_count = 0

        try:
            with open(self._log_file, "r", encoding="utf-8") as f_in:
                with open(temp_file, "w", encoding="utf-8") as f_out:
                    for line in f_in:
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            record = json.loads(line)
                            if record.get("timestamp", "") >= cutoff:
                                f_out.write(line + "\n")
                                kept_count += 1
                            else:
                                deleted_count += 1
                        except json.JSONDecodeError:
                            deleted_count += 1

            # Atomic rename with retry
            for attempt in range(3):
                try:
                    temp_file.replace(self._log_file)
                    break
                except (PermissionError, OSError) as e:
                    if attempt == 2:
                        logger.error("Fallback log temizleme başarısız: %s", e)
                        return 0
                    time.sleep(0.1 * (attempt + 1))
            
            logger.info(
                "Eski fallback logları temizlendi: %d silindi, %d kaydedildi",
                deleted_count,
                kept_count,
            )
            return deleted_count

        except Exception as e:
            logger.error("Fallback log temizleme hatası: %s", e)
            return 0
        finally:
            # Cleanup temp file if exists
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass


# Singleton instance
_fallback_store_instance: FallbackStore | None = None
_store_lock = threading.Lock()


def get_fallback_store() -> FallbackStore:
    """Singleton FallbackStore instance al."""
    global _fallback_store_instance
    if _fallback_store_instance is None:
        with _store_lock:
            if _fallback_store_instance is None:
                _fallback_store_instance = FallbackStore()
    return _fallback_store_instance


