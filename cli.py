"""
LLM Trading System - Command Line Interface (CLI)
==================================================
Kullanici dostu komut satiri arayuzu.

Kullanim:
    python cli.py --help
    python cli.py health
    python cli.py run --symbol BTC/USDT
    python cli.py backtest --symbol BTC/USDT --days 90
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Proje kökünü path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_header(title: str) -> None:
    """Baslik yazdir."""
    width = 70
    print("\n" + "═" * width)
    print(f"  {title}".center(width))
    print("═" * width + "\n")


def print_section(title: str) -> None:
    """Bölüm başlığı yazdır."""
    print(f"\n▶ {title}")
    print("─" * 50)


def cmd_health(args) -> int:
    """Sağlık kontrolü."""
    from scripts.health_check import main as health_main
    return health_main()


def cmd_run(args) -> int:
    """Trading bot'u çalıştır."""
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
    
    try:
        subprocess.run(cmd, check=True)
        return 0
    except KeyboardInterrupt:
        print("\n\n[BILGI] Kullanici tarafindan durduruldu.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[HATA] Bot hatasi: {e}")
        return 1


def cmd_backtest(args) -> int:
    """Backtest çalıştır."""
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
        print(f"\n[HATA] Backtest hatasi: {e}")
        return 1


def cmd_portfolio(args) -> int:
    """Portföy durumu."""
    import json
    
    print_header("PORTFÖY DURUMU")
    
    portfolio_file = PROJECT_ROOT / "data" / "portfolio_state.json"
    
    if not portfolio_file.exists():
        print("[BILGI] Henüz açık pozisyon yok.")
        return 0
    
    try:
        with open(portfolio_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        print(f"Başlangıç Nakit:    ${data.get('initial_cash', 0):,.2f}")
        print(f"Şu Anki Nakit:      ${data.get('cash', 0):,.2f}")
        print(f"Toplam Özvarlık:    ${data.get('equity', sum(p.get('current_price', 0) * p.get('amount', 0) for p in data.get('positions', [])) + data.get('cash', 0)):,.2f}")
        print(f"Toplam P&L:         ${data.get('total_pnl', 0):,.2f}")
        print(f"Günlük P&L:         ${data.get('daily_pnl', 0):,.2f}")
        print(f"Maksimum Drawdown:  {data.get('current_drawdown', 0):.2%}")
        print(f"Alpha:              {data.get('alpha', 0):.2%}")
        
        positions = data.get("positions", [])
        if positions:
            print_section(f"AÇIK POZİSYONLAR ({len(positions)})")
            for pos in positions:
                print(f"\n  {pos.get('symbol')}")
                print(f"    Taraf:      {pos.get('side', 'long').upper()}")
                print(f"    Giriş:      ${pos.get('entry_price', 0):,.2f}")
                print(f"    Miktar:     {pos.get('amount', 0):.6f}")
                print(f"    Stop-Loss:  ${pos.get('stop_loss', 0):,.2f}")
                print(f"    Take-Profit:${pos.get('take_profit', 0):,.2f}")
                print(f"    P&L:        ${pos.get('unrealized_pnl', 0):,.2f} ({pos.get('unrealized_pnl_pct', 0):.2%})")
        
        print()
        return 0
    except Exception as e:
        print(f"[HATA] Portföy okunamadı: {e}")
        return 1


def cmd_tests(args) -> int:
    """Test suite çalıştır."""
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
        result = subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[HATA] Testler başarısız: {e}")
        return 1


def cmd_logs(args) -> int:
    """Logları göster."""
    from rich.console import Console
    
    console = Console()
    
    print_header("SON LOG SATIRLARI")
    
    log_file = PROJECT_ROOT / "logs" / "trading.log"
    
    if not log_file.exists():
        print("[BILGI] Henüz log dosyası oluşturulmadı.")
        return 0
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Son N satır
        n = args.lines or 50
        for line in lines[-n:]:
            console.print(line.strip())
        
        return 0
    except Exception as e:
        print(f"[HATA] Log okunamadı: {e}")
        return 1


def cmd_scan(args) -> int:
    """Piyasa taraması."""
    from data.scanner import MarketScanner
    from agents.lead_scout import LeadScout
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    print_header("PİYASA TARAMASI")
    
    scanner = MarketScanner()
    
    print_section("Adaylar Taraniyor...")
    try:
        candidates = scanner.get_candidates()
    except Exception as e:
        console.print(f"[red]✗ Tarama hatası: {e}[/red]")
        return 1
    
    if not candidates:
        console.print("[yellow]⚠ Kriterlere uygun aday bulunamadı.[/yellow]")
        return 0
    
    console.print(f"[green]✓ {len(candidates)} aday bulundu.[/green]")
    
    print_section("En İyi Adaylar")
    
    table = Table(title="Önerilen Varlıklar", show_header=True, header_style="bold cyan")
    table.add_column("Sembol", style="bold")
    table.add_column("Fiyat", justify="right")
    table.add_column("24h Hacim", justify="right")
    table.add_column("24h Değişim", justify="right")
    table.add_column("Kalite Skor", justify="right")
    
    for candidate in candidates[:10]:
        # Scanner'dan dönen format: symbol, price, change_24h, volume_24h, quality_score
        if isinstance(candidate, dict):
            symbol = candidate.get("symbol", "N/A")
            price = candidate.get("price", 0)
            volume = candidate.get("volume_24h", 0)
            change = candidate.get("change_24h", 0)
            score = candidate.get("quality_score", 0)
            
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
    """Sistem durumu."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    
    console = Console()
    
    print_header("SİSTEM DURUMU")
    
    # Circuit Breaker
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb_status = cb.get_status()
    
    panel_data = []
    panel_data.append(f"Circuit Breaker: {'[red]AKTİF[/red]' if cb_status.get('halted') else '[green]PASİF[/green]'}")
    if cb_status.get('halt_reason'):
        panel_data.append(f"  Sebep: {cb_status['halt_reason']}")
    panel_data.append(f"Art Arda Kayıp: {cb_status.get('consecutive_losses', 0)}")
    panel_data.append(f"Art Arda LLM Hatası: {cb_status.get('consecutive_llm_errors', 0)}")
    
    console.print(Panel("\n".join(panel_data), title="Circuit Breaker", border_style="red" if cb_status.get('halted') else "green"))
    
    # Portföy
    from risk.portfolio import PortfolioState
    portfolio = PortfolioState.load_from_file()
    
    portfolio_table = Table(title="Portföy Özeti", show_header=False)
    portfolio_table.add_column("Özellik", style="bold")
    portfolio_table.add_column("Değer")
    
    portfolio_table.add_row("Özvarlık", f"${portfolio.equity:,.2f}")
    portfolio_table.add_row("Nakit", f"${portfolio.cash:,.2f}")
    portfolio_table.add_row("Açık Pozisyon", str(portfolio.open_position_count))
    portfolio_table.add_row("Toplam P&L", f"${portfolio.total_pnl:,.2f}")
    portfolio_table.add_row("Günlük P&L", f"${portfolio.daily_pnl:,.2f}")
    portfolio_table.add_row("Drawdown", f"{portfolio.current_drawdown:.2%}")
    
    console.print(portfolio_table)
    print()
    
    return 0


def main() -> int:
    """Ana CLI fonksiyonu."""
    parser = argparse.ArgumentParser(
        description="LLM Trading System - Komut Satırı Arayüzü",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python cli.py health                    # Sağlık kontrolü
  python cli.py run --symbol BTC/USDT     # Paper trading başlat
  python cli.py run --symbol BTC/USDT --execute  # Canlı trading
  python cli.py backtest --symbol BTC/USDT --days 90
  python cli.py portfolio                 # Portföy durumu
  python cli.py scan                      # Piyasa taraması
  python cli.py status                    # Sistem durumu
  python cli.py logs                      # Logları göster
  python cli.py tests                     # Test suite
        """,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Komutlar")
    
    # Health check
    health_parser = subparsers.add_parser("health", help="Sağlık kontrolü")
    health_parser.set_defaults(func=cmd_health)
    
    # Run bot
    run_parser = subparsers.add_parser("run", help="Trading bot'u çalıştır")
    run_parser.add_argument("--symbol", "-s", required=True, help="Sembol (örn: BTC/USDT)")
    run_parser.add_argument("--interval", "-i", default="1h", help="Interval (5m, 15m, 30m, 1h, 4h)")
    run_parser.add_argument("--watchdog", "-w", action="store_true", help="Flash crash koruması")
    run_parser.add_argument("--execute", "-x", action="store_true", help="Canlı işlem (DİKKAT!)")
    run_parser.add_argument("--auto-scan", action="store_true", help="Otomatik piyasa taraması")
    run_parser.add_argument("--max-cycles", type=int, default=0, help="Maksimum döngü sayısı (0=sınırsız)")
    run_parser.set_defaults(func=cmd_run)
    
    # Backtest
    backtest_parser = subparsers.add_parser("backtest", help="Backtest çalıştır")
    backtest_parser.add_argument("--symbol", "-s", required=True, help="Sembol")
    backtest_parser.add_argument("--days", "-d", type=int, default=90, help="Geçmiş gün sayısı")
    backtest_parser.set_defaults(func=cmd_backtest)
    
    # Portfolio
    portfolio_parser = subparsers.add_parser("portfolio", help="Portföy durumu")
    portfolio_parser.set_defaults(func=cmd_portfolio)
    
    # Tests
    tests_parser = subparsers.add_parser("tests", help="Test suite çalıştır")
    tests_parser.add_argument("--verbose", "-v", action="store_true", help="Detaylı çıktı")
    tests_parser.set_defaults(func=cmd_tests)
    
    # Logs
    logs_parser = subparsers.add_parser("logs", help="Logları göster")
    logs_parser.add_argument("--lines", "-n", type=int, default=50, help="Satır sayısı")
    logs_parser.set_defaults(func=cmd_logs)
    
    # Scan
    scan_parser = subparsers.add_parser("scan", help="Piyasa taraması")
    scan_parser.set_defaults(func=cmd_scan)
    
    # Status
    status_parser = subparsers.add_parser("status", help="Sistem durumu")
    status_parser.set_defaults(func=cmd_status)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
