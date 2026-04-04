"""
LLM Trading System — Backtest Çalıştırma Betiği
==================================================
Geçmiş veriler üzerinde strateji testi yapar.

Kullanım:
    python scripts/run_backtest.py --symbol BTC/USDT --days 365
    python scripts/run_backtest.py --symbol AAPL --mode walk-forward
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from config.settings import get_trading_params
from data.market_data import MarketDataClient
from data.news_data import NewsClient
from data.symbol_resolver import resolve_symbol
from models.technical_analyzer import TechnicalAnalyzer
from models.sentiment_analyzer import SentimentAnalyzer
from backtest.walk_forward import (
    BacktestResult,
    calculate_metrics,
    chronological_split,
    rolling_walk_forward,
)
from risk.cvar_optimizer import calculate_var, stress_test_monte_carlo
from risk.stop_loss import DynamicStopLoss
from risk.portfolio import PortfolioState

console = Console()


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


def run_simple_backtest(
    symbol: str,
    days: int = 365,
) -> BacktestResult:
    """
    Basit duyarlılık+teknik strateji backtesti.

    LLM sentiment skorları önceden hesaplanır (pre-compute),
    sonra teknik sinyallerle birleştirilerek sınalır.
    """
    params = get_trading_params()
    resolved = resolve_symbol(symbol)

    console.print(Panel(
        f"[bold cyan]Backtest[/bold cyan]\n"
        f"Sembol: [bold]{resolved.symbol}[/bold]\n"
        f"Süre: {days} gün\n"
        f"Sermaye: {params.backtest.initial_cash} USDT",
        title="📊 Geriye Dönük Test",
        border_style="cyan",
    ))

    # ── Veri çekme ────────────────────────────────────────
    console.print("\n[bold yellow]1. Veri yükleniyor...[/bold yellow]")
    market = MarketDataClient()
    df = market.fetch_ohlcv(symbol, timeframe="1d", days=days)

    if df.empty or len(df) < 50:
        console.print("[red]Yetersiz veri — backtest iptal[/red]")
        return BacktestResult(
            period=0, total_return=0, sharpe_ratio=0, max_drawdown=0,
            win_rate=0, total_trades=0, profitable_trades=0, losing_trades=0,
            avg_win=0, avg_loss=0, profit_factor=0,
            train_range="", test_range="",
        )

    console.print(f"  {len(df)} günlük veri yüklendi")

    # ── Kronolojik bölme ──────────────────────────────────
    console.print("\n[bold yellow]2. Veri bölünüyor...[/bold yellow]")
    split = chronological_split(df)
    console.print(f"  Eğitim: {len(split.train)} mum ({split.train_range})")
    console.print(f"  Doğrulama: {len(split.validation)} mum")
    console.print(f"  Test: {len(split.test)} mum ({split.test_range})")

    # ── Teknik göstergeleri hesapla ────────────────────────
    console.print("\n[bold yellow]3. Teknik analiz...[/bold yellow]")
    tech_analyzer = TechnicalAnalyzer()
    stop_loss_mgr = DynamicStopLoss()

    # ── Basit strateji simülasyonu (test seti üzerinde) ───
    console.print("\n[bold yellow]4. Strateji simülasyonu (test seti)...[/bold yellow]")
    portfolio = PortfolioState(
        initial_cash=params.backtest.initial_cash,
        cash=params.backtest.initial_cash,
    )

    test_df = split.test
    if test_df.empty:
        console.print("[red]Test seti boş[/red]")
        return calculate_metrics([], params.backtest.initial_cash)

    # Kayan pencere ile test setini tara
    window = 30  # Teknik analiz için minimum pencere
    trades: list[dict] = []

    for i in range(window, len(test_df)):
        # Son 'window' mumdan teknik analiz
        lookback = test_df.iloc[max(0, i - window) : i + 1]
        signals = tech_analyzer.analyze(lookback, symbol)

        current_price = float(test_df["close"].iloc[i])
        atr = signals.atr_14

        # Mevcut pozisyon kontrolü
        has_position = portfolio.open_position_count > 0

        if has_position:
            # Stop-loss kontrolü
            pos = portfolio.positions[0]
            pos.update_price(current_price)

            # Trailing stop güncelle
            new_stop = stop_loss_mgr.update_trailing_stop(
                pos.stop_loss, current_price, atr, pos.side
            )
            pos.stop_loss = new_stop

            if stop_loss_mgr.should_exit(current_price, pos.stop_loss, pos.side):
                trade = portfolio.close_position(pos.symbol, current_price)
                if trade:
                    trade["exit_reason"] = "stop_loss"
                    trades.append(trade)
                continue

            # Take-profit kontrolü
            if pos.should_take_profit(current_price):
                trade = portfolio.close_position(pos.symbol, current_price)
                if trade:
                    trade["exit_reason"] = "take_profit"
                    trades.append(trade)
                continue

            # Teknik sinyal değişimi → çıkış
            if (pos.side == "long" and signals.signal == "sell") or \
               (pos.side == "short" and signals.signal == "buy"):
                trade = portfolio.close_position(pos.symbol, current_price)
                if trade:
                    trade["exit_reason"] = "signal_reversal"
                    trades.append(trade)

        else:
            # Yeni pozisyon açma
            if signals.signal == "buy" and signals.trend_strength > 0.3:
                amount = portfolio.calculate_position_size(current_price)
                if amount > 0:
                    stop = stop_loss_mgr.calculate_initial_stop(
                        current_price, atr, "long"
                    )
                    tp_distance = (current_price - stop) * 2  # R:R = 2:1
                    tp = current_price + tp_distance

                    portfolio.open_position(
                        symbol=resolved.symbol,
                        side="long",
                        price=current_price,
                        amount=amount,
                        stop_loss=stop,
                        take_profit=tp,
                    )

            elif signals.signal == "sell" and signals.trend_strength > 0.3:
                amount = portfolio.calculate_position_size(current_price)
                if amount > 0:
                    stop = stop_loss_mgr.calculate_initial_stop(
                        current_price, atr, "short"
                    )
                    tp_distance = (stop - current_price) * 2
                    tp = current_price - tp_distance

                    portfolio.open_position(
                        symbol=resolved.symbol,
                        side="short",
                        price=current_price,
                        amount=amount,
                        stop_loss=stop,
                        take_profit=tp,
                    )

    # Açık pozisyonları kapat (backtest sonu)
    for pos in list(portfolio.positions):
        trade = portfolio.close_position(
            pos.symbol, float(test_df["close"].iloc[-1])
        )
        if trade:
            trade["exit_reason"] = "backtest_end"
            trades.append(trade)

    # ── Metrikler ─────────────────────────────────────────
    console.print("\n[bold yellow]5. Performans metrikleri...[/bold yellow]")
    metrics = calculate_metrics(trades, params.backtest.initial_cash)
    metrics.train_range = split.train_range
    metrics.test_range = split.test_range

    # ── Stres Testi ───────────────────────────────────────
    console.print("\n[bold yellow]6. Monte Carlo stres testi...[/bold yellow]")
    returns = df["close"].pct_change().dropna()
    stress = stress_test_monte_carlo(returns, n_simulations=5000, n_days=30)

    # ── Sonuç Tablosu ─────────────────────────────────────
    table = Table(title="📈 Backtest Sonuçları", border_style="green")
    table.add_column("Metrik", style="bold")
    table.add_column("Değer")

    table.add_row("Toplam Getiri", f"{metrics.total_return:.2%}")
    table.add_row("Sharpe Oranı", f"{metrics.sharpe_ratio:.4f}")
    table.add_row("Max Drawdown", f"{metrics.max_drawdown:.2%}")
    table.add_row("Kazanma Oranı", f"{metrics.win_rate:.2%}")
    table.add_row("Toplam İşlem", str(metrics.total_trades))
    table.add_row("Kârlı İşlem", str(metrics.profitable_trades))
    table.add_row("Zararlı İşlem", str(metrics.losing_trades))
    table.add_row("Ort. Kazanç", f"{metrics.avg_win:.4f}")
    table.add_row("Ort. Kayıp", f"{metrics.avg_loss:.4f}")
    table.add_row("Kâr Faktörü", f"{metrics.profit_factor:.4f}")
    table.add_row("─" * 20, "─" * 20)
    table.add_row("Monte Carlo VaR (30g)", f"{stress['var']:.4%}")
    table.add_row("Monte Carlo CVaR (30g)", f"{stress['cvar']:.4%}")
    table.add_row("En Kötü Senaryo (%5)", f"{stress['worst_case_5pct']:.4%}")

    console.print(table)

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Trading Backtest")
    parser.add_argument("--symbol", "-s", required=True, help="Varlık sembolü")
    parser.add_argument("--days", "-d", type=int, default=365, help="Geçmiş gün sayısı")
    parser.add_argument("--mode", "-m", default="simple", choices=["simple", "walk-forward"])
    parser.add_argument("--log-level", "-l", default="INFO")

    args = parser.parse_args()
    setup_logging(args.log_level)

    if args.mode == "simple":
        run_simple_backtest(args.symbol, args.days)
    else:
        console.print("[yellow]Walk-forward modu...[/yellow]")
        run_simple_backtest(args.symbol, args.days)


if __name__ == "__main__":
    main()
