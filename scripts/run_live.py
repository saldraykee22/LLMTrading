"""
LLM Trading System — Ana Çalıştırma Betiği
=============================================
Tam analiz pipeline'ını çalıştırır:
1. Veri çekme (OHLCV + haberler)
2. Teknik analiz
3. Çoklu ajan analizi (LangGraph)
4. Emir oluşturma ve (opsiyonel) yürütme

Kullanım:
    python scripts/run_live.py --symbol BTC/USDT
    python scripts/run_live.py --symbol BTC/USDT --execute
    python scripts/run_live.py --symbol AAPL --provider ollama
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Windows console encoding fix
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Proje kökünü path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config.settings import LLMProvider, get_settings, get_trading_params
from data.market_data import MarketDataClient
from data.news_data import NewsClient
from data.symbol_resolver import resolve_symbol
from models.technical_analyzer import TechnicalAnalyzer
from agents.graph import run_analysis
from execution.order_manager import parse_trade_decision
from execution.exchange_client import ExchangeClient
from risk.regime_filter import RegimeFilter
from risk.portfolio import PortfolioState
from risk.circuit_breaker import CircuitBreaker

console = Console()


def setup_logging(level: str = "INFO") -> None:
    """Rich tabanlı loglama ayarla."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )


def run_pipeline(
    symbol: str,
    execute: bool = False,
    provider: str | None = None,
) -> dict:
    """
    Tam analiz pipeline'ını çalıştırır.

    Args:
        symbol: Varlık sembolü
        execute: True ise emri borsaya gönder
        provider: LLM sağlayıcı override

    Returns:
        Analiz sonuçları
    """
    resolved = resolve_symbol(symbol)
    params = get_trading_params()

    # ── Portföy yükleme (persistence) ─────────────────────
    portfolio = PortfolioState.load_from_file()
    portfolio.reset_daily_pnl_if_needed()
    portfolio_state_dict = portfolio.to_dict()

    # ── Circuit Breaker kontrolü ───────────────────────────
    cb = CircuitBreaker()
    should_halt, halt_reason = cb.should_halt(
        equity=portfolio.equity, daily_pnl=portfolio.daily_pnl
    )
    if should_halt:
        console.print(f"[bold red]⛔ CIRCUIT BREAKER: {halt_reason}[/bold red]")
        return {"status": "halted", "reason": halt_reason}

    console.print(
        Panel(
            f"[bold cyan]LLM Trading System[/bold cyan]\n"
            f"Sembol: [bold]{resolved.symbol}[/bold] ({resolved.asset_class.value})\n"
            f"Borsa: {resolved.exchange}\n"
            f"Mod: {params.execution.mode.value}\n"
            f"Özvarlık: ${portfolio.equity:,.2f}\n"
            f"Zaman: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            title="🤖 Analiz Başlatılıyor",
            border_style="cyan",
        )
    )

    # ── 1. VIX Rejim Kontrolü ────────────────────────────
    console.print("\n[bold yellow]📊 Aşama 1: Rejim Kontrolü[/bold yellow]")
    market_client = MarketDataClient()
    regime_filter = RegimeFilter()

    try:
        vix_data = market_client.fetch_vix(days=60)
        regime = regime_filter.update(vix_data)
        regime_status = regime_filter.get_status()
        console.print(
            f"  VIX: {regime_status['vix_current']:.2f} (SMA: {regime_status['vix_sma']:.2f})"
        )
        console.print(f"  Rejim: [bold]{regime.value}[/bold]")

        if regime_filter.should_halt_trading():
            console.print(
                "[bold red]⚠ YÜKSEK VOLATİLİTE — İşlem durduruldu![/bold red]"
            )
            return {
                "status": "halted",
                "reason": "high_volatility",
                "regime": regime.value,
            }
    except Exception as e:
        console.print(f"  [dim]VIX verisi alınamadı: {e}[/dim]")
        regime_status = {"regime": "unknown"}

    # ── 2. Piyasa Verisi ──────────────────────────────────
    console.print("\n[bold yellow]📈 Aşama 2: Piyasa Verisi[/bold yellow]")
    df = market_client.fetch_ohlcv(symbol, days=90)
    console.print(f"  {len(df)} mum yüklendi")

    market_summary = {}
    if not df.empty:
        market_summary = {
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
        console.print(f"  Fiyat: {market_summary['current_price']:.4f}")
        console.print(f"  24h Değişim: {market_summary['price_change_24h']:.2%}")

    # ── 3. Teknik Analiz ──────────────────────────────────
    console.print("\n[bold yellow]📐 Aşama 3: Teknik Analiz[/bold yellow]")
    tech_analyzer = TechnicalAnalyzer()
    tech_signals = tech_analyzer.analyze(df, symbol)
    tech_dict = tech_signals.to_dict()
    console.print(
        f"  Trend: {tech_signals.trend} (güç: {tech_signals.trend_strength:.2f})"
    )
    console.print(f"  RSI: {tech_signals.rsi_14:.1f}")
    console.print(f"  Sinyal: {tech_signals.signal}")

    # ── 4. Haber Verisi ───────────────────────────────────
    console.print("\n[bold yellow]📰 Aşama 4: Haber Toplama[/bold yellow]")
    news_client = NewsClient()
    news_items = news_client.fetch_all_news(symbol)
    console.print(f"  {len(news_items)} haber toplandı")

    # Haberleri serialize et
    news_serialized = []
    for item in news_items[:20]:  # Max 20 haber
        news_serialized.append(
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

    # ── 5. Çoklu Ajan Analizi ─────────────────────────────
    console.print("\n[bold yellow]🤖 Aşama 5: Çoklu Ajan Analizi[/bold yellow]")
    console.print("  Koordinatör → Araştırmacı → Tartışma → Risk → İşlemci")

    result = run_analysis(
        symbol=resolved.symbol,
        market_data=market_summary,
        news_data=news_serialized,
        technical_signals=tech_dict,
        portfolio_state=portfolio_state_dict,
    )

    # ── 6. Sonuçları Göster ───────────────────────────────
    trade_decision = result.get("trade_decision", {})
    sentiment = result.get("sentiment", {})
    risk = result.get("risk_assessment", {})
    debate = result.get("debate_result", {})

    # Sonuç tablosu
    table = Table(title="📋 Analiz Sonuçları", show_header=True, border_style="cyan")
    table.add_column("Parametre", style="bold")
    table.add_column("Değer")

    table.add_row("Sembol", resolved.symbol)
    table.add_row(
        "Duyarlılık",
        f"{sentiment.get('signal', 'N/A')} ({sentiment.get('sentiment_score', 0):.2f})",
    )
    table.add_row("Güven", f"{sentiment.get('confidence', 0):.2f}")
    table.add_row(
        "Tartışma",
        f"{debate.get('adjusted_signal', 'N/A')} ({debate.get('consensus_score', 0):.2f})",
    )
    table.add_row("Risk Kararı", risk.get("decision", "N/A"))
    table.add_row("─" * 20, "─" * 30)
    table.add_row(
        "📌 AKSİYON", f"[bold]{trade_decision.get('action', 'hold').upper()}[/bold]"
    )
    table.add_row("Miktar", str(trade_decision.get("amount", 0)))
    table.add_row("Stop-Loss", str(trade_decision.get("stop_loss", 0)))
    table.add_row("Take-Profit", str(trade_decision.get("take_profit", 0)))
    table.add_row("Güven", str(trade_decision.get("confidence", 0)))

    console.print(table)

    # ── 7. Emir Yürütme (opsiyonel) ───────────────────────
    current_price = market_summary.get("current_price", 0)
    atr_value = tech_dict.get("atr_14", 0)
    if execute and trade_decision.get("action") in ("buy", "sell"):
        # ── Güvenlik Kapısı (Security Gate) ───────────────────
        settings = get_settings()
        if params.execution.mode == TradingMode.LIVE:
            if not settings.confirm_live_trade:
                console.print("\n[bold red]❌ GÜVENLİK ENGELİ: Canlı işlem modu aktif ancak onaylanmadı![/bold red]")
                console.print("[yellow]Canlı işlem yapmak için .env dosyasına şunları ekleyin:[/yellow]")
                console.print("[white]TRADING_MODE=live[/white]")
                console.print("[white]CONFIRM_LIVE_TRADE=true[/white]")
                return {"status": "error", "message": "Live trading not confirmed"}
            
            console.print("\n[bold red]⚠⚠⚠ DİKKAT: CANLI İŞLEM GERÇEKLEŞTİRİLİYOR! ⚠⚠⚠[/bold red]")

        order = parse_trade_decision(
            trade_decision, current_price=current_price, atr_value=atr_value
        )
        if order:
            console.print("\n[bold red]⚡ Emir iletiliyor...[/bold red]")
            client = ExchangeClient()
            exec_result = client.execute_order(order, current_price=current_price)
            console.print(f"  Sonuç: {exec_result}")
            result["execution_result"] = exec_result

            # Paper modda portföy güncellemesi engine tarafından yapılır
            if exec_result.get("mode") == "paper":
                paper_status = client._get_paper_engine().get_status()
                portfolio.cash = paper_status["cash"]
                portfolio.total_pnl = paper_status["total_pnl"]
                portfolio.daily_pnl = paper_status["daily_pnl"]
                portfolio.max_equity = paper_status["max_equity"]
                portfolio.current_drawdown = paper_status["current_drawdown"]
    elif trade_decision.get("action") in ("buy", "sell"):
        console.print("\n[dim]--execute bayrağı olmadan emir gönderilmedi[/dim]")

    # Temizlik
    news_client.close()

    # ── Portföy kaydetme (persistence) ────────────────────
    portfolio.update_drawdown()
    portfolio.save_to_file()
    console.print(
        f"\n[dim]💾 Portföy kaydedildi (equity: ${portfolio.equity:,.2f})[/dim]"
    )

    # Mesaj geçmişini göster
    console.print("\n[bold yellow]💬 Ajan İletişim Geçmişi[/bold yellow]")
    for msg in result.get("messages", []):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        console.print(f"  [{role}] {content[:200]}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Trading System")
    parser.add_argument(
        "--symbol", "-s", required=True, help="Varlık sembolü (ör. BTC/USDT, AAPL)"
    )
    parser.add_argument(
        "--execute", "-x", action="store_true", help="Emri borsaya gönder"
    )
    parser.add_argument(
        "--provider",
        "-p",
        choices=["openrouter", "deepseek", "ollama"],
        help="LLM sağlayıcı",
    )
    parser.add_argument("--log-level", "-l", default="INFO", help="Log seviyesi")

    args = parser.parse_args()
    setup_logging(args.log_level)

    result = run_pipeline(
        symbol=args.symbol,
        execute=args.execute,
        provider=args.provider,
    )

    # Sonucu JSON dosyasına kaydet
    output_dir = PROJECT_ROOT / "data" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"analysis_{args.symbol.replace('/', '_')}_{ts}.json"

    # Serialize edilebilir hale getir
    def make_serializable(obj):
        if isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [make_serializable(i) for i in obj]
        elif isinstance(obj, (datetime,)):
            return obj.isoformat()
        return obj

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(make_serializable(result), f, ensure_ascii=False, indent=2)

    console.print(f"\n[green]✓ Sonuçlar kaydedildi: {output_file}[/green]")


if __name__ == "__main__":
    main()
