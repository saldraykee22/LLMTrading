"""
Emir Defteri Analiz Modülü
===========================
CCXT üzerinden emir defteri derinliğini analiz eder.
- Gerçek slippage hesaplama
- Likidite skoru
- Etkin fiyat tahmini
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import ccxt

from config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SlippageResult:
    """Slippage analiz sonucu."""

    symbol: str
    side: str  # buy | sell
    requested_amount: float
    expected_price: float
    effective_price: float
    slippage_pct: float
    liquidity_score: float
    bid_depth: float
    ask_depth: float
    order_book_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Dict'e dönüştürür (LLM'e gönderim için)."""
        return {
            "symbol": self.symbol,
            "side": self.side,
            "requested_amount": round(self.requested_amount, 6),
            "expected_price": round(self.expected_price, 4),
            "effective_price": round(self.effective_price, 4),
            "slippage_pct": round(self.slippage_pct, 4),
            "liquidity_score": round(self.liquidity_score, 3),
            "bid_depth": round(self.bid_depth, 4),
            "ask_depth": round(self.ask_depth, 4),
        }


class OrderBookAnalyzer:
    """Emir defteri derinliği ve slippage analiz motoru."""

    def __init__(self, symbol: str, depth: int = 20) -> None:
        self.symbol = symbol
        self.depth = depth
        self._settings = get_settings()
        self._exchange: ccxt.Exchange | None = None
        self._order_book: dict[str, Any] | None = None

    def _get_exchange(self) -> ccxt.Exchange:
        """Binance public exchange bağlantısını sağlar."""
        if self._exchange is None:
            config: dict = {
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
            self._exchange = ccxt.binance(config)
            logger.info("OrderBookAnalyzer: Binance public connection established")
        return self._exchange

    def fetch_order_book(
        self, symbol: str | None = None, depth: int | None = None
    ) -> dict[str, Any] | None:
        """
        CCXT üzerinden emir defterini çeker.

        Args:
            symbol: Ticaret çifti (ör. BTC/USDT). None ise constructor'daki kullanılır.
            depth: Her taraftan kaç seviye alınacağı.

        Returns:
            CCXT order book dict veya hata durumunda None.
        """
        target_symbol = symbol or self.symbol
        target_depth = depth or self.depth

        try:
            exchange = self._get_exchange()
            order_book = exchange.fetch_order_book(target_symbol, limit=target_depth)
            self._order_book = order_book
            logger.info(
                "Emir defteri çekildi: %s — %d bid, %d ask",
                target_symbol,
                len(order_book.get("bids", [])),
                len(order_book.get("asks", [])),
            )
            return order_book
        except ccxt.BaseError as e:
            logger.error("Emir defteri çekme hatası (%s): %s", target_symbol, e)
            return None

    def calculate_slippage(
        self, amount: float, side: str = "buy", order_book: dict[str, Any] | None = None
    ) -> SlippageResult:
        """
        Belirtilen miktar için etkin slippage'i hesaplar.

        Args:
            amount: Emir miktarı (base asset).
            side: 'buy' veya 'sell'.
            order_book: Önceden çekilmiş emir defteri. None ise fetch_order_book çağrılır.

        Returns:
            SlippageResult: Slippage ve likidite bilgileri.
        """
        ob = order_book or self.fetch_order_book()

        if ob is None:
            logger.warning("Emir defteri mevcut değil, varsayılan slippage dönülüyor")
            return SlippageResult(
                symbol=self.symbol,
                side=side,
                requested_amount=amount,
                expected_price=0.0,
                effective_price=0.0,
                slippage_pct=0.0,
                liquidity_score=0.0,
                bid_depth=0.0,
                ask_depth=0.0,
            )

        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        if not bids and not asks:
            logger.warning("Emir defteri boş: %s", self.symbol)
            return SlippageResult(
                symbol=self.symbol,
                side=side,
                requested_amount=amount,
                expected_price=0.0,
                effective_price=0.0,
                slippage_pct=0.0,
                liquidity_score=0.0,
                bid_depth=0.0,
                ask_depth=0.0,
            )

        bid_depth = sum(b[1] for b in bids) if bids else 0.0
        ask_depth = sum(a[1] for a in asks) if asks else 0.0

        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0

        if best_bid > 0 and best_ask > 0:
            mid_price = (best_bid + best_ask) / 2.0
        elif best_ask > 0:
            mid_price = best_ask
        elif best_bid > 0:
            mid_price = best_bid
        else:
            mid_price = 0.0

        effective_price = self._get_effective_price_from_ob(amount, side, bids, asks)

        if mid_price > 0:
            slippage_pct = (effective_price - mid_price) / mid_price
        else:
            slippage_pct = 0.0

        liquidity_score = self._calculate_liquidity_score(bids, asks, amount, side)

        snapshot = {
            "best_bid": round(best_bid, 4),
            "best_ask": round(best_ask, 4),
            "spread_pct": round((best_ask - best_bid) / best_ask, 4)
            if best_ask > 0
            else 0.0,
            "bid_levels": len(bids),
            "ask_levels": len(asks),
        }

        result = SlippageResult(
            symbol=self.symbol,
            side=side,
            requested_amount=amount,
            expected_price=mid_price,
            effective_price=effective_price,
            slippage_pct=slippage_pct,
            liquidity_score=liquidity_score,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            order_book_snapshot=snapshot,
        )

        logger.info(
            "Slippage: %s %s %.6f — mid: %.4f, effective: %.4f, slippage: %.4f%%, likidite: %.3f",
            self.symbol,
            side,
            amount,
            mid_price,
            effective_price,
            slippage_pct * 100,
            liquidity_score,
        )
        return result

    def get_liquidity_score(self, order_book: dict[str, Any] | None = None) -> float:
        """
        Emir defteri likiditesini 0-1 arası skorlar.

        Args:
            order_book: Önceden çekilmiş emir defteri.

        Returns:
            float: 0 (çok düşük likidite) ile 1 (yüksek likidite) arasında skor.
        """
        ob = order_book or self._order_book
        if ob is None:
            ob = self.fetch_order_book()
        if ob is None:
            return 0.0

        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        if not bids or not asks:
            return 0.0

        bid_depth = sum(b[1] for b in bids)
        ask_depth = sum(a[1] for a in asks)
        total_depth = bid_depth + ask_depth

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        spread_pct = (best_ask - best_bid) / best_ask if best_ask > 0 else 1.0

        depth_score = min(total_depth / 100.0, 1.0)

        if spread_pct <= 0.0001:
            spread_score = 1.0
        elif spread_pct <= 0.001:
            spread_score = 0.8
        elif spread_pct <= 0.005:
            spread_score = 0.6
        elif spread_pct <= 0.01:
            spread_score = 0.4
        elif spread_pct <= 0.05:
            spread_score = 0.2
        else:
            spread_score = 0.0

        level_count = len(bids) + len(asks)
        level_score = min(level_count / 40.0, 1.0)

        score = (depth_score * 0.5) + (spread_score * 0.3) + (level_score * 0.2)
        return round(min(max(score, 0.0), 1.0), 3)

    def get_effective_price(
        self, amount: float, side: str = "buy", order_book: dict[str, Any] | None = None
    ) -> float:
        """
        Emir defteri derinliğini dikkate alarak tahmini dolum fiyatını döndürür.

        Args:
            amount: Emir miktarı.
            side: 'buy' veya 'sell'.
            order_book: Önceden çekilmiş emir defteri.

        Returns:
            float: Tahmini ortalama dolum fiyatı.
        """
        ob = order_book or self._order_book
        if ob is None:
            ob = self.fetch_order_book()
        if ob is None:
            return 0.0

        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        return self._get_effective_price_from_ob(amount, side, bids, asks)

    def _get_effective_price_from_ob(
        self,
        amount: float,
        side: str,
        bids: list[list],
        asks: list[list],
    ) -> float:
        """
        Emir defteri seviyelerini gezerek ağırlıklı ortalama dolum fiyatını hesaplar.

        Buy: ask seviyelerini yukarı doğru tarar.
        Sell: bid seviyelerini aşağı doğru tarar.
        """
        remaining = amount
        total_cost = 0.0

        if side == "buy":
            levels = asks
        else:
            levels = bids

        for level in levels:
            if remaining <= 0:
                break
            price = level[0]
            vol = level[1]
            fill_qty = min(remaining, vol)
            total_cost += fill_qty * price
            remaining -= fill_qty

        if remaining > 0 and levels:
            last_price = levels[-1][0]
            total_cost += remaining * last_price
            logger.warning(
                "Emir defteri yetersiz: %s %s %.6f, %.6f karşılanamadı",
                self.symbol,
                side,
                amount,
                remaining,
            )

        filled = amount - max(remaining, 0)
        if filled > 0:
            return total_cost / filled

        return levels[0][0] if levels else 0.0

    def _calculate_liquidity_score(
        self,
        bids: list[list],
        asks: list[list],
        amount: float,
        side: str,
    ) -> float:
        """
        Belirli bir emir büyüklüğüne göre likidite skoru hesaplar.

        Skor, emrin emir defterindeki toplam derinliğe oranına dayanır.
        """
        if side == "buy":
            relevant_depth = sum(a[1] for a in asks)
        else:
            relevant_depth = sum(b[1] for b in bids)

        if relevant_depth <= 0:
            return 0.0

        fill_ratio = amount / relevant_depth

        if fill_ratio <= 0.01:
            score = 1.0
        elif fill_ratio <= 0.1:
            score = 0.9
        elif fill_ratio <= 0.25:
            score = 0.75
        elif fill_ratio <= 0.5:
            score = 0.5
        elif fill_ratio <= 0.75:
            score = 0.3
        elif fill_ratio <= 1.0:
            score = 0.15
        else:
            score = max(0.0, 0.1 - (fill_ratio - 1.0) * 0.1)

        return round(min(max(score, 0.0), 1.0), 3)
