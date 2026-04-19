"""
LLM Backtest Cache System
==========================
Persistent cache for LLM backtest results.
First run calls LLM API, subsequent runs load from cache.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)


@dataclass
class BacktestCacheEntry:
    """Cache entry storing LLM analysis results."""
    
    symbol: str
    timestamp: str  # ISO format
    timeframe: str
    decision: dict[str, Any]
    sentiment: dict[str, Any]
    debate_result: dict[str, Any]
    risk_assessment: dict[str, Any]
    market_data_hash: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    @classmethod
    def from_result(cls, symbol: str, timestamp: datetime, timeframe: str, result: dict) -> "BacktestCacheEntry":
        """Create cache entry from LangGraph result."""
        return cls(
            symbol=symbol,
            timestamp=timestamp.isoformat(),
            timeframe=timeframe,
            decision=result.get("trade_decision", {}),
            sentiment=result.get("sentiment", {}),
            debate_result=result.get("debate_result", {}),
            risk_assessment=result.get("risk_assessment", {}),
            market_data_hash="",  # Can be computed from market_data if needed
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BacktestCacheEntry":
        """Create from dictionary."""
        return cls(**data)


class BacktestCache:
    """
    Persistent cache for backtest results.
    
    Features:
    - RAM cache for fast access
    - Disk persistence for restart survival
    - Symbol-based file organization
    - Automatic cleanup
    """
    
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or (DATA_DIR / "backtest_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, BacktestCacheEntry] = {}
        logger.info(f"BacktestCache initialized: {self.cache_dir}")
    
    def _make_key(self, symbol: str, timestamp: datetime, timeframe: str) -> str:
        """Create cache key from parameters."""
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        return f"{symbol}_{timestamp.strftime('%Y%m%d_%H%M')}_{timeframe}"
    
    def _file_path(self, key: str) -> Path:
        """Get file path for cache key."""
        # Sanitize key to avoid directory issues with symbols like BTC/USDT
        safe_key = key.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{safe_key}.json"
    
    def get(
        self,
        symbol: str,
        timestamp: datetime,
        timeframe: str,
    ) -> BacktestCacheEntry | None:
        """
        Get cache entry - RAM priority.
        
        Args:
            symbol: Trading symbol (e.g., BTC/USDT)
            timestamp: Bar timestamp
            timeframe: Candle timeframe
        
        Returns:
            Cache entry or None if not found
        """
        key = self._make_key(symbol, timestamp, timeframe)
        
        # RAM cache check
        if key in self._memory_cache:
            logger.debug(f"RAM cache hit: {key}")
            return self._memory_cache[key]
        
        # Disk cache check
        file_path = self._file_path(key)
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                entry = BacktestCacheEntry.from_dict(data)
                self._memory_cache[key] = entry
                logger.debug(f"Disk cache hit: {key}")
                return entry
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"Cache file corrupted ({key}): {e}")
                file_path.unlink(missing_ok=True)
        
        logger.debug(f"Cache miss: {key}")
        return None
    
    def save(self, entry: BacktestCacheEntry) -> None:
        """
        Save cache entry - RAM + disk.
        
        Args:
            entry: Cache entry to save
        """
        key = self._make_key(entry.symbol, entry.timestamp, entry.timeframe)
        file_path = self._file_path(key)
        
        # RAM cache
        self._memory_cache[key] = entry
        
        # Disk cache
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2, default=str)
            logger.debug(f"Cache saved: {key}")
        except Exception as e:
            logger.error(f"Failed to save cache ({key}): {e}")
    
    def contains(self, symbol: str, timestamp: datetime, timeframe: str) -> bool:
        """Check if cache has entry."""
        return self.get(symbol, timestamp, timeframe) is not None
    
    def clear(self, symbol: str | None = None) -> int:
        """
        Clear cache.
        
        Args:
            symbol: If provided, only clear specific symbol
        
        Returns:
            Number of entries cleared
        """
        count = 0
        for file in self.cache_dir.glob("*.json"):
            if symbol is None or symbol in file.stem:
                file.unlink()
                count += 1
        self._memory_cache.clear()
        logger.info(f"Cleared {count} cache entries" + (f" for {symbol}" if symbol else ""))
        return count
    
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        
        # Count by symbol
        symbols: dict[str, int] = {}
        for file in files:
            parts = file.stem.split("_")
            if len(parts) >= 1:
                sym = parts[0]
                symbols[sym] = symbols.get(sym, 0) + 1
        
        return {
            "total_entries": len(files),
            "ram_entries": len(self._memory_cache),
            "disk_size_bytes": total_size,
            "disk_size_mb": round(total_size / 1024 / 1024, 2),
            "symbols": symbols,
        }
    
    def list_entries(self, symbol: str | None = None) -> list[str]:
        """List all cache entries."""
        entries = []
        for file in self.cache_dir.glob("*.json"):
            if symbol is None or symbol in file.stem:
                entries.append(file.stem)
        return sorted(entries)
