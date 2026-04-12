"""
Retrospektif Analiz Ajanı
===========================
Kaybeden işlemleri otomatik olarak analiz eder ve öğrenilen dersleri
RAG vektör deposuna kaydeder.

Akış:
1. Pozisyon zararla kapandığında tetiklenir
2. İşlem dönemine ait OHLCV ve haber verilerini toplar
3. LLM'e piyasa bağlamını göndererek kök neden analizi yapar
4. Sonuçları VectorStore'a etiketli şekilde kaydeder
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import LLMProvider, get_trading_params
from data.market_data import MarketDataClient
from data.news_data import NewsClient, NewsItem
from data.vector_store import AgentMemoryStore
from models.sentiment_analyzer import create_llm
from utils.json_utils import extract_json

logger = logging.getLogger(__name__)

RETROSPECTIVE_SYSTEM_PROMPT = """\
You are a Retrospective Trade Analyst for an automated trading system.
Your job is to analyze losing trades and extract actionable lessons.

Analyze the provided losing trade with full market context and answer:
1. What technical indicators suggested the OPPOSITE of the trade direction?
2. What news/events during the trade period were missed or misinterpreted?
3. Was this a bad entry, bad exit, or unavoidable market move?
4. What should the system do differently next time in similar conditions?

Return your analysis as STRICT JSON with this schema:
{
  "root_cause": "single sentence describing the main reason for the loss",
  "root_cause_category": "one of: bad_entry, bad_exit, missed_news, market_crash, false_signal, overleveraged, unavoidable",
  "missed_signals": ["list of technical or fundamental signals that were ignored"],
  "lesson_learned": "one actionable sentence the system can apply to future trades",
  "confidence": 0.0 to 1.0, how confident you are in this analysis,
  "entry_quality": "good, neutral, or bad",
  "exit_quality": "good, neutral, or bad",
  "market_regime_during_trade": "trending_up, trending_down, ranging, volatile, or crash"
}

