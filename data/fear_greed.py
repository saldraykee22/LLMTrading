"""
Crypto Fear & Greed Index Client
=================================
Alternative.me API'den Kripto Korku ve Açgözlülük Endeksi çeker.
Ücretsiz API: https://alternative.me/crypto/fear-and-greed-index/
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.alternative.me/fng/"
API_TIMEOUT = 10  # saniye


class FearGreedClient:
    """Crypto Fear & Greed Index API client."""
    
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "LLMTrading-Bot/1.0",
            "Accept": "application/json",
        })
        self._last_value: int | None = None
        self._last_classification: str | None = None
        self._last_update: datetime | None = None
        self._cache_ttl_seconds = 3600  # 1 saat cache
    
    def fetch(self) -> dict[str, Any]:
        """
        Fear & Greed Index verisini çek.
        
        Returns:
            {
                "value": int,  # 0-100
                "value_classification": str,  # extreme_fear, fear, neutral, greed, extreme_greed
                "timestamp": str,  # YYYY-MM-DD
                "time_until_update": str  # HH:MM:SS
            }
        """
        try:
            response = self._session.get(API_URL, timeout=API_TIMEOUT)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("status") != "success":
                logger.warning("Fear & Greed API başarısız: %s", data.get("status"))
                return self._get_default()
            
            if "data" not in data or not data["data"]:
                logger.warning("Fear & Greed API boş veri döndürdü")
                return self._get_default()
            
            latest = data["data"][0]
            
            # Parse
            value = int(latest.get("value", 50))
            classification = latest.get("value_classification", "neutral")
            timestamp = latest.get("timestamp", "")
            time_until = latest.get("time_until_update", "00:00:00")
            
            result = {
                "value": value,
                "classification": classification,
                "timestamp": timestamp,
                "time_until_update": time_until,
            }
            
            # Cache
            self._last_value = value
            self._last_classification = classification
            self._last_update = datetime.now(timezone.utc)
            
            logger.info(
                "Fear & Greed Index: %d (%s)",
                value,
                classification,
            )
            
            return result
            
        except requests.Timeout:
            logger.error("Fear & Greed API timeout")
            return self._get_default()
        except requests.RequestException as e:
            logger.error("Fear & Greed API hatası: %s", e)
            return self._get_default()
        except (KeyError, ValueError, TypeError) as e:
            logger.error("Fear & Greed parse hatası: %s", e)
            return self._get_default()
    
    def _get_default(self) -> dict[str, Any]:
        """Varsayılan/backup değer."""
        return {
            "value": 50,
            "classification": "neutral",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "time_until_update": "N/A",
        }
    
    def get_cached_value(self) -> int | None:
        """Cache'lenmiş son değeri döndür."""
        if self._last_value is None:
            return None
        
        # Cache süresi dolmuşsa None
        if self._last_update:
            elapsed = (datetime.now(timezone.utc) - self._last_update).total_seconds()
            if elapsed > self._cache_ttl_seconds:
                logger.warning("Fear & Greed cache süresi doldu")
                return None
        
        return self._last_value
    
    def get_cached_classification(self) -> str | None:
        """Cache'lenmiş sınıflandırmayı döndür."""
        return self._last_classification
    
    def close(self) -> None:
        """Session kapat."""
        self._session.close()


def fetch_fear_greed_index() -> int:
    """
    Convenience function: Fear & Greed Index değerini çek.
    
    Returns:
        0-100 arası integer
    """
    client = FearGreedClient()
    try:
        result = client.fetch()
        return result["value"]
    finally:
        client.close()


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    
    print("Crypto Fear & Greed Index Test")
    print("=" * 50)
    
    client = FearGreedClient()
    result = client.fetch()
    
    print(f"Değer: {result['value']}")
    print(f"Sınıflandırma: {result['classification']}")
    print(f"Tarih: {result['timestamp']}")
    print(f"Güncelleme: {result['time_until_update']}")
    
    client.close()
