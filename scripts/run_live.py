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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

from config.settings import LLMProvider, TradingMode, get_settings, get_trading_params, LOGS_DIR
from data.market_data import MarketDataClient
from data.news_data import NewsClient
from data.symbol_resolver import resolve_symbol
from models.technical_analyzer import TechnicalAnalyzer
from agents.graph import run_analysis
from execution.order_manager import parse_trade_decision, TradeOrder
from execution.exchange_client import ExchangeClient
from execution.sync_manager import SyncManager
from execution.account_manager import MultiAccountManager
from risk.regime_filter import RegimeFilter
from risk.portfolio import PortfolioState
from risk.circuit_breaker import CircuitBreaker
from risk.watchdog import Watchdog
from risk.system_status import SystemStatus
from data.market_hours import MarketHours
from data.scanner import MarketScanner
from agents.lead_scout import LeadScout
from utils.dynamic_rules import inject_dynamic_rules_into_prompt

console = Console()


def setup_logging(level: str = "INFO") -> None:
    """Rich tabanlı ve dosyaya yazan loglama ayarla."""
    from logging.handlers import TimedRotatingFileHandler
    
    # Logs dizini oluştur
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / "trading.log"
    
    # Formatterlar
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Handlers
    console_handler = RichHandler(rich_tracebacks=True, markup=True)
    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)
    
    # Root logger ayarı
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Eski handlerları temizle
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
        
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Üçüncü parti loglarını kısıtla
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def run_pipeline(
    symbol: str,
    execute: bool = False,
    provider: str | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    portfolio: PortfolioState | None = None,
    account_manager: Any = None,
) -> dict:
    """
    Tam analiz pipeline'ını çalıştırır.

    Args:
        symbol: Varlık sembolü
        execute: True ise emri borsaya gönder
        provider: LLM sağlayıcı override
        circuit_breaker: Paylaşılan CircuitBreaker instance'ı
        portfolio: Paylaşılan PortfolioState instance'ı
        account_manager: MultiAccountManager for multi-account mode

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
        
        # Faz 5: Dinamik kuralları yükle ve prompt'a enjekte et
        dynamic_rules_context = inject_dynamic_rules_into_prompt("", "Trader")
        
        result = run_analysis(
            symbol=resolved.symbol,
            market_data=market_summary,
            news_data=news_serialized,
            technical_signals=tech_dict,
            portfolio_state=portfolio_state_dict,
            provider=provider,
            dynamic_rules=dynamic_rules_context if dynamic_rules_context else None,
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
            trade_decision,
            current_price=current_price,
            atr_value=atr_value,
            approved_size=risk.get("approved_size", 0.0) or 0.0,
        )
        if order:
            console.print("\n[bold red]⚡ Emir iletiliyor...[/bold red]")
            
            # Multi-account fan-out execution
            if account_manager:
                exec_results = account_manager.execute_trade(order)
                console.print(f"  Fan-out sonuçları: {exec_results}")
                result["execution_result"] = exec_results
                # Not: execute_trade zaten portföyü günceller
            else:
                client = ExchangeClient()
                client.set_portfolio(portfolio)
                exec_result = client.execute_order(order, current_price=current_price)
                console.print(f"  Sonuç: {exec_result}")
                result["execution_result"] = exec_result
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
    if portfolio:
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
    parser.add_argument(
        "--auto-scan", action="store_true", help="Piyasayı otomatik tara ve fırsatları bul"
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    # AUTO sembol desteği
    if args.symbol and args.symbol.upper() == "AUTO":
        args.auto_scan = True
        args.symbol = None
    
    symbols = args.symbols or ([args.symbol] if args.symbol else [])
    if not symbols and not args.auto_scan:
        console.print("[bold red]❌ --symbol, --symbols veya --auto-scan gerekli[/bold red]")
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

    # Multi-Account Manager
    account_manager = None
    portfolio = None
    client = None
    
    settings = get_settings()
    accounts = settings.binance_accounts
    
    if accounts and len(accounts) > 1:
        # Multi-account mode
        from execution.account_manager import MultiAccountManager

        account_manager = MultiAccountManager(accounts)
        console.print(f"[green]✅ Multi-account mode: {len(accounts)} accounts[/green]")

        for acc in accounts:
            name = acc.get("name", "Unknown")
            api_key = acc.get("api_key", "")
            console.print(f"  [dim]└ {name}: {api_key[:8]}...[/dim]")

        portfolio = None
        client = None
    else:
        # AUTO mode: İlk taramayı yap ve sembolleri bul
        if args.auto_scan and not symbols:
            console.print("[bold magenta]🔍 AUTO mode: Piyasa taraması başlatılıyor...[/bold magenta]")
            try:
                scanner = MarketScanner()
                scout = LeadScout()
                
                candidates = scanner.get_candidates()
                if candidates:
                    selected = scout.select_best_candidates(candidates, limit=5)
                    if selected:
                        symbols = selected
                        console.print(f"[green]✅ AUTO mode: {len(symbols)} coin bulundu: {', '.join(symbols)}[/green]")
                    else:
                        console.print("[yellow]⚠️  Aday bulunamadı, BTC/USDT ile başlanıyor[/yellow]")
                        symbols = ["BTC/USDT"]
                else:
                    console.print("[yellow]⚠️  Scanner aday bulamadı, BTC/USDT ile başlanıyor[/yellow]")
                    symbols = ["BTC/USDT"]
            except Exception as e:
                console.print(f"[yellow]⚠️  AUTO scan hatası: {e}, BTC/USDT ile başlanıyor[/yellow]")
                symbols = ["BTC/USDT"]
        # Single account mode (legacy)
        logging.getLogger(__name__).info("Single account mode")
        portfolio = PortfolioState.load_from_file()
        client = ExchangeClient()
        client.set_portfolio(portfolio)
    
    circuit_breaker = CircuitBreaker()
    system_status = SystemStatus.get_instance()
    
    # ── Borsa Senkronizasyonu ────────────────────────────
    # Bot başladığında borsa bakiyesi ile yerel state'i eşle
    if execute:
        try:
            if account_manager:
                # Multi-account: tüm hesapları senkronize et
                for name, data in account_manager.get_all_accounts().items():
                    console.print(f"[dim]🔄 {name} hesabı senkronize ediliyor...[/dim]")
                    try:
                        data["portfolio"].sync_with_exchange(data["client"])
                    except Exception as sync_err:
                        console.print(f"[yellow]⚠ {name} senkronizasyon hatası: {sync_err}[/yellow]")
                        # IP hatası olabilir, hesabı deaktif et
                        if "429" in str(sync_err) or "IP" in str(sync_err).upper():
                            account_manager.set_account_inactive(name, str(sync_err))
            else:
                portfolio.sync_with_exchange(client)
        except Exception as e:
            console.print(f"[bold red]⚠ Senkronizasyon hatası: {e}[/bold red]")
            # Kritik hata: Senkronizasyon başarısızsa ve canlı moddaysak durdur
            if get_trading_params().execution.mode == TradingMode.LIVE and not account_manager:
                console.print("[bold red]❌ Kritik hata: Canlı modda senkronizasyon başarısız. Bot durduruluyor.[/bold red]")
                sys.exit(1)

    watchdog = None
    if args.watchdog:
        try:
            # Multi-account mode için
            if account_manager:
                watchdog = Watchdog(
                    symbols=symbols,
                    account_manager=account_manager,
                )
            else:
                watchdog = Watchdog(
                    symbols=symbols,
                    portfolio=portfolio,
                    exchange_client=client,
                )
            watchdog.start()
            console.print("[green]🐕 Watchdog başlatıldı[/green]")
        except Exception as e:
            console.print(f"[bold red]⚠ Watchdog başlatılamadı: {e}[/bold red]")

    # Paylaşılan nesneleri dışarıda başlat
    scanner = MarketScanner()
    scout = LeadScout()
    
    # Sync manager (her 10 cycle'da 1 çalışır)
    if account_manager:
        sync_manager = SyncManager(account_manager=account_manager, reconcile_every_n_cycles=10)
    else:
        sync_manager = SyncManager(portfolio, client, reconcile_every_n_cycles=10)

    cycle = 0
    last_rag_cleanup = time.time()
    try:
        while not stop_event.is_set():
            # SystemStatus kontrolü (event-driven)
            if not system_status.is_running():
                reason = system_status.get_halt_reason() or "System halted"
                console.print(f"[bold red]🚨 Sistem durduruldu: {reason}[/bold red]")
                console.print("[dim]Bekleniyor... (resume için SystemStatus.resume() çağrın)[/dim]")
                system_status.wait_for_resume(timeout=60)
                if not system_status.is_running():
                    console.print("[bold yellow]⏸️ Cycle atlandı - sistem hala durduruldu[/bold yellow]")
                    stop_event.wait(interval_seconds)
                    continue
            
            # Watchdog heartbeat kontrolü (her cycle'da)
            if watchdog and not watchdog.check_heartbeat():
                console.print("[bold red]🚨 Watchdog heartbeat timeout![/bold red]")
                # SystemStatus zaten emergency_stop'a geçti (watchdog içinde)
            
            if args.max_cycles > 0 and cycle >= args.max_cycles:
                console.print(
                    f"[bold]🏁 Maksimum döngü sayısına ulaşıldı ({cycle})[/bold]"
                )
                break

            cycle += 1
            start_time = datetime.now(timezone.utc)
            console.print(f"\n{'=' * 60}")
            console.print(
                f"[bold]🔄 Döngü {cycle} — {start_time.strftime('%Y-%m-%d %H:%M UTC')}[/bold]"
            )
            console.print(f"{'=' * 60}")

            # ── Sembolleri Belirle ──────────────────────────────
            current_symbols = list(symbols)
            
            # Faz 3: Dinamik Tarayıcı (her N saatte bir)
            params = get_trading_params()
            
            if account_manager:
                total_cash = sum(
                    acc.get("portfolio", PortfolioState()).cash
                    for acc in account_manager.get_all_accounts().values()
                )
                total_equity = sum(
                    acc.get("portfolio", PortfolioState()).equity
                    for acc in account_manager.get_all_accounts().values()
                )
                cash_ratio = total_cash / total_equity if total_equity > 0 else 1.0
            elif portfolio and portfolio.equity > 0:
                cash_ratio = portfolio.cash / portfolio.equity
            else:
                cash_ratio = 1.0
            
            if params.scanner.dynamic_scanner_enabled and scanner.should_scan(cycle, cash_ratio):
                console.print("[bold magenta]🔍 Dinamik Tarayıcı: Hacim Spike'ı Aranıyor...[/bold magenta]")
                
                try:
                    dynamic_symbols = scanner.get_top_gainers_and_volume_spikes(limit=5)
                    
                    if dynamic_symbols:
                        # [DINAMIK_KEŞIF] flag'li sembolleri ekle
                        new_symbols = [s['symbol'] for s in dynamic_symbols if s['symbol'] not in current_symbols]
                        
                        if new_symbols:
                            current_symbols = list(set(current_symbols + new_symbols))
                            console.print(
                                f"[green]✅ [DINAMIK_KEŞIF] Eklendi: {', '.join(new_symbols)}[/green]"
                            )
                            
                            # Her birinin neden eklendiğini logla
                            for s in dynamic_symbols:
                                if s['symbol'] in new_symbols:
                                    console.print(
                                        f"  [dim]└ {s['symbol']}: {s['discovery_reason']}[/dim]"
                                    )
                    
                    # Tarama tamamlandı olarak işaretle
                    scanner.mark_scan_complete(cycle)
                    
                except Exception as e:
                    console.print(f"[yellow]⚠ Dinamik tarayıcı hatası: {e}[/yellow]")
            
            # Lead Scout (Algoritmik tarama)
            if args.auto_scan:
                console.print("[bold magenta]🔍 Lead Scout: Erken Momentum Taraması...[/bold magenta]")
                candidates = scanner.get_candidates()
                if candidates:
                    selected = scout.select_best_candidates(candidates)
                    if selected:
                        current_symbols = list(set(current_symbols + selected))
                        console.print(f"[green]✅ Lead Scout adayları eklendi: {', '.join(selected)}[/green]")
                else:
                    console.print("[yellow]⚠ Tarayıcı kriterlere uygun aday bulamadı.[/yellow]")

            # --- PARALEL ANALİZ ---
            def task_wrapper(sym):
                try:
                    res = run_pipeline(
                        symbol=sym,
                        execute=execute,
                        provider=args.provider,
                        circuit_breaker=circuit_breaker,
                        portfolio=portfolio,
                        account_manager=account_manager,
                    )
                    if account_manager:
                        account_manager.save_all_portfolios()
                    elif portfolio:
                        portfolio.save_to_file()
                    return res
                except Exception as e:
                    console.print(f"[bold red]❌ Pipeline Error ({sym}): {e}[/bold red]")
                    # Not: LLM hataları run_pipeline içinde zaten kaydediliyor.
                    # Burada genel exception'ları LLM hatası olarak saymamak
                    # için record_llm_error() çağrılmıyor.
                    return {"symbol": sym, "error": str(e)}

            if current_symbols:
                configured_workers = max(1, get_trading_params().system.max_workers)
                num_workers = min(len(current_symbols), configured_workers)
                with ThreadPoolExecutor(max_workers=num_workers) as executor:
                    results = list(executor.map(task_wrapper, current_symbols))
                    for res in results:
                        if isinstance(res, dict) and res.get("error"):
                            logger.error("Pipeline error for %s: %s", res.get("symbol"), res.get("error"))

            # Multi-account için tüm portföyleri kaydet
            if account_manager:
                account_manager.save_all_portfolios()
            elif portfolio:
                portfolio.save_to_file()

            # Cycle sonu özet tablo (her cycle'da)
            from scripts.interactive_commands import cycle_end_prompt
            try:
                # Özet tablo göster
                if portfolio:
                    summary_table = Table(show_header=False, box=None, padding=(0, 2))
                    summary_table.add_column("Metrik", style="cyan", width=20)
                    summary_table.add_column("Değer", style="white")
                    
                    summary_table.add_row("Cycle", f"#{cycle} tamamlandı")
                    summary_table.add_row("Özvarlık", f"${portfolio.equity:,.2f}")
                    summary_table.add_row("PnL", f"${portfolio.total_pnl:+,.2f}")
                    summary_table.add_row("Pozisyon", f"{portfolio.open_position_count} açık")
                    
                    cb_status = circuit_breaker.get_status()
                    fb_count = cb_status['consecutive_fallbacks']
                    summary_table.add_row("Fallback", f"{fb_count}/5 {'✓' if fb_count < 3 else '⚠️'}")
                    
                    console.print(Panel(summary_table, title=f"📊 CYCLE #{cycle} ÖZET", border_style="green"))
                
                # Kullanıcı komutu için fırsat ver
                cmd_entered = cycle_end_prompt(portfolio, cycle, start_time, circuit_breaker)
                if cmd_entered:
                    console.print("[dim]Cycle devam ediyor...[/dim]\n")
            except Exception as e:
                logging.getLogger(__name__).warning("Cycle end prompt error (non-critical): %s", e)

            # Exchange sync (her 10 cycle'da 1)
            if sync_manager.should_reconcile(cycle):
                try:
                    sync_result = sync_manager.reconcile(cycle)
                    if sync_result.get("status") == "success":
                        cleaned = sync_result.get("zombie_orders_cleaned", 0)
                        console.print(f"[dim]🔄 Exchange sync: {cleaned} zombie orders cleaned[/dim]")
                    elif sync_result.get("status") == "discrepancy":
                        console.print(f"[yellow]⚠️  Balance discrepancy detected![/yellow]")
                except Exception as e:
                    console.print(f"[yellow]Sync manager error: {e}[/yellow]")

            # RAG hafıza temizliği (her 24 saatte bir)
            if time.time() - last_rag_cleanup >= 86400:
                try:
                    from data.vector_store import AgentMemoryStore
                    pruned = AgentMemoryStore.get_instance().prune_entries_older_than(days=30)
                    console.print(f"[dim]🧹 RAG Hafızası temizlendi: {pruned} eski kayıt silindi.[/dim]")
                    last_rag_cleanup = time.time()
                except Exception as e:
                    console.print(f"[yellow]RAG temizleme hatası: {e}[/yellow]")

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
        # ChromaDB bağlantılarını kapat
        from data.vector_store import AgentMemoryStore
        try:
            AgentMemoryStore().close()
        except Exception as cleanup_err:
            logging.getLogger(__name__).warning("ChromaDB cleanup error: %s", cleanup_err)
        # Portföyleri kaydet
        if account_manager:
            account_manager.save_all_portfolios()
        elif portfolio:
            portfolio.save_to_file()
        console.print("\n[green]✓ Bot güvenli şekilde durduruldu[/green]")


if __name__ == "__main__":
    main()