Be concise. No markdown formatting outside the JSON block."""


@dataclass
class RetrospectiveResult:
    """Tek bir kayıp işlemin retrospektif analizi."""

    symbol: str
    trade_pnl: float
    entry_time: str
    exit_time: str
    root_cause: str
    root_cause_category: str
    missed_signals: list[str] = field(default_factory=list)
    lesson_learned: str = ""
    confidence: float = 0.0
    entry_quality: str = "unknown"
    exit_quality: str = "unknown"
    market_regime_during_trade: str = "unknown"
    analysis_time: str = ""

    def __post_init__(self) -> None:
        if not self.analysis_time:
            self.analysis_time = datetime.now(timezone.utc).isoformat()


class RetrospectiveAgent:
    """Kaybeden işlemleri analiz eden ve dersleri RAG'a kaydeden ajan."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        self._params = get_trading_params()
        self._llm = create_llm(provider, model, temperature=0.1)
        self._market_client = MarketDataClient()
        self._news_client = NewsClient()
        self._memory_store = AgentMemoryStore()

    def analyze_losing_trade(
        self, trade_record: dict[str, Any], symbol: str
    ) -> RetrospectiveResult:
        """
        Tek bir kayıp işlemi analiz eder.

        Args:
            trade_record: PortfolioState.closed_trades'den gelen işlem kaydı
            symbol: Varlık sembolü

        Returns:
            RetrospectiveResult: Analiz sonucu
        """
        pnl = trade_record.get("pnl", 0.0)
        if pnl >= 0:
            logger.warning("Karlı işlem retrospektif analize gönderilemez: %s", symbol)
            return RetrospectiveResult(
                symbol=symbol,
                trade_pnl=pnl,
                entry_time=trade_record.get("entry_time", ""),
                exit_time=trade_record.get("exit_time", ""),
                root_cause="not_a_losing_trade",
                root_cause_category="unavoidable",
                lesson_learned="Trade was profitable, no retrospective needed.",
                confidence=1.0,
            )

        logger.info("Retrospektif analiz başlatılıyor: %s (PnL: %.4f)", symbol, pnl)

        market_context, news_context = self._gather_context(trade_record, symbol)
        analysis = self._llm_analysis(trade_record, market_context, news_context)

        if not analysis:
            logger.error("LLM analizi başarısız: %s", symbol)
            return RetrospectiveResult(
                symbol=symbol,
                trade_pnl=pnl,
                entry_time=trade_record.get("entry_time", ""),
                exit_time=trade_record.get("exit_time", ""),
                root_cause="llm_analysis_failed",
                root_cause_category="unavoidable",
                lesson_learned="Analysis could not be completed due to LLM error.",
                confidence=0.0,
            )

        result = RetrospectiveResult(
            symbol=symbol,
            trade_pnl=pnl,
            entry_time=trade_record.get("entry_time", ""),
            exit_time=trade_record.get("exit_time", ""),
            root_cause=analysis.get("root_cause", "unknown"),
            root_cause_category=analysis.get("root_cause_category", "unknown"),
            missed_signals=analysis.get("missed_signals", []),
            lesson_learned=analysis.get("lesson_learned", ""),
            confidence=float(analysis.get("confidence", 0.3)),
            entry_quality=analysis.get("entry_quality", "unknown"),
            exit_quality=analysis.get("exit_quality", "unknown"),
            market_regime_during_trade=analysis.get(
                "market_regime_during_trade", "unknown"
            ),
        )

        self.store_lesson(result, symbol)
        logger.info(
            "Retrospektif tamamlandı: %s → %s (güven: %.2f)",
            symbol,
            result.root_cause_category,
            result.confidence,
        )
        return result

    def _gather_context(
        self, trade_record: dict[str, Any], symbol: str
    ) -> tuple[str, str]:
        """
        İşlem dönemine ait piyasa ve haber bağlamını toplar.

        Returns:
            (market_context_text, news_context_text)
        """
        entry_time_str = trade_record.get("entry_time", "")
        exit_time_str = trade_record.get("exit_time", "")

        market_context = self._build_market_context(
            symbol, entry_time_str, exit_time_str
        )
        news_context = self._build_news_context(symbol, entry_time_str, exit_time_str)

        return market_context, news_context

    def _build_market_context(
        self, symbol: str, entry_time_str: str, exit_time_str: str
    ) -> str:
        """İşlem dönemine ait OHLCV verisini metin olarak formatlar."""
        try:
            ohlcv = self._market_client.fetch_ohlcv(symbol, days=90)
        except Exception as e:
            logger.error("OHLCV veri hatası (%s): %s", symbol, e)
            return "Market data unavailable."

        if ohlcv.empty:
            return "No OHLCV data found for the trade period."

        entry_dt = self._parse_iso(entry_time_str)
        exit_dt = self._parse_iso(exit_time_str)

        if entry_dt and exit_dt:
            entry_ts = entry_dt.strftime("%Y-%m-%d %H:%M:%S")
            exit_ts = exit_dt.strftime("%Y-%m-%d %H:%M:%S")
            mask = (ohlcv["datetime"] >= entry_dt) & (ohlcv["datetime"] <= exit_dt)
            trade_period = ohlcv.loc[mask]
        else:
            entry_ts = entry_time_str
            exit_ts = exit_time_str
            trade_period = ohlcv.tail(20)

        if trade_period.empty:
            trade_period = ohlcv.tail(20)

        lines = [
            f"Trade period: {entry_ts} → {exit_ts}",
            f"Total candles available: {len(ohlcv)}",
            f"Candles during trade: {len(trade_period)}",
            "",
            "Recent price action (last 10 candles during trade):",
        ]

        for _, row in trade_period.tail(10).iterrows():
            dt_str = str(row["datetime"])[:19]
            lines.append(
                f"  {dt_str} | O:{row['open']:.4f} H:{row['high']:.4f} "
                f"L:{row['low']:.4f} C:{row['close']:.4f} V:{row['volume']:.2f}"
            )

        if not trade_period.empty:
            first_close = float(trade_period["close"].iloc[0])
            last_close = float(trade_period["close"].iloc[-1])
            period_change_pct = (
                (last_close - first_close) / first_close * 100 if first_close > 0 else 0
            )
            high = float(trade_period["high"].max())
            low = float(trade_period["low"].min())
            avg_vol = float(trade_period["volume"].mean())
            lines.append("")
            lines.append(
                f"Period summary: {period_change_pct:+.2f}% | "
                f"High: {high:.4f} | Low: {low:.4f} | Avg Vol: {avg_vol:.2f}"
            )

        return "\n".join(lines)

    def _build_news_context(
        self, symbol: str, entry_time_str: str, exit_time_str: str
    ) -> str:
        """İşlem dönemine ait haberleri metin olarak formatlar."""
        try:
            news_items = self._news_client.fetch_all_news(symbol, include_general=True)
        except Exception as e:
            logger.error("Haber veri hatası (%s): %s", symbol, e)
            return "News data unavailable."

        entry_dt = self._parse_iso(entry_time_str)
        exit_dt = self._parse_iso(exit_time_str)

        if entry_dt and exit_dt:
            relevant_news = [
                n
                for n in news_items
                if entry_dt - timedelta(hours=12) <= n.published_at <= exit_dt
            ]
        else:
            relevant_news = news_items[:15]

        if not relevant_news:
            return "No news found for the trade period."

        lines = [f"News during/around trade period ({len(relevant_news)} items):", ""]
        for i, item in enumerate(relevant_news[:15], 1):
            pub = item.published_at.strftime("%Y-%m-%d %H:%M")
            sentiment_tag = f" [{item.raw_sentiment}]" if item.raw_sentiment else ""
            lines.append(f"{i}. [{pub}]{sentiment_tag} **{item.title}**")
            if item.summary:
                lines.append(f"   Summary: {item.summary[:250]}")
            lines.append("")

        return "\n".join(lines)

    def _llm_analysis(
        self,
        trade_record: dict[str, Any],
        market_context: str,
        news_context: str,
    ) -> dict[str, Any] | None:
        """
        LLM'e kayıp işlem analizini gönderir. JSON hatalarında retry yapar.

        Returns:
            Parsed JSON dict or None on failure.
        """
        pnl = trade_record.get("pnl", 0.0)
        pnl_pct = trade_record.get("pnl_pct", 0.0)
        entry_price = trade_record.get("entry_price", 0.0)
        exit_price = trade_record.get("exit_price", 0.0)
        amount = trade_record.get("amount", 0.0)
        entry_time = trade_record.get("entry_time", "unknown")
        exit_time = trade_record.get("exit_time", "unknown")

        user_message = f"""\
## Losing Trade Details
- Symbol: {trade_record.get("symbol", "UNKNOWN")}
- Side: {trade_record.get("side", "long")}
- Entry: {entry_price:.4f} @ {entry_time}
- Exit: {exit_price:.4f} @ {exit_time}
- Amount: {amount}
- PnL: {pnl:.4f} ({pnl_pct * 100:+.2f}%)

## Market Context During Trade
{market_context}

## News Context During Trade
{news_context}

Analyze this losing trade and return your findings as STRICT JSON."""

        messages = [
            SystemMessage(content=RETROSPECTIVE_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]

        from utils.llm_retry import invoke_with_retry
        from utils.json_utils import extract_json

        # Maksimum 3 deneme (JSON hatası dahil)
        for attempt in range(3):
            try:
                response = invoke_with_retry(
                    self._llm.invoke,
                    messages,
                    max_tokens=self._params.limits.max_tokens_research,
                    response_format={"type": "json_object"},
                    max_retries=2, # Her dış denemede 2 iç retry
                )
                raw_text = response.content
                result = extract_json(raw_text)

                if "__parse_error__" not in result:
                    return result

                logger.warning(
                    "Retrospektif JSON parse hatası (deneme %d/3): %s",
                    attempt + 1,
                    result.get("__parse_error__"),
                )
            except Exception as e:
                logger.error("LLM retrospektif hatası (deneme %d/3): %s", attempt + 1, e)

        return None

    def store_lesson(self, result: RetrospectiveResult, symbol: str) -> None:
        """
        Analiz sonucunu VectorStore'a kaydeder.

        Tags: losing_trade, root_cause:XYZ, symbol
        """
        if not self._memory_store.collection:
            logger.warning("VectorStore kullanılamıyor, ders kaydedilemedi")
            return

        doc_text = (
            f"Losing trade on {symbol}: {result.root_cause}. "
            f"Category: {result.root_cause_category}. "
            f"Missed signals: {', '.join(result.missed_signals)}. "
            f"Lesson: {result.lesson_learned}. "
            f"Entry quality: {result.entry_quality}, "
            f"Exit quality: {result.exit_quality}. "
            f"Market regime: {result.market_regime_during_trade}. "
            f"PnL: {result.trade_pnl:.4f} ({result.confidence:.0%} confidence)."
        )

        metadata = {
            "symbol": symbol,
            "action": "losing_trade",
            "root_cause_category": result.root_cause_category,
            "entry_quality": result.entry_quality,
            "exit_quality": result.exit_quality,
            "market_regime": result.market_regime_during_trade,
            "accuracy": result.confidence,
            "timestamp": result.analysis_time,
        }

        doc_id = f"retro_{symbol}_{datetime.now(timezone.utc).timestamp()}"

        try:
            self._memory_store.collection.add(
                documents=[doc_text],
                metadatas=[metadata],
                ids=[doc_id],
            )
            logger.debug("Retrospektif ders kaydedildi: %s", doc_id)
        except Exception as e:
            logger.error("Vektör db retrospektif kayıt hatası: %s", e)

    @staticmethod
    def _parse_iso(iso_str: str) -> datetime | None:
        """ISO format tarih stringini datetime'a çevirir."""
        if not iso_str:
            return None
        try:
            return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None


def check_and_analyze_losses(portfolio) -> list[RetrospectiveResult]:
    """
    Portföydeki kapatılmış kayıp işlemleri kontrol eder ve
    analiz edilmemiş olanları retrospektif analize sokar.

    Args:
        portfolio: PortfolioState instance

    Returns:
        List of RetrospectiveResult for each analyzed trade.
    """
    from risk.portfolio import PortfolioState

    if not isinstance(portfolio, PortfolioState):
        logger.error("Geçersiz portföy nesnesi")
        return []

    agent = RetrospectiveAgent()
    results: list[RetrospectiveResult] = []

    for trade in portfolio.closed_trades:
        if trade.get("retrospective_analyzed", False):
            continue

        pnl = trade.get("pnl", 0.0)
        if pnl >= 0:
            continue

        symbol = trade.get("symbol", "UNKNOWN")
        try:
            result = agent.analyze_losing_trade(trade, symbol)
            results.append(result)

            trade["retrospective_analyzed"] = True
            trade["retrospective_category"] = result.root_cause_category
            trade["retrospective_lesson"] = result.lesson_learned

            portfolio.save_to_file()
        except Exception as e:
            logger.error("Retrospektif analiz hatası (%s): %s", symbol, e)
            continue

    if results:
        logger.info(
            "Retrospektif analiz tamamlandı: %d kayıp işlem incelendi", len(results)
        )
    else:
        logger.debug("Analiz edilecek kayıp işlem bulunamadı")

    return results
