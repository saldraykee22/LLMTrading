"""
Portföy Yöneticisi Ajan (Portfolio Manager)
=============================================
Birden fazla varlığı analiz eder, skorlar ve CVaR optimizasyonu ile
optimal portföy dağılımını belirler.

Akış:
  1. Sembol havuzunu al
  2. Her sembol için run_analysis çalıştır
  3. Sonuçları skorla (sentiment, debate, risk, teknik)
  4. CVaR optimizasyonu ile ağırlıkları belirle
  5. Nihai portföy dağılımını döndür
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from agents.graph import run_analysis
from config.settings import get_settings, get_trading_params
from data.market_data import MarketDataClient
from risk.cvar_optimizer import optimize_portfolio_cvar
from utils.json_utils import extract_json

logger = logging.getLogger(__name__)


@dataclass
class SymbolAnalysis:
    """Tek bir sembolün analiz sonucu."""

    symbol: str
    sentiment_score: float = 0.0
    sentiment_confidence: float = 0.0
    debate_consensus: float = 0.0
    debate_winner: str = "draw"
    hallucinations: int = 0
    risk_approved: bool = False
    risk_warnings: int = 0
    trend: str = "neutral"
    trend_strength: float = 0.0
    rsi: float = 50.0
    composite_score: float = 0.0  # -1.0 ile 1.0 arası
    returns_series: list[float] = field(default_factory=list)
    raw_result: dict = field(default_factory=dict)

    def calculate_composite_score(self) -> float:
        """
        Bileşik skor hesaplar:
          - Debate consensus: %35
          - Sentiment score: %25
          - Trend strength: %20
          - RSI ters (30-70 arası ideal): %20
        """
        debate_component = self.debate_consensus * 0.35
        sentiment_component = self.sentiment_score * 0.25
        trend_component = self.trend_strength * 0.20

        rsi_normalized = 0.0
        if self.rsi < 30:
            rsi_normalized = 0.5
        elif self.rsi > 70:
            rsi_normalized = -0.5
        else:
            rsi_normalized = (self.rsi - 50) / 40  # -0.5 ile 0.5 arası
        rsi_component = rsi_normalized * 0.20

        # Güven ağırlığı: düşük güven = skoru düşür
        confidence_factor = (self.sentiment_confidence + 0.5) / 1.5

        self.composite_score = (
            debate_component + sentiment_component + trend_component + rsi_component
        ) * confidence_factor
        self.composite_score = max(-1.0, min(1.0, self.composite_score))
        return self.composite_score


class PortfolioManager:
    """
    Çoklu varlık portföy yöneticisi.

    Kullanım:
        pm = PortfolioManager(symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        result = pm.build_portfolio()
    """

    def __init__(
        self,
        symbols: list[str],
        max_positions: int | None = None,
        min_score_threshold: float = 0.1,
        provider: str | None = None,
    ) -> None:
        self._symbols = symbols
        params = get_trading_params()
        self._max_positions = max_positions or params.risk.max_open_positions
        self._min_score = min_score_threshold
        self._provider = provider
        self._analyses: dict[str, SymbolAnalysis] = {}
        self._market_data = MarketDataClient()

    def analyze_all(self, max_workers: int = 3) -> dict[str, SymbolAnalysis]:
        """
        Tüm semboller için analiz çalıştırır (parallel).

        Args:
            max_workers: Aynı anda kaç sembol analiz edilsin

        Returns:
            {symbol: SymbolAnalysis}
        """
        logger.info(
            "Portföy analizi başlıyor: %d sembol (parallel: %d)",
            len(self._symbols),
            max_workers,
        )
        
        from data.news_data import NewsClient
        from models.technical_analyzer import TechnicalAnalyzer

        self._news_client = NewsClient()
        self._tech_analyzer = TechnicalAnalyzer()

        def _analyze_single(symbol: str) -> tuple[str, SymbolAnalysis]:
            try:
                logger.info("─── %s analizi ───", symbol)

                # Mevcut pipeline'ı çalıştır
                result = run_analysis(
                    symbol=symbol,
                    market_data=self._fetch_market_summary(symbol),
                    news_data=self._fetch_news(symbol),
                    technical_signals=self._fetch_technical_signals(symbol),
                    portfolio_state=self._get_portfolio_state(),
                    provider=self._provider,
                )

                analysis = self._parse_result(symbol, result)
                analysis.calculate_composite_score()

                logger.info(
                    "  %s → skor: %.3f (sentiment: %.2f, debate: %.2f, trend: %s)",
                    symbol,
                    analysis.composite_score,
                    analysis.sentiment_score,
                    analysis.debate_consensus,
                    analysis.trend,
                )

                return (symbol, analysis)

            except Exception as e:
                logger.error("Analiz hatası (%s): %s", symbol, e)
                return (
                    symbol,
                    SymbolAnalysis(
                        symbol=symbol,
                        composite_score=-1.0,
                        raw_result={"error": str(e)},
                    ),
                )

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_analyze_single, sym): sym for sym in self._symbols
                }
                for future in as_completed(futures):
                    symbol, analysis = future.result()
                    self._analyses[symbol] = analysis
        finally:
            self._news_client.close()

        return self._analyses

    def build_portfolio(
        self,
        days_for_returns: int = 90,
    ) -> dict[str, Any]:
        """
        Analiz sonuçlarına göre optimal portföy dağılımı oluşturur.

        Args:
            days_for_returns: CVaR optimizasyonu için getiri verisi (gün)

        Returns:
            Portföy dağılımı
        """
        if not self._analyses:
            self.analyze_all()

        # 1. Eşik üstü skorlu sembolleri seç
        qualified = {
            sym: ana
            for sym, ana in self._analyses.items()
            if ana.composite_score >= self._min_score
            and not ana.raw_result.get("error")
        }

        if not qualified:
            logger.warning(
                "Eşik üstü skorlu sembol bulunamadı (min: %.2f)",
                self._min_score,
            )
            return {
                "status": "no_qualified_assets",
                "reason": f"Min skor eşiği {self._min_score:.2f} karşılanmadı",
                "all_scores": {
                    sym: ana.composite_score for sym, ana in self._analyses.items()
                },
                "allocations": {},
                "total_weight": 0.0,
            }

        # 2. Skorlara göre sırala, max_positions kadar al
        sorted_symbols = sorted(
            qualified.keys(),
            key=lambda s: qualified[s].composite_score,
            reverse=True,
        )
        top_symbols = sorted_symbols[: self._max_positions]

        logger.info(
            "Seçilen varlıklar: %s",
            ", ".join(f"{s} ({qualified[s].composite_score:.3f})" for s in top_symbols),
        )

        # 3. CVaR optimizasyonu için getiri verisi topla
        returns_df = self._build_returns_dataframe(top_symbols, days_for_returns)

        allocations: dict[str, float] = {}

        if (
            returns_df is not None
            and not returns_df.empty
            and len(returns_df.columns) > 1
        ):
            # CVaR optimizasyonu
            params = get_trading_params()
            cvar_result = optimize_portfolio_cvar(
                returns_df,
                confidence=params.risk.cvar_confidence,
                max_weight=params.risk.cvar.max_weight,
            )
            allocations = cvar_result.get("weights", {})
            cvar_info = {
                "cvar": cvar_result.get("cvar", 0),
                "var": cvar_result.get("var", 0),
                "expected_return": cvar_result.get("expected_return", 0),
            }
        else:
            # Tek varlık veya getiri verisi yoksa skor bazlı dağılım
            allocations = self._score_based_allocation(top_symbols, qualified)
            cvar_info = {
                "cvar": 0,
                "var": 0,
                "expected_return": 0,
                "note": "skor-bazlı dağılım",
            }

        # 4. Allokasyonları normalize et (toplam = 1.0)
        total = sum(allocations.values())
        if total > 0:
            allocations = {k: round(v / total, 4) for k, v in allocations.items()}
        
        # 4b. Rejim bazlı exposure limiti uygula
        from risk.regime_filter import RegimeFilter
        regime_filter = RegimeFilter()
        max_exposure = regime_filter.get_max_exposure()
        
        # Toplam ağırlığı rejim limitine göre sınırla
        current_total = sum(allocations.values())
        if current_total > max_exposure:
            logger.warning(
                "⚠️ Rejim limiti aşıldı: %.2f > %.2f (%s rejimi)",
                current_total,
                max_exposure,
                regime_filter.regime.value,
            )
            # Orantılı olarak düşür
            scaling_factor = max_exposure / current_total
            allocations = {k: round(v * scaling_factor, 4) for k, v in allocations.items()}
            logger.info(
                "✅ Allokasyonlar %.2f faktörü ile düşürüldü (toplam: %.2f)",
                scaling_factor,
                sum(allocations.values()),
            )

        # 5. Sonuç
        portfolio = {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_assets_analyzed": len(self._analyses),
            "qualified_assets": len(qualified),
            "selected_assets": len(allocations),
            "allocations": allocations,
            "total_weight": round(sum(allocations.values()), 4),
            "cvar_info": cvar_info,
            "asset_details": {
                sym: {
                    "allocation_pct": allocations.get(sym, 0) * 100,
                    "composite_score": qualified[sym].composite_score,
                    "sentiment_score": qualified[sym].sentiment_score,
                    "sentiment_confidence": qualified[sym].sentiment_confidence,
                    "debate_consensus": qualified[sym].debate_consensus,
                    "debate_winner": qualified[sym].debate_winner,
                    "trend": qualified[sym].trend,
                    "trend_strength": qualified[sym].trend_strength,
                    "rsi": qualified[sym].rsi,
                    "risk_approved": qualified[sym].risk_approved,
                }
                for sym in allocations
            },
            "all_scores": {
                sym: {
                    "composite_score": ana.composite_score,
                    "sentiment_score": ana.sentiment_score,
                    "debate_consensus": ana.debate_consensus,
                    "trend": ana.trend,
                    "risk_approved": ana.risk_approved,
                }
                for sym, ana in self._analyses.items()
            },
        }

        logger.info(
            "Portföy oluşturuldu: %d varlık, toplam ağırlık: %.2f%%",
            len(allocations),
            portfolio["total_weight"] * 100,
        )

        return portfolio

    # ── Yardımcı Metodlar ──────────────────────────────────

    def _fetch_market_summary(self, symbol: str) -> dict:
        """Sembol için piyasa özeti getirir."""
        try:
            df = self._market_data.fetch_ohlcv(symbol, days=90)
            if df.empty:
                return {}
            return {
                "current_price": float(df["close"].iloc[-1]),
                "price_change_24h": float(
                    (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2]
                )
                if len(df) > 1
                else 0,
                "high_24h": float(df["high"].iloc[-1]),
                "low_24h": float(df["low"].iloc[-1]),
                "volume_24h": float(df["volume"].iloc[-1]),
            }
        except Exception as e:
            logger.warning("Market data hatası (%s): %s", symbol, e)
            return {}

    def _fetch_news(self, symbol: str) -> list[dict]:
        """Sembol için haber verisi getirir."""
        try:
            params = get_trading_params()
            items = getattr(self, "_news_client").fetch_all_news(symbol)
            result = []
            for item in items[: params.limits.max_news_items]:
                result.append(
                    {
                        "title": item.title,
                        "summary": item.summary[:300],
                        "source": item.source,
                        "url": item.url,
                        "published_at": item.published_at.isoformat(),
                        "symbols": item.symbols,
                        "category": item.category,
                        "raw_sentiment": item.raw_sentiment,
                    }
                )
            return result
        except Exception as e:
            logger.warning("Haber hatası (%s): %s", symbol, e)
            return []

    def _fetch_technical_signals(self, symbol: str) -> dict:
        """Sembol için teknik sinyaller getirir."""
        try:
            df = self._market_data.fetch_ohlcv(symbol, days=90)
            if df.empty:
                return {}
            signals = getattr(self, "_tech_analyzer").analyze(df, symbol)
            return signals.to_dict()
        except Exception as e:
            logger.warning("Teknik analiz hatası (%s): %s", symbol, e)
            return {}

    def _get_portfolio_state(self) -> dict:
        """Mevcut portföy durumunu getirir."""
        try:
            from risk.portfolio import PortfolioState

            portfolio = PortfolioState.load_from_file()
            return portfolio.to_dict()
        except Exception as e:
            logger.warning("Portföy durumu okunamadı: %s", e)
            return {}

    def _parse_result(self, symbol: str, result: dict) -> SymbolAnalysis:
        """run_analysis sonucunu SymbolAnalysis'a çevirir."""
        sentiment = result.get("sentiment", {})
        debate = result.get("debate_result", {})
        tech = result.get("technical_signals", {})
        risk = result.get("risk_assessment", {})

        analysis = SymbolAnalysis(
            symbol=symbol,
            sentiment_score=float(sentiment.get("sentiment_score", 0)),
            sentiment_confidence=float(sentiment.get("confidence", 0)),
            debate_consensus=float(debate.get("consensus_score", 0)),
            debate_winner=debate.get("winner", "draw"),
            hallucinations=len(debate.get("hallucinations_detected", [])),
            risk_approved=result.get("risk_approved", False),
            risk_warnings=len(risk.get("warnings", [])),
            trend=tech.get("trend", "neutral"),
            trend_strength=float(tech.get("trend_strength", 0)),
            rsi=float(tech.get("rsi_14", 50)),
            raw_result=result,
        )

        # Getiri verisi (CVaR için)
        try:
            df = self._market_data.fetch_ohlcv(symbol, days=90)
            if not df.empty:
                analysis.returns_series = df["close"].pct_change().dropna().tolist()
        except Exception as e:
            logger.debug("Getiri verisi okunamadı (%s): %s", symbol, e)

        return analysis

    def _build_returns_dataframe(
        self, symbols: list[str], days: int
    ) -> pd.DataFrame | None:
        """Sembollerin getiri serilerini DataFrame olarak birleştirir."""
        data = {}
        for symbol in symbols:
            try:
                df = self._market_data.fetch_ohlcv(symbol, days=days)
                if not df.empty:
                    returns = df["close"].pct_change().dropna()
                    # En kısa seriye göre hizala
                    data[symbol] = returns
            except Exception as e:
                logger.warning("Getiri verisi hatası (%s): %s", symbol, e)

        if not data:
            return None

        df = pd.DataFrame(data)
        return df.dropna()

    def _score_based_allocation(
        self,
        symbols: list[str],
        analyses: dict[str, SymbolAnalysis],
    ) -> dict[str, float]:
        """Skorlara göre eşit olmayan dağılım yapar."""
        scores = {s: max(analyses[s].composite_score, 0.01) for s in symbols}
        total = sum(scores.values())
        return {s: round(sc / total, 4) for s, sc in scores.items()}
