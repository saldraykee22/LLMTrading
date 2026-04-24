"""
LLM Trading System — Portföy Dengeleme (Rebalancing) Scripti
=============================================================
Mevcut portföyü hedef alokasyonlara göre dengeler.

Kullanım:
    python scripts/run_rebalance.py --dry-run
    python scripts/run_rebalance.py --execute
    python scripts/run_rebalance.py --execute --max-slippage-pct 0.005
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from config.settings import TradingMode, get_trading_params
from execution.exchange_client import ExchangeClient
from execution.order_manager import TradeOrder
from execution.paper_engine import PaperTradingEngine
from risk.portfolio import PortfolioState

console = Console()

ALLOCATION_FILE = PROJECT_ROOT / "data" / "portfolio_allocation.json"


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )


@dataclass
class RebalanceTrade:
    symbol: str
    action: str
    current_value: float
    target_value: float
    current_amount: float
    target_amount: float
    trade_amount: float
    current_price: float
    executed: bool = False
    exec_price: float = 0.0
    exec_amount: float = 0.0
    status: str = "pending"


def load_allocations() -> dict[str, float]:
    if not ALLOCATION_FILE.exists():
        console.print("[bold red]Hedef alokasyon dosyası bulunamadı![/bold red]")
        console.print(f"  Beklenen: {ALLOCATION_FILE}")
        console.print(
            "[yellow]Önce run_portfolio.py ile portföy analizi çalıştırın.[/yellow]"
        )
        sys.exit(1)

    data = json.loads(ALLOCATION_FILE.read_text(encoding="utf-8"))

    allocations = {}
    if "allocations" in data:
        for sym, pct in data["allocations"].items():
            allocations[sym] = float(pct)
    elif "asset_details" in data:
        for sym, details in data["asset_details"].items():
            allocations[sym] = float(details.get("allocation_pct", 0))
    else:
        for key, value in data.items():
            if isinstance(value, dict) and "allocation_pct" in value:
                allocations[key] = float(value["allocation_pct"])
            elif isinstance(value, (int, float)) and key not in (
                "status",
                "reason",
                "cvar_info",
                "all_scores",
            ):
                allocations[key] = float(value)

    if not allocations:
        console.print(
            "[bold red]Alokasyon dosyasında geçerli veri bulunamadı![/bold red]"
        )
        sys.exit(1)

    total = sum(allocations.values())
    if total <= 0 or total > 200:
        console.print(f"[bold red]Geçersiz alokasyon toplamı: %{total:.1f}[/bold red]")
        sys.exit(1)

    if abs(total - 100.0) > 1.0:
        console.print(
            f"[yellow]Uyarı: Alokasyon toplamı %{total:.1f}, normalize ediliyor...[/yellow]"
        )
        for sym in allocations:
            allocations[sym] = (allocations[sym] / total) * 100.0

    return allocations


def compute_rebalance_trades(
    portfolio: PortfolioState,
    allocations: dict[str, float],
    prices: dict[str, float],
) -> list[RebalanceTrade]:
    trades = []
    equity = portfolio.equity

    for symbol, alloc_pct in allocations.items():
        target_value = equity * (alloc_pct / 100.0)
        current_price = prices.get(symbol, 0.0)

        if current_price <= 0:
            console.print(
                f"[yellow]⚠ {symbol} için fiyat bulunamadı, atlanıyor[/yellow]"
            )
            continue

        existing_pos = next(
            (p for p in portfolio.positions if p.symbol == symbol), None
        )

        if existing_pos:
            current_value = existing_pos.current_price * existing_pos.amount
            current_amount = existing_pos.amount
        else:
            current_value = 0.0
            current_amount = 0.0

        diff = target_value - current_value

        if abs(diff) < equity * 0.001:
            continue

        target_amount = target_value / current_price
        trade_amount = abs(diff) / current_price

        action = "buy" if diff > 0 else "sell"

        trades.append(
            RebalanceTrade(
                symbol=symbol,
                action=action,
                current_value=current_value,
                target_value=target_value,
                current_amount=current_amount,
                target_amount=target_amount,
                trade_amount=trade_amount,
                current_price=current_price,
            )
        )

    for pos in portfolio.positions:
        if pos.symbol not in allocations:
            current_value = pos.current_price * pos.amount
            trades.append(
                RebalanceTrade(
                    symbol=pos.symbol,
                    action="sell",
                    current_value=current_value,
                    target_value=0.0,
                    current_amount=pos.amount,
                    target_amount=0.0,
                    trade_amount=pos.amount,
                    current_price=pos.current_price,
                )
            )

    return trades


def fetch_current_prices(
    symbols: list[str], portfolio: PortfolioState
) -> dict[str, float]:
    prices = {}

    for pos in portfolio.positions:
        if pos.current_price > 0:
            prices[pos.symbol] = pos.current_price

    try:
        from data.market_data import MarketDataClient

        market_client = MarketDataClient()
        for symbol in symbols:
            if symbol in prices:
                continue
            try:
                df = market_client.fetch_ohlcv(symbol, days=1)
                if not df.empty:
                    prices[symbol] = float(df["close"].iloc[-1])
            except Exception as e:
                console.print(f"  [dim]{symbol} fiyatı alınamadı: {e}[/dim]")
        market_client.close()
    except Exception as e:
        console.print(f"  [dim]Fiyat çekme hatası: {e}[/dim]")

    return prices


def execute_trade(
    trade: RebalanceTrade,
    exchange_client: ExchangeClient,
    paper_engine: PaperTradingEngine | None,
    max_slippage_pct: float,
) -> dict[str, Any]:
    order = TradeOrder(
        symbol=trade.symbol,
        action=trade.action,
        order_type="market",
        amount=trade.trade_amount,
        stop_loss=0.0,
        take_profit=0.0,
        reasoning=f"Rebalancing trade: {trade.action} to reach target allocation",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    exec_result = exchange_client.execute_order(order, trade.current_price)

    if exec_result.get("status") in ("filled", "closed", "open"):
        trade.executed = True
        trade.exec_price = float(exec_result.get("price") or trade.current_price)
        trade.exec_amount = float(exec_result.get("amount") or trade.trade_amount)
        trade.status = "filled"
    else:
        trade.status = exec_result.get("status", "failed")
        trade.exec_price = trade.current_price
        trade.exec_amount = 0.0

    return exec_result


def update_portfolio_after_trade(
    portfolio: PortfolioState, trade: RebalanceTrade, exec_result: dict[str, Any]
) -> None:
    if trade.action == "buy" and trade.exec_amount > 0:
        existing = next(
            (p for p in portfolio.positions if p.symbol == trade.symbol), None
        )
        if not existing:
            portfolio.open_position(
                symbol=trade.symbol,
                side="long",
                price=trade.exec_price,
                amount=trade.exec_amount,
            )
        else:
            total_amount = existing.amount + trade.exec_amount
            existing.entry_price = (
                existing.entry_price * existing.amount
                + trade.exec_price * trade.exec_amount
            ) / total_amount
            existing.amount = total_amount
            existing.current_price = trade.exec_price
            portfolio.cash -= trade.exec_price * trade.exec_amount

    elif trade.action == "sell" and trade.exec_amount > 0:
        portfolio.close_position(trade.symbol, trade.exec_price)


def run_rebalance(
    execute: bool = False,
    dry_run: bool = False,
    max_slippage_pct: float = 0.01,
) -> dict:
    params = get_trading_params()

    portfolio = PortfolioState.load_from_file()
    portfolio.reset_daily_pnl_if_needed()

    allocations = load_allocations()

    console.print(
        Panel(
            f"[bold cyan]Portföy Dengeleme (Rebalancing)[/bold cyan]\n"
            f"Mod: {'EXECUTE' if execute else 'DRY-RUN'}\n"
            f"Maks Slipaj: %{max_slippage_pct * 100:.2f}\n"
            f"Özvarlık: ${portfolio.equity:,.2f}\n"
            f"Nakit: ${portfolio.cash:,.2f}\n"
            f"Açık Pozisyon: {portfolio.open_position_count}\n"
            f"Hedef Varlık: {len(allocations)}\n"
            f"Zaman: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            title="Dengeleme Başlatılıyor",
            border_style="cyan",
        )
    )

    console.print("\n[bold yellow]Hedef Alokasyonlar:[/bold yellow]")
    alloc_table = Table(show_header=True, border_style="cyan")
    alloc_table.add_column("Sembol", style="bold")
    alloc_table.add_column("Ağırlık", justify="right")
    alloc_table.add_column("Hedef Değer", justify="right")

    for sym, pct in sorted(allocations.items(), key=lambda x: x[1], reverse=True):
        target_val = portfolio.equity * (pct / 100.0)
        alloc_table.add_row(sym, f"{pct:.1f}%", f"${target_val:,.2f}")

    console.print(alloc_table)

    all_symbols = list(allocations.keys())
    for pos in portfolio.positions:
        if pos.symbol not in all_symbols:
            all_symbols.append(pos.symbol)

    console.print("\n[bold yellow]Fiyatlar Alınıyor...[/bold yellow]")
    prices = fetch_current_prices(all_symbols, portfolio)

    if not prices:
        console.print("[bold red]Hiçbir fiyat alınamadı, dengeleme iptal![/bold red]")
        return {"status": "failed", "reason": "no_prices"}

    for sym, price in prices.items():
        console.print(f"  {sym}: ${price:,.4f}")

    trades = compute_rebalance_trades(portfolio, allocations, prices)

    if not trades:
        console.print("\n[bold green]Portföy zaten hedef alokasyonlarda![/bold green]")
        return {"status": "already_balanced"}

    console.print(
        f"\n[bold yellow]{len(trades)} dengeleme işlemi bulundu:[/bold yellow]"
    )

    planned_table = Table(show_header=True, border_style="yellow")
    planned_table.add_column("#", style="dim")
    planned_table.add_column("Sembol", style="bold")
    planned_table.add_column("Aksiyon", justify="center")
    planned_table.add_column("Mevcut Değer", justify="right")
    planned_table.add_column("Hedef Değer", justify="right")
    planned_table.add_column("Fark", justify="right")
    planned_table.add_column("İşlem Miktarı", justify="right")
    planned_table.add_column("Fiyat", justify="right")

    for i, trade in enumerate(trades, 1):
        action_style = "green" if trade.action == "buy" else "red"
        diff = trade.target_value - trade.current_value
        diff_style = "green" if diff > 0 else "red"
        planned_table.add_row(
            str(i),
            trade.symbol,
            f"[{action_style}]{trade.action.upper()}[/{action_style}]",
            f"${trade.current_value:,.2f}",
            f"${trade.target_value:,.2f}",
            f"[{diff_style}]${diff:+,.2f}[/{diff_style}]",
            f"{trade.trade_amount:.6f}",
            f"${trade.current_price:,.4f}",
        )

    console.print(planned_table)

    if dry_run:
        console.print(
            "\n[bold cyan]DRY-RUN modu — İşlemler simüle ediliyor...[/bold cyan]"
        )

        sim_table = Table(show_header=True, border_style="cyan")
        sim_table.add_column("#", style="dim")
        sim_table.add_column("Sembol", style="bold")
        sim_table.add_column("Aksiyon", justify="center")
        sim_table.add_column("Miktar", justify="right")
        sim_table.add_column("Tahmini Fiyat", justify="right")
        sim_table.add_column("Tahmini Maliyet", justify="right")
        sim_table.add_column("Nakit Etkisi", justify="right")

        for i, trade in enumerate(trades, 1):
            slippage = trade.current_price * max_slippage_pct
            if trade.action == "buy":
                est_price = trade.current_price + slippage
            else:
                est_price = trade.current_price - slippage

            est_cost = est_price * trade.trade_amount
            cash_impact = -est_cost if trade.action == "buy" else est_cost

            sim_table.add_row(
                str(i),
                trade.symbol,
                f"[{'green' if trade.action == 'buy' else 'red'}]{trade.action.upper()}[/{'green' if trade.action == 'buy' else 'red'}]",
                f"{trade.trade_amount:.6f}",
                f"${est_price:,.4f}",
                f"${est_cost:,.2f}",
                f"[{'red' if cash_impact < 0 else 'green'}]${cash_impact:+,.2f}[/{'red' if cash_impact < 0 else 'green'}]",
            )

        console.print(sim_table)
        console.print(
            f"\n[dim]Simülasyon tamamlandı — {len(trades)} işlem, "
            f"gerçek yürütme yapılmadı[/dim]"
        )

        return {
            "status": "dry_run",
            "trades_planned": len(trades),
            "trades": [
                {
                    "symbol": t.symbol,
                    "action": t.action,
                    "amount": t.trade_amount,
                    "price": t.current_price,
                    "current_value": t.current_value,
                    "target_value": t.target_value,
                }
                for t in trades
            ],
        }

    if not execute:
        console.print(
            "\n[dim]--execute bayrağı olmadan işlem yürütülmedi. "
            "--dry-run veya --execute kullanın.[/dim]"
        )
        return {"status": "no_action"}

    console.print("\n[bold red]İşlemler Yürütülüyor...[/bold red]")

    exchange_client = ExchangeClient()
    paper_engine = None
    if params.execution.mode == TradingMode.PAPER:
        paper_engine = PaperTradingEngine(
            initial_cash=portfolio.cash,
            slippage_pct=max_slippage_pct,
            commission_pct=params.execution.commission_pct,
        )

    executed_count = 0
    failed_count = 0
    total_volume = 0.0

    for i, trade in enumerate(trades, 1):
        console.print(
            f"\n  [{i}/{len(trades)}] {trade.action.upper()} {trade.symbol}: "
            f"{trade.trade_amount:.6f} @ ${trade.current_price:,.4f}"
        )

        if params.execution.mode == TradingMode.PAPER and paper_engine:
            order = TradeOrder(
                symbol=trade.symbol,
                action=trade.action,
                order_type="market",
                amount=trade.trade_amount,
                stop_loss=0.0,
                take_profit=0.0,
                reasoning=f"Rebalancing: {trade.action} to reach target allocation",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            exec_result = paper_engine.execute_order(order, trade.current_price)

            if exec_result.get("status") in ("filled", "closed", "open"):
                trade.executed = True
                trade.exec_price = float(
                    exec_result.get("price") or trade.current_price
                )
                trade.exec_amount = float(
                    exec_result.get("amount") or trade.trade_amount
                )
                trade.status = "filled"
                executed_count += 1
                total_volume += trade.exec_price * trade.exec_amount
                console.print(
                    f"    [green]DOLDU[/green] @ ${trade.exec_price:,.4f} "
                    f"({trade.exec_amount:.6f})"
                )
            else:
                trade.status = exec_result.get("status", "failed")
                failed_count += 1
                console.print(
                    f"    [red]BAŞARISIZ[/red]: {exec_result.get('message', 'Bilinmeyen hata')}"
                )
        else:
            exec_result = execute_trade(
                trade, exchange_client, paper_engine, max_slippage_pct
            )

            if trade.executed:
                update_portfolio_after_trade(portfolio, trade, exec_result)
                executed_count += 1
                total_volume += trade.exec_price * trade.exec_amount
                console.print(
                    f"    [green]DOLDU[/green] @ ${trade.exec_price:,.4f} "
                    f"({trade.exec_amount:.6f})"
                )
            else:
                failed_count += 1
                console.print(
                    f"    [red]BAŞARISIZ[/red]: {exec_result.get('message', 'Bilinmeyen hata')}"
                )

    console.print("\n[bold yellow]Dengeleme Özeti:[/bold yellow]")

    summary_table = Table(show_header=True, border_style="green")
    summary_table.add_column("#", style="dim")
    summary_table.add_column("Sembol", style="bold")
    summary_table.add_column("Aksiyon", justify="center")
    summary_table.add_column("Planlanan", justify="right")
    summary_table.add_column("Gerçekleşen", justify="right")
    summary_table.add_column("Planlanan Değer", justify="right")
    summary_table.add_column("Gerçekleşen Değer", justify="right")
    summary_table.add_column("Durum", justify="center")

    for i, trade in enumerate(trades, 1):
        planned_val = trade.current_price * trade.trade_amount
        if trade.executed:
            exec_val = trade.exec_price * trade.exec_amount
            status_style = "green"
            status_text = "DOLDU"
        else:
            exec_val = 0.0
            status_style = "red"
            status_text = trade.status.upper()

        summary_table.add_row(
            str(i),
            trade.symbol,
            f"[{'green' if trade.action == 'buy' else 'red'}]{trade.action.upper()}[/{'green' if trade.action == 'buy' else 'red'}]",
            f"{trade.trade_amount:.6f}",
            f"{trade.exec_amount:.6f}" if trade.executed else "-",
            f"${planned_val:,.2f}",
            f"${exec_val:,.2f}" if trade.executed else "-",
            f"[{status_style}]{status_text}[/{status_style}]",
        )

    console.print(summary_table)

    console.print(
        f"\n  Toplam Planlanan: {len(trades)} işlem"
        f"\n  Başarılı: {executed_count}"
        f"\n  Başarısız: {failed_count}"
        f"\n  Toplam Hacim: ${total_volume:,.2f}"
    )

    portfolio.update_drawdown()
    portfolio.save_to_file()

    console.print(f"\n[dim]Portföy kaydedildi (equity: ${portfolio.equity:,.2f})[/dim]")

    return {
        "status": "completed",
        "trades_planned": len(trades),
        "trades_executed": executed_count,
        "trades_failed": failed_count,
        "total_volume": total_volume,
        "trades": [
            {
                "symbol": t.symbol,
                "action": t.action,
                "planned_amount": t.trade_amount,
                "exec_amount": t.exec_amount,
                "exec_price": t.exec_price,
                "status": t.status,
            }
            for t in trades
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM Trading Portföy Dengeleme (Rebalancing)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="İşlemleri simüle et, yürütme",
    )
    parser.add_argument(
        "--execute",
        "-x",
        action="store_true",
        help="İşlemleri gerçekten yürüt",
    )
    parser.add_argument(
        "--max-slippage-pct",
        type=float,
        default=0.01,
        help="Maksimum slipaj oranı (varsayılan: 0.01 = %%1)",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        default="INFO",
        help="Log seviyesi",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        console.print(
            "[bold yellow]Hiçbir mod belirtilmedi. --dry-run veya --execute kullanın.[/bold yellow]"
        )
        parser.print_help()
        sys.exit(1)

    if args.dry_run and args.execute:
        console.print(
            "[bold red]--dry-run ve --execute aynı anda kullanılamaz![/bold red]"
        )
        sys.exit(1)

    setup_logging(args.log_level)

    result = run_rebalance(
        execute=args.execute,
        dry_run=args.dry_run,
        max_slippage_pct=args.max_slippage_pct,
    )

    console.print(f"\n[green]Dengeleme tamamlandı ({result['status']})[/green]")


if __name__ == "__main__":
    main()
