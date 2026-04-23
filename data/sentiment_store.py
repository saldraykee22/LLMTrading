"""
Duyarlılık Deposu Modülü
=========================
LLM tarafından üretilen duyarlılık skorlarını saklar ve sorgular.
Backtest için önceden hesaplanmış skorları diske yazar.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

STORE_DIR = DATA_DIR / "sentiment_cache"


@dataclass
class SentimentRecord:
    """Tek bir duyarlılık analizi kaydı."""

    symbol: str
    timestamp: str  # ISO format
    sentiment_score: float  # -1.0 → 1.0
    confidence: float  # 0.0 → 1.0
    risk_score: float  # 0.0 → 1.0
    signal: str  # bullish | bearish | neutral
    reasoning: str = ""
    key_factors: list[str] = field(default_factory=list)
    news_count: int = 0
    model_used: str = ""
    provider: str = ""
    price: float = 0.0


class SentimentStore:
    """JSON tabanlı duyarlılık deposu — RAM cache ile optimize edilmiş."""

    MAX_CACHE_PER_SYMBOL = 500
    MAX_SYMBOLS_IN_CACHE = 100

    def __init__(self, store_dir: Path | None = None) -> None:
        self._dir = store_dir or STORE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        from collections import OrderedDict
        self._cache: OrderedDict[str, list[SentimentRecord]] = OrderedDict()

    def _file_path(self, symbol: str) -> Path:
        """Sembol için depo dosya yolu."""
        from data.symbol_resolver import validate_symbol
        clean = symbol.upper()
        if not validate_symbol(clean):
            clean = clean.replace("/", "_").replace(".", "_").replace("\\", "_")
            clean = clean.replace("..", "_")
        else:
            # Valid symbols like BTC/USDT still contain '/' which is invalid in filenames
            clean = clean.replace("/", "_")
        return self._dir / f"{clean}_sentiment.jsonl"

    def _update_lru(self, symbol: str) -> None:
        """LRU mantığı için sembolü en sona taşır."""
        if symbol in self._cache:
            self._cache.move_to_end(symbol)

    def _evict_lru(self) -> None:
        """Kapasite aşıldıysa en eski sembolü cache'den siler."""
        while len(self._cache) > self.MAX_SYMBOLS_IN_CACHE:
            self._cache.popitem(last=False)

    def save(
        self, record: SentimentRecord, min_interval_minutes: int | None = None
    ) -> bool:
        """
        Yeni kaydı dosyaya ekler (append) + RAM cache günceller.
        Thread-safe: Lock ile korunmuştur.
        """
        from config.settings import get_trading_params

        if min_interval_minutes is None:
            min_interval_minutes = get_trading_params().limits.sentiment_cache_minutes

        with self._lock:
            # Duplicate kontrolü — RAM cache'den (hızlı)
            cached = self._cache.get(record.symbol)
            if cached:
                latest = cached[-1]
                last_time = datetime.fromisoformat(latest.timestamp)
                now = datetime.now(timezone.utc)
                if (now - last_time).total_seconds() < min_interval_minutes * 60:
                    logger.debug(
                        "Sentiment çok yakın, atlanıyor (%s, son: %s)",
                        record.symbol,
                        latest.timestamp,
                    )
                    self._update_lru(record.symbol)
                    return False

            path = self._file_path(record.symbol)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

            # RAM cache güncelle
            if record.symbol not in self._cache:
                self._cache[record.symbol] = []
            self._cache[record.symbol].append(record)

            # RAM cache boyut limiti
            if len(self._cache[record.symbol]) > self.MAX_CACHE_PER_SYMBOL:
                self._cache[record.symbol] = self._cache[record.symbol][
                    -self.MAX_CACHE_PER_SYMBOL // 2 :
                ]
            
            self._update_lru(record.symbol)
            self._evict_lru()

            logger.debug(
                "Sentiment kaydedildi: %s → %.2f", record.symbol, record.sentiment_score
            )
            return True

    def load(
        self,
        symbol: str,
        last_n: int | None = None,
    ) -> list[SentimentRecord]:
        """Sembol için kayıtları yükler — RAM cache öncelikli."""
        with self._lock:
            # RAM cache'den kontrol
            if symbol in self._cache:
                self._update_lru(symbol)
                records = self._cache[symbol]
                if last_n:
                    return records[-last_n:]
                return records

            # Diskten yükle ve cache'e al
            path = self._file_path(symbol)
            if not path.exists():
                return []

            records: list[SentimentRecord] = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        records.append(SentimentRecord(**data))
                    except (json.JSONDecodeError, TypeError):
                        continue

            # Cache'e al
            self._cache[symbol] = records
            self._update_lru(symbol)
            self._evict_lru()

            if last_n:
                return records[-last_n:]

            return records

    def get_latest(self, symbol: str) -> SentimentRecord | None:
        """En son duyarlılık kaydını döndürür — RAM cache'den (O(1))."""
        records = self.load(symbol, last_n=1)
        return records[0] if records else None

    def get_average_score(self, symbol: str, last_n: int = 5) -> float:
        """Son N kaydın ortalama duyarlılık skorunu döndürür — RAM cache'den."""
        records = self.load(symbol, last_n=last_n)
        if not records:
            return 0.0
        return sum(r.sentiment_score for r in records) / len(records)

    def clear(self, symbol: str) -> None:
        """Sembol için tüm kayıtları siler + RAM cache temizler."""
        path = self._file_path(symbol)
        if path.exists():
            path.unlink()
        self._cache.pop(symbol, None)
        logger.info("Sentiment temizlendi: %s", symbol)

    def reload_cache(self, symbol: str) -> list[SentimentRecord]:
        """RAM cache'i diskten yeniden yükler (program restart sonrası)."""
        path = self._file_path(symbol)
        if not path.exists():
            self._cache.pop(symbol, None)
            return []

        records: list[SentimentRecord] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    records.append(SentimentRecord(**data))
                except (json.JSONDecodeError, TypeError):
                    continue

        self._cache[symbol] = records
        return records
