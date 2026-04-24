"""
Aegis Intelligence Terminal - Command Line Interface (CLI)
=========================================================
Global standard command line interface for Aegis Terminal.

Usage:
    aegis --help
    aegis health
    aegis run --symbol BTC/USDT
    aegis backtest --symbol BTC/USDT --days 90
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_header(header: str) -> None:
    """Print header."""
    width = 70
    print("\n" + "=" * width)
    print(f"  {header}".center(width))
    print("=" * width + "\n")


def print_section(section_name: str) -> None:
    """Print section header."""
    print(f"\n> {section_name}")
    print("-" * 50)


def cmd_health(args) -> int:
    """System health check."""
    from scripts.health_check import main as health_main
    return health_main()


def cmd_run(args) -> int:
    """Run trading bot."""
    import subprocess
    
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_live.py"),
        "--symbol", args.symbol,
        "--interval", args.interval,
    ]
    
    if args.watchdog:
        cmd.append("--watchdog")
    
    if args.execute:
        cmd.append("--execute")
    
    if args.auto_scan:
        cmd.append("--auto-scan")
    
    if args.max_cycles:
        cmd.extend(["--max-cycles", str(args.max_cycles)])
    
    if args.model:
        cmd.extend(["--model", args.model])
    
    try:
        subprocess.run(cmd, check=True)
        return 0
    except KeyboardInterrupt:
        print("\n\n[INFO] Stopped by user.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Bot error: {e}")
        return 1


def cmd_backtest(args) -> int:
    """Run backtest."""
    import subprocess
    
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_backtest.py"),
        "--symbol", args.symbol,
        "--days", str(args.days),
    ]
    
    try:
        subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Backtest error: {e}")
        return 1


def cmd_portfolio(args) -> int:
    """Portfolio status."""
    import json
    
    print_header("PORTFOLIO STATUS")
    
    portfolio_file = PROJECT_ROOT / "data" / "portfolio_state.json"
    
    if not portfolio_file.exists():
        print("[INFO] No open positions yet.")
        return 0
    
    try:
        with open(portfolio_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        print(f"Initial Cash:    ${data.get('initial_cash', 0):,.2f}")
        print(f"Current Cash:    ${data.get('cash', 0):,.2f}")
        print(f"Total Equity:    ${data.get('equity', 0):,.2f}")
        print(f"Total P&L:       ${data.get('total_pnl', 0):,.2f}")
        print(f"Daily P&L:       ${data.get('daily_pnl', 0):,.2f}")
        print(f"Max Drawdown:    {data.get('current_drawdown', 0):.2%}")
        
        positions = data.get("positions", [])
        if positions:
            print_section(f"OPEN POSITIONS ({len(positions)})")
            for pos in positions:
                print(f"\n  {pos.get('symbol')}")
                print(f"    Side:        {pos.get('side', 'long').upper()}")
                print(f"    Entry:       ${pos.get('entry_price', 0):,.2f}")
                print(f"    Amount:      {pos.get('amount', 0):.6f}")
                print(f"    Unrealized:  ${pos.get('unrealized_pnl', 0):,.2f}")
        
        print()
        return 0
    except Exception as e:
        print(f"[ERROR] Could not read portfolio: {e}")
        return 1


def cmd_test(args) -> int:
    """Run test suite."""
    import subprocess
    
    print_header("TEST SUITE")
    
    cmd = [
        sys.executable,
        "-m", "pytest",
        str(PROJECT_ROOT / "tests" / "test_integration.py"),
        "-v",
        "--tb=short",
    ]
    
    if args.verbose:
        cmd.append("-s")
    
    try:
        subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Tests failed: {e}")
        return 1


def cmd_logs(args) -> int:
    """Show logs."""
    print_header("LATEST LOG LINES")
    
    log_file = PROJECT_ROOT / "logs" / "trading.log"
    
    if not log_file.exists():
        print("[INFO] No log file created yet.")
        return 0
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        n = args.lines or 50
        for line in lines[-n:]:
            print(line.strip())
        
        return 0
    except Exception as e:
        print(f"[ERROR] Could not read logs: {e}")
        return 1


def cmd_scan(args) -> int:
    """Market scan."""
    from data.scanner import MarketScanner
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    print_header("MARKET SCAN")
    
    scanner = MarketScanner()
    
    print_section("Scanning Candidates...")
    try:
        candidates = scanner.get_candidates()
    except Exception as e:
        console.print(f"[red]X Scan error: {e}[/red]")
        return 1
    
    if not candidates:
        console.print("[yellow]No candidates found matching criteria.[/yellow]")
        return 0
    
    console.print(f"[green]V {len(candidates)} candidates found.[/green]")
    
    print_section("Top Candidates")
    
    table = Table(title="Recommended Assets", show_header=True, header_style="bold cyan")
    table.add_column("Symbol", style="bold")
    table.add_column("Price", justify="right")
    table.add_column("24h Volume", justify="right")
    table.add_column("24h Change", justify="right")
    table.add_column("Quality Score", justify="right")
    
    for cand in candidates[:10]:
        if isinstance(cand, dict):
            symbol = cand.get("symbol", "N/A")
            price = cand.get("price", 0)
            volume = cand.get("volume_24h", 0)
            change = cand.get("change_24h", 0)
            score = cand.get("quality_score", 0)
            
            table.add_row(
                symbol,
                f"${price:,.4f}",
                f"${volume:,.0f}",
                f"{change:+.2f}%",
                f"{score:.1f}",
            )
    
    console.print(table)
    print()
    
    return 0


def cmd_status(args) -> int:
    """System status."""
    console = Console()
    
    print_header("SYSTEM STATUS")
    
    # Circuit Breaker
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb_status = cb.get_status()
    
    panel_data = []
    panel_data.append(f"Circuit Breaker: {'[red]HALTED[/red]' if cb_status.get('halted') else '[green]ACTIVE[/green]'}")
    if cb_status.get('halt_reason'):
        panel_data.append(f"  Reason: {cb_status['halt_reason']}")
    panel_data.append(f"Consecutive Losses: {cb_status.get('consecutive_losses', 0)}")
    panel_data.append(f"Consecutive LLM Errors: {cb_status.get('consecutive_llm_errors', 0)}")
    
    console.print(Panel("\n".join(panel_data), title="Circuit Breaker", border_style="red" if cb_status.get('halted') else "green"))
    
    # Portfolio
    from risk.portfolio import PortfolioState
    portfolio = PortfolioState.load_from_file()
    
    port_table = Table(title="Portfolio Summary", show_header=False)
    port_table.add_column("Metric", style="bold")
    port_table.add_column("Value")
    
    port_table.add_row("Equity", f"${portfolio.equity:,.2f}")
    port_table.add_row("Cash", f"${portfolio.cash:,.2f}")
    port_table.add_row("Open Positions", str(portfolio.open_position_count))
    port_table.add_row("Total P&L", f"${portfolio.total_pnl:,.2f}")
    port_table.add_row("Daily P&L", f"${portfolio.daily_pnl:,.2f}")
    port_table.add_row("Drawdown", f"{portfolio.current_drawdown:.2%}")
    
    console.print(port_table)
    print()
    
    return 0


def cmd_fallbacks(args) -> int:
    """Show latest fallback logs."""
    console = Console()
    
    from data.fallback_store import get_fallback_store
    store = get_fallback_store()
    fallbacks = store.get_fallbacks(limit=args.limit)
    summary = store.get_fallback_summary(hours=24)
    
    if not fallbacks:
        console.print("[yellow]No fallback records found[/]")
        return 0
    
    # Summary
    console.print("\n[bold cyan]Fallback Summary (Last 24h)[/]")
    console.print(f"  Total: {summary['total_fallbacks']}")
    if summary.get('by_agent'):
        console.print("  By Agent:")
        for agent, count in summary['by_agent'].items():
            console.print(f"    - {agent}: {count}")
    
    # Table
    table = Table(title="Fallback Audit Log", show_lines=True)
    table.add_column("Time", style="cyan", width=10)
    table.add_column("Agent", style="magenta", width=15)
    table.add_column("Reason", style="yellow", width=40)
    table.add_column("Symbol", style="green", width=12)
    
    for fb in fallbacks:
        time = datetime.fromisoformat(fb['timestamp']).strftime('%H:%M:%S')
        agent = fb['agent']
        reason = fb['reason'][:40]
        symbol = fb.get('symbol', '-')
        table.add_row(time, agent, reason, symbol)
    
    console.print(table)
    return 0


def cmd_circuit_breaker_status(args) -> int:
    """Show circuit breaker detailed status."""
    console = Console()
    
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    status = cb.get_status()
    
    console.print("\n[bold]Circuit Breaker Status[/]")
    
    if status['halted']:
        console.print("  State: [bold red]HALTED[/]")
        console.print(f"  Reason: [red]{status['halt_reason']}[/]")
    else:
        console.print("  State: [bold green]ACTIVE[/]")
    
    console.print("\n  Counters:")
    
    from config.trading_params import get_trading_params
    params = get_trading_params()

    # Fallbacks
    fb_count = status['consecutive_fallbacks']
    fb_max = params.system.max_consecutive_fallbacks
    fb_pct = (fb_count / fb_max) * 100 if fb_max > 0 else 0
    fb_color = "red" if fb_count >= fb_max - 1 else "yellow" if fb_count >= fb_max // 2 else "green"
    fb_bar = '#' * int(fb_pct/10) + '-' * (10 - int(fb_pct/10))
    console.print(f"    Fallbacks:    [{fb_color}]{fb_count}/{fb_max}[/{fb_color}] [{fb_bar}]")

    # LLM Errors
    llm_count = status['consecutive_llm_errors']
    llm_max = params.risk.max_consecutive_llm_errors
    llm_pct = (llm_count / llm_max) * 100 if llm_max > 0 else 0
    llm_color = "red" if llm_count >= llm_max - 2 else "yellow" if llm_count >= llm_max // 2 else "green"
    llm_bar = '#' * int(llm_pct/10) + '-' * (10 - int(llm_pct/10))
    console.print(f"    LLM Errors:   [{llm_color}]{llm_count}/{llm_max}[/{llm_color}] [{llm_bar}]")

    # Losses
    loss_count = status['consecutive_losses']
    loss_max = params.risk.max_consecutive_losses
    loss_pct = (loss_count / loss_max) * 100 if loss_max > 0 else 0
    loss_color = "red" if loss_count >= loss_max - 1 else "yellow" if loss_count >= loss_max // 2 else "green"
    loss_bar = '#' * int(loss_pct/10) + '-' * (10 - int(loss_pct/10))
    console.print(f"    Losses:       [{loss_color}]{loss_count}/{loss_max}[/{loss_color}] [{loss_bar}]")
    
    console.print()
    return 0


def cmd_circuit_breaker_reset(args) -> int:
    """Reset circuit breaker counters."""
    console = Console()
    from rich.prompt import Confirm
    
    if not Confirm.ask("[yellow]Reset all circuit breaker counters?[/]"):
        return 0
    
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb.reset_fallbacks()
    cb.reset_llm_errors()
    cb.consecutive_losses = 0
    cb._save_state()
    
    console.print("[green]✓ Circuit breaker counters reset[/]")
    return 0


def cmd_accounts(args) -> int:
    """Show status of all accounts."""
    console = Console()
    from rich.table import Table
    
    from config.settings import get_settings
    from execution.account_manager import MultiAccountManager
    
    settings = get_settings()
    
    if not settings.binance_accounts:
        console.print("[yellow]Multi-account configuration not found[/yellow]")
        return 0
    
    try:
        manager = MultiAccountManager(settings.binance_accounts)
        summary = manager.get_status_summary()
        
        console.print("\n[bold cyan]Account Status[/]")
        console.print(f"  Total Accounts:  {summary['total_accounts']}")
        console.print(f"  Active Accounts: {summary['active_accounts']}\n")
        
        # Table
        table = Table(title="Accounts", show_lines=True)
        table.add_column("Name", style="cyan", width=15)
        table.add_column("Status", style="magenta", width=10)
        table.add_column("Equity", style="green", width=15)
        table.add_column("Cash", style="blue", width=15)
        table.add_column("Positions", style="yellow", width=10)
        table.add_column("Error", style="red", width=20)
        
        for name, data in summary['accounts'].items():
            status = "[green]Active[/]" if data['is_active'] else "[red]Inactive[/]"
            equity = f"${data['equity']:,.2f}"
            cash = f"${data['cash']:,.2f}"
            pos = str(data['open_positions'])
            err = data['last_error'][:20] if data['last_error'] else "-"
            table.add_row(name, status, equity, cash, pos, err)
        
        console.print(table)
        
        # Combined view
        if summary['total_accounts'] > 1:
            total_equity = sum(acc['equity'] for acc in summary['accounts'].values())
            total_cash = sum(acc['cash'] for acc in summary['accounts'].values())
            total_positions = sum(acc['open_positions'] for acc in summary['accounts'].values())
            
            console.print("\n[bold]★ Consolidated View (All Accounts)[/]")
            console.print(f"  Total Equity:    [green]${total_equity:,.2f}[/]")
            console.print(f"  Total Cash:      [blue]${total_cash:,.2f}[/]")
            console.print(f"  Total Positions: {total_positions}\n")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
    return 0


def cmd_dashboard(args) -> int:
    """Show web dashboard URL."""
    console = Console()
    
    console.print("\n[bold cyan]Web Dashboard[/]")
    console.print("  URL: [link=http://localhost:8000]http://localhost:8000[/]")
    console.print("  API: [link=http://localhost:8000/docs]http://localhost:8000/docs[/]")
    console.print("\n  To start: [cyan]python dashboard/server.py[/]\n")
    return 0


def ana() -> int:
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description="Aegis Intelligence Terminal - Autonomous Trading Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  aegis health                    # Health check
  aegis run --symbol BTC/USDT     # Start paper trading
  aegis run --symbol BTC/USDT --execute  # Live trading (CAUTION!)
  aegis backtest --symbol BTC/USDT --days 90
  aegis portfolio                 # Portfolio status
  aegis scan                      # Market scan
  aegis status                    # System status
  aegis logs                      # Show logs
  aegis test                      # Run test suite
        """,
    )
    
    parser.add_argument("--version", "-v", action="version", version="Aegis Terminal v1.0.0")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Health check
    health_parser = subparsers.add_parser("health", help="System health check")
    health_parser.set_defaults(func=cmd_health)
    
    # Run bot
    run_parser = subparsers.add_parser("run", help="Run trading bot")
    run_parser.add_argument("--symbol", "-s", default="AUTO", help="Symbol or AUTO (auto-scan)")
    run_parser.add_argument("--interval", "-i", default="1h", help="Interval (5m, 15m, 30m, 1h, 4h)")
    run_parser.add_argument("--watchdog", "-w", action="store_true", help="Flash crash protection")
    run_parser.add_argument("--execute", "-e", action="store_true", help="Live trading (CAUTION!)")
    run_parser.add_argument("--auto-scan", action="store_true", help="Automatic market scanning")
    run_parser.add_argument("--max-cycles", type=int, default=0, help="Max cycles (0=infinite)")
    run_parser.add_argument("--model", "-m", default="qwen/qwen3.5-flash-02-23", help="LLM model")
    run_parser.set_defaults(func=cmd_run)
    
    # Backtest
    backtest_parser = subparsers.add_parser("backtest", help="Run backtest")
    backtest_parser.add_argument("--symbol", "-s", required=True, help="Symbol")
    backtest_parser.add_argument("--days", "-d", type=int, default=90, help="Days of history")
    backtest_parser.set_defaults(func=cmd_backtest)
    
    # Portfolio
    portfolio_parser = subparsers.add_parser("portfolio", help="Portfolio status")
    portfolio_parser.set_defaults(func=cmd_portfolio)
    
    # Test
    test_parser = subparsers.add_parser("test", help="Run test suite")
    test_parser.add_argument("--verbose", "-V", action="store_true", help="Verbose output")
    test_parser.set_defaults(func=cmd_test)
    
    # Logs
    logs_parser = subparsers.add_parser("logs", help="Show logs")
    logs_parser.add_argument("--lines", "-n", type=int, default=50, help="Number of lines")
    logs_parser.set_defaults(func=cmd_logs)
    
    # Scan
    scan_parser = subparsers.add_parser("scan", help="Market scan")
    scan_parser.set_defaults(func=cmd_scan)
    
    # Status
    status_parser = subparsers.add_parser("status", help="System status")
    status_parser.set_defaults(func=cmd_status)
    
    # Fallback audit log
    fallbacks_parser = subparsers.add_parser("fallbacks", help="Show latest fallback logs")
    fallbacks_parser.add_argument("--limit", "-l", type=int, default=10, help="Number of records to show")
    fallbacks_parser.set_defaults(func=cmd_fallbacks)
    
    # Circuit breaker status
    cb_parser = subparsers.add_parser("circuit-breaker", help="Show circuit breaker status")
    cb_parser.set_defaults(func=cmd_circuit_breaker_status)
    
    # Circuit breaker reset
    cb_reset_parser = subparsers.add_parser("circuit-breaker-reset", help="Reset circuit breaker counters")
    cb_reset_parser.set_defaults(func=cmd_circuit_breaker_reset)
    
    # Accounts
    accounts_parser = subparsers.add_parser("accounts", help="Show status of all accounts")
    accounts_parser.set_defaults(func=cmd_accounts)
    
    # Dashboard URL
    dashboard_parser = subparsers.add_parser("dashboard", help="Show web dashboard URL")
    dashboard_parser.set_defaults(func=cmd_dashboard)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


def main():
    """Entry point for console script."""
    sys.exit(ana())


if __name__ == "__main__":
    main()
