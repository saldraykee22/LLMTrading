"""
LLM Trading System — Backtest Çalıştırma Betiği
==================================================
Geçmiş veriler üzerinde strateji testi yapar.

Kullanım:
    python scripts/run_backtest.py --symbol BTC/USDT --days 365
    python scripts/run_backtest.py --symbol AAPL --mode walk-forward
    python scripts/run_backtest.py --symbol BTC/USDT --timeframe 1h --days 90
    python scripts/run_backtest.py --symbol BTC/USDT --mode llm --cache --provider deepseek
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Windows console encoding fix
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from config.settings import get_trading_params
from data.market_data import MarketDataClient
from data.symbol_resolver import resolve_symbol
from models.technical_analyzer import TechnicalAnalyzer
from backtest.walk_forward import (
    BacktestResult,
    calculate_metrics,
    chronological_split,
    rolling_walk_forward,
)
from risk.cvar_optimizer import stress_test_monte_carlo
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
    timeframe: str = "1d",
) -> BacktestResult:
    """
    Basit teknik strateji backtesti.

    Teknik sinyallerle birleştirilerek sınanır.
    """
    params = get_trading_params()
    resolved = resolve_symbol(symbol)

    # ASCII-safe title/content ensures the test-backtest flow runs reliably.
    console.print(
        Panel(
            f"[bold cyan]Backtest[/bold cyan]\n"
            f"Symbol: {resolved.symbol}\n"
            f"Timeframe: {timeframe}\n"
            f"Duration: {days} days\n"
            f"Capital: {params.backtest.initial_cash} USDT",
            title="Backtest",
            border_style="cyan",
        )
    )

    # -- Data Fetching ---------------------------------------
    console.print("\n[bold yellow]1. Loading data...[/bold yellow]")
    market = MarketDataClient()
    df = market.fetch_ohlcv(symbol, timeframe=timeframe, days=days)

    if df.empty or len(df) < 50:
        console.print(
            f"[red]Insufficient data ({len(df)} candles) - backtest aborted[/red]"
        )
        return BacktestResult(
            period=0,
            total_return=0,
            sharpe_ratio=0,
            max_drawdown=0,
            win_rate=0,
            total_trades=0,
            profitable_trades=0,
            losing_trades=0,
            avg_win=0,
            avg_loss=0,
            profit_factor=0,
            train_range="",
            test_range="",
        )

    console.print(f"  {len(df)} candles loaded ({timeframe})")

    # -- Chronological Split ---------------------------------
    console.print("\n[bold yellow]2. Splitting data...[/bold yellow]")
    split = chronological_split(df)
    console.print(f"  Train: {len(split.train)} candles ({split.train_range})")
    console.print(f"  Validation: {len(split.validation)} candles")
    console.print(f"  Test: {len(split.test)} candles ({split.test_range})")

    # -- Technical Analysis ----------------------------------
    console.print("\n[bold yellow]3. Technical analysis...[/bold yellow]")
    tech_analyzer = TechnicalAnalyzer()
    stop_loss_mgr = DynamicStopLoss()

    # -- Strategy Simulation ---------------------------------
    console.print("\n[bold yellow]4. Strategy simulation (test set)...[/bold yellow]")
    portfolio = PortfolioState(
        initial_cash=params.backtest.initial_cash,
        cash=params.backtest.initial_cash,
    )

    test_df = split.test
    if test_df.empty:
        console.print("[red]Test set is empty[/red]")
        return calculate_metrics([], params.backtest.initial_cash)

    window = params.limits.backtest_lookback_window
    trades: list[dict] = []

    for i in range(window, len(test_df)):
        lookback = test_df.iloc[max(0, i - window) : i + 1]
        signals = tech_analyzer.analyze(lookback, symbol)
        current_price = float(test_df["close"].iloc[i])
        atr = signals.atr_14

        has_position = portfolio.open_position_count > 0

        if has_position:
            pos = portfolio.positions[0]
            pos.update_price(current_price)

            high_price = float(test_df["high"].iloc[i])
            low_price = float(test_df["low"].iloc[i])

            sl_test_price = low_price
            tp_test_price = high_price

            # 1. Stop-Loss Kontrolü (Mum içi ilk öncelik)
            if stop_loss_mgr.should_exit(sl_test_price, pos.stop_loss):
                trade = portfolio.close_position(pos.symbol, pos.stop_loss)
                if trade:
                    trade["exit_reason"] = "stop_loss"
                    trades.append(trade)
                continue

            # 2. Take-Profit Kontrolü (Mum içi)
            if pos.should_take_profit(tp_test_price):
                trade = portfolio.close_position(pos.symbol, pos.take_profit)
                if trade:
                    trade["exit_reason"] = "take_profit"
                    trades.append(trade)
                continue

            # 3. Kapanışta Sinyal Tersine Dönme İhtimali
            if pos.side == "long" and signals.signal == "sell":
                trade = portfolio.close_position(pos.symbol, current_price)
                if trade:
                    trade["exit_reason"] = "signal_reversal"
                    trades.append(trade)
                continue

            # 4. Trailing Stop Güncellemesi
            new_stop = stop_loss_mgr.update_trailing_stop(
                pos.stop_loss, current_price, atr
            )
            pos.stop_loss = new_stop
        else:
            if signals.signal == "buy" and signals.trend_strength > 0.3:
                amount = portfolio.calculate_position_size(current_price)
                if amount > 0:
                    stop = stop_loss_mgr.calculate_initial_stop(current_price, atr)
                    tp = current_price + (current_price - stop) * 2
                    portfolio.open_position(
                        symbol=resolved.symbol,
                        side="long",
                        price=current_price,
                        amount=amount,
                        stop_loss=stop,
                        take_profit=tp,
                    )

    # Close open positions
    for pos in list(portfolio.positions):
        trade = portfolio.close_position(pos.symbol, float(test_df["close"].iloc[-1]))
        if trade:
            trade["exit_reason"] = "backtest_end"
            trades.append(trade)

    # -- Metrics ---------------------------------------------
    console.print("\n[bold yellow]5. Performance metrics...[/bold yellow]")
    metrics = calculate_metrics(trades, params.backtest.initial_cash)
    metrics.train_range = split.train_range
    metrics.test_range = split.test_range

    # -- Stress Test -----------------------------------------
    console.print("\n[bold yellow]6. Monte Carlo stress test...[/bold yellow]")
    returns = df["close"].pct_change().dropna()
    stress = stress_test_monte_carlo(
        returns, n_simulations=params.limits.monte_carlo_simulations, n_days=30
    )

    # -- Result Table ----------------------------------------
    table = Table(title="Backtest Results", border_style="green")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Total Return", f"{metrics.total_return:.2%}")
    table.add_row("Sharpe Ratio", f"{metrics.sharpe_ratio:.4f}")
    table.add_row("Max Drawdown", f"{metrics.max_drawdown:.2%}")
    table.add_row("Monte Carlo CVaR (30g)", f"{stress['cvar']:.4%}")
    table.add_row("En Kötü Senaryo (%5)", f"{stress['worst_case_5pct']:.4%}")

    console.print(table)

    return metrics


def run_walkforward_backtest(
    symbol: str,
    days: int = 365,
    timeframe: str = "1d",
) -> list[BacktestResult]:
    """
    Rolling walk-forward doğrulama.

    Veriyi kayan pencerelere böler, her pencerede ayrı backtest yapar.
    Overfitting tespiti için kullanılır.
    """
    params = get_trading_params()
    resolved = resolve_symbol(symbol)

    console.print(
        Panel(
            f"[bold cyan]Walk-Forward Backtest[/bold cyan]\n"
            f"Symbol: {resolved.symbol}\n"
            f"Timeframe: {timeframe}\n"
            f"Duration: {days} days\n"
            f"Capital: {params.backtest.initial_cash} USDT",
            title="Walk-Forward Validation",
            border_style="cyan",
        )
    )

    # -- Data Fetching ---------------------------------------
    console.print("\n[bold yellow]1. Loading data...[/bold yellow]")
    market = MarketDataClient()
    df = market.fetch_ohlcv(symbol, timeframe=timeframe, days=days)

    if df.empty or len(df) < 100:
        console.print(
            f"[red]Insufficient data ({len(df)} candles) - min 100 required for walk-forward[/red]"
        )
        return []

    console.print(f"  {len(df)} candles loaded ({timeframe})")

    # -- Walk-forward splits ---------------------------------
    console.print("\n[bold yellow]2. Creating walk-forward windows...[/bold yellow]")
    train_window = int(len(df) * 0.6)
    test_window = max(int(len(df) * 0.1), 30)

    splits = rolling_walk_forward(df, train_window, test_window)
    console.print(f"  {len(splits)} periods created")

    # -- Backtest in each period -----------------------------
    tech_analyzer = TechnicalAnalyzer()
    stop_loss_mgr = DynamicStopLoss()
    all_results: list[BacktestResult] = []

    for idx, split in enumerate(splits):
        console.print(f"\n[bold]-- Period {idx + 1}/{len(splits)} --[/bold]")
        console.print(f"  Train: {split.train_range}")
        console.print(f"  Test: {split.test_range}")

        test_df = split.test
        if test_df.empty or len(test_df) < 30:
            console.print("  [dim]Test set too short, skipping[/dim]")
            continue

        portfolio = PortfolioState(
            initial_cash=params.backtest.initial_cash,
            cash=params.backtest.initial_cash,
        )

        window = params.limits.backtest_lookback_window
        trades: list[dict] = []

        for i in range(window, len(test_df)):
            lookback = test_df.iloc[max(0, i - window) : i + 1]
            signals = tech_analyzer.analyze(lookback, symbol)
            current_price = float(test_df["close"].iloc[i])
            atr = signals.atr_14

            has_position = portfolio.open_position_count > 0

            if has_position:
                pos = portfolio.positions[0]
                pos.update_price(current_price)

                high_price = float(test_df["high"].iloc[i])
                low_price = float(test_df["low"].iloc[i])

                sl_test_price = low_price
                tp_test_price = high_price

                # 1. Stop-Loss Kontrolü (Mum içi ilk öncelik)
                if stop_loss_mgr.should_exit(sl_test_price, pos.stop_loss):
                    trade = portfolio.close_position(pos.symbol, pos.stop_loss)
                    if trade:
                        trade["exit_reason"] = "stop_loss"
                        trades.append(trade)
                    continue

                # 2. Take-Profit Kontrolü (Mum içi)
                if pos.should_take_profit(tp_test_price):
                    trade = portfolio.close_position(pos.symbol, pos.take_profit)
                    if trade:
                        trade["exit_reason"] = "take_profit"
                        trades.append(trade)
                    continue

                # 3. Kapanışta Sinyal Tersine Dönme İhtimali
                if pos.side == "long" and signals.signal == "sell":
                    trade = portfolio.close_position(pos.symbol, current_price)
                    if trade:
                        trade["exit_reason"] = "signal_reversal"
                        trades.append(trade)
                    continue

                # 4. Trailing Stop Güncellemesi
                new_stop = stop_loss_mgr.update_trailing_stop(
                    pos.stop_loss, current_price, atr
                )
                pos.stop_loss = new_stop
            else:
                if signals.signal == "buy" and signals.trend_strength > 0.3:
                    amount = portfolio.calculate_position_size(current_price)
                    if amount > 0:
                        stop = stop_loss_mgr.calculate_initial_stop(current_price, atr)
                        tp = current_price + (current_price - stop) * 2
                        portfolio.open_position(
                            symbol=resolved.symbol,
                            side="long",
                            price=current_price,
                            amount=amount,
                            stop_loss=stop,
                            take_profit=tp,
                        )

        # Close open positions
        for pos in list(portfolio.positions):
            trade = portfolio.close_position(
                pos.symbol, float(test_df["close"].iloc[-1])
            )
            if trade:
                trade["exit_reason"] = "backtest_end"
                trades.append(trade)

        metrics = calculate_metrics(
            trades, params.backtest.initial_cash, period=idx + 1
        )
        metrics.train_range = split.train_range
        metrics.test_range = split.test_range
        all_results.append(metrics)

        console.print(
            f"  Return: {metrics.total_return:.2%} | "
            f"Sharpe: {metrics.sharpe_ratio:.2f} | "
            f"Win Rate: {metrics.win_rate:.2%} | "
            f"Trades: {metrics.total_trades}"
        )

    # -- Summary ---------------------------------------------
    if all_results:
        avg_return = sum(r.total_return for r in all_results) / len(all_results)
        avg_sharpe = sum(r.sharpe_ratio for r in all_results) / len(all_results)
        avg_winrate = sum(r.win_rate for r in all_results) / len(all_results)
        total_trades = sum(r.total_trades for r in all_results)

        console.print("\n" + "=" * 50)
        console.print(f"[bold]Walk-Forward Summary ({len(all_results)} periods)[/bold]")
        console.print(f"  Avg Return: {avg_return:.2%}")
        console.print(f"  Avg Sharpe: {avg_sharpe:.4f}")
        console.print(f"  Avg Win Rate: {avg_winrate:.2%}")
        console.print(f"  Total Trades: {total_trades}")
        console.print("=" * 50)

        table = Table(title="Period Details", border_style="cyan")
        table.add_column("#", style="bold")
        table.add_column("Return")
        table.add_column("Sharpe")
        table.add_column("Win Rate")
        table.add_column("Max DD")
        table.add_column("Trades")
        for r in all_results:
            table.add_row(
                str(r.period),
                f"{r.total_return:.2%}",
                f"{r.sharpe_ratio:.4f}",
                f"{r.win_rate:.2%}",
                f"{r.max_drawdown:.2%}",
                str(r.total_trades),
            )
        console.print(table)

    return all_results


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Trading Backtest")
    parser.add_argument("--symbol", "-s", required=True, help="Varlık sembolü")
    parser.add_argument("--days", "-d", type=int, default=90, help="Geçmiş gün sayısı")
    parser.add_argument(
        "--timeframe",
        "-t",
        default="1h",
        choices=["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"],
        help="Mum periyodu",
    )
    parser.add_argument(
        "--mode",
        "-m",
        default="llm",
        choices=["simple", "walk-forward", "llm"],
        help="Backtest modu",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        default=True,
        help="LLM cache kullan (önerilen, default: aktif)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_false",
        dest="cache",
        help="Cache kapat",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Cache temizle ve yeniden başla",
    )
    parser.add_argument(
        "--provider",
        "-p",
        default="deepseek",
        choices=["openrouter", "deepseek", "ollama"],
        help="LLM sağlayıcı",
    )
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=10000,
        help="Başlangıç sermayesi",
    )
    parser.add_argument("--log-level", "-l", default="INFO")

    args = parser.parse_args()
    setup_logging(args.log_level)

    if args.mode == "llm":
        # LLM backtest with full pipeline
        from backtest.llm_backtest import LLMBacktestEngine, run_llm_backtest
        
        console.print(
            Panel(
                f"[bold cyan]LLM Backtest (Full Pipeline)[/bold cyan]\n"
                f"Symbol: {args.symbol}\n"
                f"Timeframe: {args.timeframe}\n"
                f"Days: {args.days}\n"
                f"Provider: {args.provider}\n"
                f"Cache: {'Enabled' if args.cache else 'Disabled'}\n"
                f"Initial Cash: ${args.initial_cash:,.2f}",
                title="🤖 LLM Backtest Mode",
                border_style="cyan",
            )
        )
        
        if args.clear_cache:
            from backtest.backtest_cache import BacktestCache
            cache = BacktestCache()
            count = cache.clear(args.symbol)
            console.print(f"[green]Cleared {count} cache entries[/green]\n")
        
        # Run async backtest
        engine = LLMBacktestEngine(
            symbol=args.symbol,
            initial_cash=args.initial_cash,
            cache_enabled=args.cache,
            provider=args.provider,
            timeframe=args.timeframe,
        )
        
        # Fetch data (from existing market data client)
        from data.market_data import MarketDataClient
        market_client = MarketDataClient()
        df = market_client.fetch_ohlcv(args.symbol, timeframe=args.timeframe, days=args.days)
        
        if df.empty or len(df) < 10:
            console.print(f"[red]Insufficient data ({len(df)} bars) - minimum 10 bars required[/red]")
            sys.exit(1)
            
        result = asyncio.run(engine.run_full_backtest(df, days=args.days))
        
        # Save results
        report_path = engine.save_results(result)
        console.print(f"\n[bold green]✅ Report saved to: [/bold green]{report_path}")
        
        if "error" in result:
            console.print(f"[red]Backtest failed: {result['error']}[/red]")
            sys.exit(1)
    
    elif args.mode == "simple":
        run_simple_backtest(args.symbol, args.days, args.timeframe)
    else:
        run_walkforward_backtest(args.symbol, args.days, args.timeframe)


if __name__ == "__main__":
    main()
