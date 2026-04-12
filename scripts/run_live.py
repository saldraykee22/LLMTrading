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
import signal
import sys
import threading
import time
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

from config.settings import LLMProvider, TradingMode, get_settings, get_trading_params
from data.market_data import MarketDataClient
from data.news_data import NewsClient
from data.symbol_resolver import resolve_symbol
from models.technical_analyzer import TechnicalAnalyzer
from agents.graph import run_analysis
from execution.order_manager import parse_trade_decision, TradeOrder
from execution.exchange_client import ExchangeClient
from risk.regime_filter import RegimeFilter
from risk.portfolio import PortfolioState
from risk.circuit_breaker import CircuitBreaker
from risk.watchdog import Watchdog
from data.market_hours import MarketHours

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
    circuit_breaker: CircuitBreaker | None = None,
    portfolio: PortfolioState | None = None,
) -> dict:
    """
    Tam analiz pipeline'ını çalıştırır.

    Args:
        symbol: Varlık sembolü
        execute: True ise emri borsaya gönder
        provider: LLM sağlayıcı override
        circuit_breaker: Paylaşılan CircuitBreaker instance'ı
        portfolio: Paylaşılan PortfolioState instance'ı

    Returns:
        Analiz sonuçları
    """
    resolved = resolve_symbol(symbol)
    params = get_trading_params()

    # ── Portföy yükleme (persistence) ─────────────────────
    if portfolio is None:
        portfolio = PortfolioState.load_from_file()
    portfolio.reset_daily_pnl_if_needed()
    portfolio_state_dict = portfolio.to_dict()

    # ── Circuit Breaker kontrolü ───────────────────────────
    cb = circuit_breaker or CircuitBreaker()
    should_halt, halt_reason = cb.should_halt(
        equity=portfolio.equity, daily_pnl=portfolio.daily_pnl
    )
    if should_halt:
        console.print(f"[bold red]⛔ CIRCUIT BREAKER: {halt_reason}[/bold red]")
        return {"status": "halted", "reason": halt_reason}

    # ── Market Hours kontrolü ──────────────────────────────
    market_info = MarketHours.get_market_info(resolved.symbol)
    if not market_info["is_open"]:
        time_left = MarketHours.time_until_open(resolved.symbol)
        hours, remainder = divmod(int(time_left.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        console.print(
            f"[bold yellow]⏰ MARKET CLOSED: {market_info['market']} "
            f"({market_info['schedule']} {market_info['open']}-{market_info['close']} {market_info['timezone']})[/bold yellow]"
        )
        console.print(f"[dim]  Market opens in {hours}h {minutes}m[/dim]")
        return {
            "status": "market_closed",
            "market": market_info["market"],
            "opens_in": str(time_left),
        }

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

    # ── Portföy Otonom Çıkış Kontrolü (Stop-Loss / Take-Profit) ───
    current_price_for_check = market_summary.get("current_price", 0)
    if current_price_for_check > 0:
        for pos in list(portfolio.positions):
            if pos.symbol == resolved.symbol:
                pos.update_price(current_price_for_check)

                # Stop Loss Kontrolü
                if pos.should_stop_loss(current_price_for_check):
                    console.print(
                        f"[bold red]🚨 OTONOM ÇIKIŞ: STOP-LOSS tetiklendi ({pos.symbol})[/bold red]"
                    )
                    if execute:
                        client = ExchangeClient()
                        order = TradeOrder(
                            symbol=pos.symbol,
                            action="sell",
                            order_type="market",
                            amount=pos.amount,
                        )
                        exec_res = client.execute_order(order, current_price_for_check)
                        if exec_res.get("status") in ("filled", "closed", "open"):
                            portfolio.close_position(
                                pos.symbol,
                                float(exec_res.get("price") or current_price_for_check),
                            )
                    else:
                        console.print(
                            f"  [dim]Execute kapalı — {pos.symbol} stop-loss pozisyonu kapatılmadı (sadece log)[/dim]"
                        )

                # Take Profit Kontrolü
                elif pos.should_take_profit(current_price_for_check):
                    console.print(
                        f"[bold green]🎯 OTONOM ÇIKIŞ: TAKE-PROFIT tetiklendi ({pos.symbol})[/bold green]"
                    )
                    if execute:
                        client = ExchangeClient()
                        order = TradeOrder(
                            symbol=pos.symbol,
                            action="sell",
                            order_type="market",
                            amount=pos.amount,
                        )
                        exec_res = client.execute_order(order, current_price_for_check)
                        if exec_res.get("status") in ("filled", "closed", "open"):
                            portfolio.close_position(
                                pos.symbol,
                                float(exec_res.get("price") or current_price_for_check),
                            )
                    else:
                        console.print(
                            f"  [dim]Execute kapalı — {pos.symbol} take-profit pozisyonu kapatılmadı (sadece log)[/dim]"
                        )

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
    result = None
    try:
        news_items = news_client.fetch_all_news(symbol)
        console.print(f"  {len(news_items)} haber toplandı")

        news_serialized = []
        for item in news_items[: params.limits.max_news_items]:
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

        console.print("\n[bold yellow]🤖 Aşama 5: Çoklu Ajan Analizi[/bold yellow]")
        console.print("  Koordinatör → Araştırmacı → Tartışma → Risk → İşlemci")

        result = run_analysis(
            symbol=resolved.symbol,
            market_data=market_summary,
            news_data=news_serialized,
            technical_signals=tech_dict,
            portfolio_state=portfolio_state_dict,
            provider=provider,
        )
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error("Pipeline error for %s: %s", symbol, e)
        result = {"error": str(e), "trade_decision": {"action": "hold"}}
    finally:
        news_client.close()

    # ── Hata Kontrolü ve Circuit Breaker ──────────────────
    if result and result.get("error"):
        console.print(
            f"\n[bold red]❌ Ajan Hatası Algılandı: {result['error']}[/bold red]"
        )
        cb.record_llm_error()
    else:
        cb.reset_llm_errors()

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
                console.print(
                    "\n[bold red]❌ GÜVENLİK ENGELİ: Canlı işlem modu aktif ancak onaylanmadı![/bold red]"
                )
                console.print(
                    "[yellow]Canlı işlem yapmak için .env dosyasına şunları ekleyin:[/yellow]"
                )
                console.print("[white]TRADING_MODE=live[/white]")
                console.print("[white]CONFIRM_LIVE_TRADE=true[/white]")
                return {"status": "error", "message": "Live trading not confirmed"}

            console.print(
                "\n[bold red]⚠⚠⚠ DİKKAT: CANLI İŞLEM GERÇEKLEŞTİRİLİYOR! ⚠⚠⚠[/bold red]"
            )

        order = parse_trade_decision(
            trade_decision, current_price=current_price, atr_value=atr_value
        )
        if order:
            console.print("\n[bold red]⚡ Emir iletiliyor...[/bold red]")
            client = ExchangeClient()
            exec_result = client.execute_order(order, current_price=current_price)
            console.print(f"  Sonuç: {exec_result}")
            result["execution_result"] = exec_result

            if exec_result.get("status") in ("filled", "closed", "open"):
                exec_price = float(exec_result.get("price") or current_price)
                exec_amount = float(exec_result.get("amount") or order.amount)

                existing_pos = next(
                    (p for p in portfolio.positions if p.symbol == order.symbol), None
                )

                if order.action == "buy":
                    if not existing_pos:
                        portfolio.open_position(
                            symbol=order.symbol,
                            side="long",
                            price=exec_price,
                            amount=exec_amount,
                            stop_loss=order.stop_loss,
                            take_profit=order.take_profit,
                        )
                elif order.action == "sell":
                    if existing_pos:
                        portfolio.close_position(order.symbol, exec_price)
        else:
            console.print(
                "[bold red]❌ Emir oluşturulamadı: Trade decision validasyon hatası[/bold red]"
            )
            result["execution_result"] = {
                "status": "rejected",
                "reason": "validation_failed",
            }
    elif trade_decision.get("action") in ("buy", "sell"):
        console.print("\n[dim]--execute bayrağı olmadan emir gönderilmedi[/dim]")

    # ── Portföy kaydetme (persistence) ────────────────────
    portfolio.update_drawdown()
    portfolio.update_benchmark(df)
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


def parse_interval(interval: str) -> int:
    """Parses interval string like '5m', '15m', '1h', '4h', '1d' to seconds."""
    interval = interval.lower().strip()
    if interval.endswith("d"):
        return int(interval[:-1]) * 86400
    if interval.endswith("h"):
        return int(interval[:-1]) * 3600
    if interval.endswith("m"):
        return int(interval[:-1]) * 60
    return int(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Trading System")
    parser.add_argument(
        "--symbol", "-s", default=None, help="Varlık sembolü (tek, --symbols yoksa)"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Coin listesi (virgülle veya ayrı ayrı)",
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
    parser.add_argument(
        "--interval",
        "-i",
        default="1h",
        help="Analiz aralığı (5m, 15m, 30m, 1h, 4h, 1d)",
    )
    parser.add_argument(
        "--watchdog", "-w", action="store_true", help="Flash crash korumasını aç"
    )
    parser.add_argument(
        "--max-cycles", type=int, default=0, help="Maksimum döngü sayısı (0=sınırsız)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Sadece analiz, emir yok"
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    symbols = args.symbols or ([args.symbol] if args.symbol else [])
    if not symbols:
        console.print("[bold red]❌ --symbol veya --symbols gerekli[/bold red]")
        sys.exit(1)

    interval_seconds = parse_interval(args.interval)
    execute = args.execute and not args.dry_run

    console.print(
        Panel(
            f"[bold cyan]LLM Trading Bot (Daemon Mode)[/bold cyan]\n"
            f"Semboller: [bold]{', '.join(symbols)}[/bold]\n"
            f"Interval: {args.interval} ({interval_seconds}s)\n"
            f"Mod: {'execute' if execute else 'paper/dry-run'}\n"
            f"Watchdog: {'[green]AÇIK[/green]' if args.watchdog else '[dim]KAPALI[/dim]'}\n"
            f"Max Cycles: {'sınırsız' if args.max_cycles == 0 else args.max_cycles}",
            title="🤖 Bot Başlatılıyor",
            border_style="cyan",
        )
    )

    stop_event = threading.Event()

    def signal_handler(sig, frame):
        console.print(
            "\n[bold yellow]🛑 Sinyal alındı, bot durduruluyor...[/bold yellow]"
        )
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    portfolio = PortfolioState.load_from_file()
    circuit_breaker = CircuitBreaker()

    watchdog = None
    if args.watchdog:
        try:
            client = ExchangeClient()
            watchdog = Watchdog(
                symbols=symbols,
                portfolio=portfolio,
                exchange_client=client,
            )
            watchdog.start()
            console.print("[green]🐕 Watchdog başlatıldı[/green]")
        except Exception as e:
            console.print(f"[bold red]⚠ Watchdog başlatılamadı: {e}[/bold red]")

    cycle = 0
    try:
        while not stop_event.is_set():
            if args.max_cycles > 0 and cycle >= args.max_cycles:
                console.print(
                    f"[dim]🏁 Maksimum döngü sayısına ulaşıldı ({cycle})[/dim]"
                )
                break

            cycle += 1
            console.print(f"\n{'=' * 60}")
            console.print(
                f"[bold]🔄 Döngü {cycle} — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}[/bold]"
            )
            console.print(f"{'=' * 60}")

            for symbol in symbols:
                result = run_pipeline(
                    symbol=symbol,
                    execute=execute,
                    provider=args.provider,
                    circuit_breaker=circuit_breaker,
                    portfolio=portfolio,
                )

                if result.get("status") in ("halted", "market_closed"):
                    console.print(
                        f"[dim]  {symbol}: {result.get('status')} — atlanıyor[/dim]"
                    )
                    continue

            portfolio.save_to_file()

            if args.max_cycles > 0 and cycle >= args.max_cycles:
                break

            if not stop_event.is_set():
                console.print(
                    f"\n[dim]⏳ Sonraki cycle: {args.interval} sonra... (Ctrl+C ile durdur)[/dim]"
                )
                stop_event.wait(interval_seconds)

    except KeyboardInterrupt:
        console.print(
            "\n[bold yellow]🛑 KlavyeInterrupt — Bot durduruluyor...[/bold yellow]"
        )
    finally:
        if watchdog:
            watchdog.stop()
        portfolio.save_to_file()
        console.print("\n[green]✓ Bot güvenli şekilde durduruldu[/green]")


if __name__ == "__main__":
    main()
