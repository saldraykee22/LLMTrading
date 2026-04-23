"""
LLM Trading System - Komut Satiri Arayuzu (CLI)
================================================
Turkce kullanici dostu komut satiri arayuzu.

Kullanim:
    python cli.py --help
    python cli.py saglik
    python cli.py calistir --sembol BTC/USDT
    python cli.py geriye-donuk-test --sembol BTC/USDT --gun 90
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Proje kokunu path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_baslik(baslik: str) -> None:
    """Baslik yazdir."""
    width = 70
    print("\n" + "=" * width)
    print(f"  {baslik}".center(width))
    print("=" * width + "\n")


def print_bolum(bolum_adi: str) -> None:
    """Bolum basligi yazdir."""
    print(f"\n> {bolum_adi}")
    print("-" * 50)


def cmd_saglik(args) -> int:
    """Sistem saglik kontrolu."""
    from scripts.health_check import main as saglik_ana
    return saglik_ana()


def cmd_calistir(args) -> int:
    """Trading bot'u calistir."""
    import subprocess
    
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_live.py"),
        "--symbol", args.sembol,
        "--interval", args.aralik,
    ]
    
    if args.bekci:
        cmd.append("--watchdog")
    
    if args.yurut:
        cmd.append("--execute")
    
    if args.oto_tarama:
        cmd.append("--auto-scan")
    
    if args.maks_dongu:
        cmd.extend(["--max-cycles", str(args.maks_dongu)])
    
    if args.model:
        cmd.extend(["--model", args.model])
    
    try:
        subprocess.run(cmd, check=True)
        return 0
    except KeyboardInterrupt:
        print("\n\n[BILGI] Kullanici tarafindan durduruldu.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[HATA] Bot hatasi: {e}")
        return 1


def cmd_geriye_donuk_test(args) -> int:
    """Geriye donuk test calistir."""
    import subprocess
    
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_backtest.py"),
        "--symbol", args.sembol,
        "--days", str(args.gun),
    ]
    
    try:
        subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[HATA] Backtest hatasi: {e}")
        return 1


def cmd_portfoy(args) -> int:
    """Portfoy durumu."""
    import json
    
    print_baslik("PORTFOY DURUMU")
    
    portfoy_dosya = PROJECT_ROOT / "data" / "portfolio_state.json"
    
    if not portfoy_dosya.exists():
        print("[BILGI] Henuz acik pozisyon yok.")
        return 0
    
    try:
        with open(portfoy_dosya, "r", encoding="utf-8") as f:
            veri = json.load(f)
        
        print(f"Baslangic Nakit:    ${veri.get('initial_cash', 0):,.2f}")
        print(f"Su Anki Nakit:      ${veri.get('cash', 0):,.2f}")
        print(f"Toplam Ozvarlik:    ${veri.get('equity', 0):,.2f}")
        print(f"Toplam Kar/Zarar:   ${veri.get('total_pnl', 0):,.2f}")
        print(f"Gunluk Kar/Zarar:   ${veri.get('daily_pnl', 0):,.2f}")
        print(f"Maksimum Erime:     {veri.get('current_drawdown', 0):.2%}")
        
        pozisyonlar = veri.get("positions", [])
        if pozisyonlar:
            print_bolum(f"ACIK POZISYONLAR ({len(pozisyonlar)})")
            for poz in pozisyonlar:
                print(f"\n  {poz.get('symbol')}")
                print(f"    Taraf:       {poz.get('side', 'long').upper()}")
                print(f"    Giris:       ${poz.get('entry_price', 0):,.2f}")
                print(f"    Miktar:      {poz.get('amount', 0):.6f}")
                print(f"    Kar/Zarar:   ${poz.get('unrealized_pnl', 0):,.2f}")
        
        print()
        return 0
    except Exception as e:
        print(f"[HATA] Portfoy okunamadi: {e}")
        return 1


def cmd_testler(args) -> int:
    """Test paketi calistir."""
    import subprocess
    
    print_baslik("TEST PAKETI")
    
    cmd = [
        sys.executable,
        "-m", "pytest",
        str(PROJECT_ROOT / "tests" / "test_integration.py"),
        "-v",
        "--tb=short",
    ]
    
    if args.ayrintili:
        cmd.append("-s")
    
    try:
        subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[HATA] Testler basarisiz: {e}")
        return 1


def cmd_kayitlar(args) -> int:
    """Kayitlari (log) goster."""
    print_baslik("SON KAYIT SATIRLARI")
    
    kayit_dosya = PROJECT_ROOT / "logs" / "trading.log"
    
    if not kayit_dosya.exists():
        print("[BILGI] Henuz kayit dosyasi olusturulmadi.")
        return 0
    
    try:
        with open(kayit_dosya, "r", encoding="utf-8") as f:
            satirlar = f.readlines()
        
        n = args.satir or 50
        for satir in satirlar[-n:]:
            print(satir.strip())
        
        return 0
    except Exception as e:
        print(f"[HATA] Kayit okunamadi: {e}")
        return 1


def cmd_tarama(args) -> int:
    """Piyasa taramasi."""
    from data.scanner import MarketScanner
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    print_baslik("PIYASA TARAMASI")
    
    tarayici = MarketScanner()
    
    print_bolum("Adaylar Taraniyor...")
    try:
        adaylar = tarayici.get_candidates()
    except Exception as e:
        console.print(f"[red]X Tarama hatasi: {e}[/red]")
        return 1
    
    if not adaylar:
        console.print("[yellow]Kriterlere uygun aday bulunamadi.[/yellow]")
        return 0
    
    console.print(f"[green]V {len(adaylar)} aday bulundu.[/green]")
    
    print_bolum("En Iyi Adaylar")
    
    tablo = Table(title="Onerilen Varliklar", show_header=True, header_style="bold cyan")
    tablo.add_column("Sembol", style="bold")
    tablo.add_column("Fiyat", justify="right")
    tablo.add_column("24s Hacim", justify="right")
    tablo.add_column("24s Degisim", justify="right")
    tablo.add_column("Kalite Skoru", justify="right")
    
    for aday in adaylar[:10]:
        if isinstance(aday, dict):
            sembol = aday.get("symbol", "N/A")
            fiyat = aday.get("price", 0)
            hacim = aday.get("volume_24h", 0)
            degisim = aday.get("change_24h", 0)
            skor = aday.get("quality_score", 0)
            
            tablo.add_row(
                sembol,
                f"${fiyat:,.4f}",
                f"${hacim:,.0f}",
                f"{degisim:+.2f}%",
                f"{skor:.1f}",
            )
    
    console.print(tablo)
    print()
    
    return 0


def cmd_durum(args) -> int:
    """Sistem durumu."""
    console = Console()
    
    print_baslik("SISTEM DURUMU")
    
    # Circuit Breaker
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb_durum = cb.get_status()
    
    panel_veri = []
    panel_veri.append(f"Circuit Breaker: {'[red]AKTIF[/red]' if cb_durum.get('halted') else '[green]PASIF[/green]'}")
    if cb_durum.get('halt_reason'):
        panel_veri.append(f"  Sebep: {cb_durum['halt_reason']}")
    panel_veri.append(f"Art Arda Kayip: {cb_durum.get('consecutive_losses', 0)}")
    panel_veri.append(f"Art Arda LLM Hatasi: {cb_durum.get('consecutive_llm_errors', 0)}")
    
    console.print(Panel("\n".join(panel_veri), title="Circuit Breaker", border_style="red" if cb_durum.get('halted') else "green"))
    
    # Portfoy
    from risk.portfolio import PortfolioState
    portfoy = PortfolioState.load_from_file()
    
    portfoy_tablo = Table(title="Portfoy Ozeti", show_header=False)
    portfoy_tablo.add_column("Ozellik", style="bold")
    portfoy_tablo.add_column("Deger")
    
    portfoy_tablo.add_row("Ozvarlik", f"${portfoy.equity:,.2f}")
    portfoy_tablo.add_row("Nakit", f"${portfoy.cash:,.2f}")
    portfoy_tablo.add_row("Acik Pozisyon", str(portfoy.open_position_count))
    portfoy_tablo.add_row("Toplam Kar/Zarar", f"${portfoy.total_pnl:,.2f}")
    portfoy_tablo.add_row("Gunluk Kar/Zarar", f"${portfoy.daily_pnl:,.2f}")
    portfoy_tablo.add_row("Erime", f"{portfoy.current_drawdown:.2%}")
    
    console.print(portfoy_tablo)
    print()
    
    return 0


def cmd_fallbacklar(args) -> int:
    """Son fallback kayitlarini goster."""
    console = Console()
    
    from data.fallback_store import get_fallback_store
    store = get_fallback_store()
    fallbacks = store.get_fallbacks(limit=args.limit)
    summary = store.get_fallback_summary(hours=24)
    
    if not fallbacks:
        console.print("[yellow]Fallback kaydi bulunamadi[/]")
        return 0
    
    # Summary
    console.print(f"\n[bold cyan]Fallback Ozeti (Son 24s)[/]")
    console.print(f"  Toplam: {summary['total_fallbacks']}")
    if summary.get('by_agent'):
        console.print(f"  Ajanlara gore:")
        for agent, count in summary['by_agent'].items():
            console.print(f"    - {agent}: {count}")
    
    # Table
    table = Table(title="Fallback Audit Log", show_lines=True)
    table.add_column("Zaman", style="cyan", width=10)
    table.add_column("Ajan", style="magenta", width=15)
    table.add_column("Neden", style="yellow", width=40)
    table.add_column("Sembol", style="green", width=12)
    
    for fb in fallbacks:
        zaman = datetime.fromisoformat(fb['timestamp']).strftime('%H:%M:%S')
        ajan = fb['agent']
        neden = fb['reason'][:40]
        sembol = fb.get('symbol', '-')
        table.add_row(zaman, ajan, neden, sembol)
    
    console.print(table)
    return 0


def cmd_circuit_breaker(args) -> int:
    """Circuit breaker durumunu goster."""
    console = Console()
    
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    status = cb.get_status()
    
    console.print(f"\n[bold]Circuit Breaker Durumu[/]")
    
    if status['halted']:
        console.print(f"  Durum: [bold red]DURDURULDU[/]")
        console.print(f"  Neden: [red]{status['halt_reason']}[/]")
    else:
        console.print(f"  Durum: [bold green]AKTIF[/]")
    
    console.print(f"\n  Sayaclar:")
    
    params = get_trading_params()

    # Fallbacks
    fb_count = status['consecutive_fallbacks']
    fb_max = params.system.max_consecutive_fallbacks
    fb_pct = (fb_count / fb_max) * 100 if fb_max > 0 else 0
    fb_color = "red" if fb_count >= fb_max - 1 else "yellow" if fb_count >= fb_max // 2 else "green"
    fb_bar = '#' * int(fb_pct/10) + '-' * (10 - int(fb_pct/10))
    console.print(f"    Fallbacklar:  [{fb_color}]{fb_count}/{fb_max}[/{fb_color}] [{fb_bar}]")

    # LLM Errors
    llm_count = status['consecutive_llm_errors']
    llm_max = params.risk.max_consecutive_llm_errors
    llm_pct = (llm_count / llm_max) * 100 if llm_max > 0 else 0
    llm_color = "red" if llm_count >= llm_max - 2 else "yellow" if llm_count >= llm_max // 2 else "green"
    llm_bar = '#' * int(llm_pct/10) + '-' * (10 - int(llm_pct/10))
    console.print(f"    LLM Hatalari: [{llm_color}]{llm_count}/{llm_max}[/{llm_color}] [{llm_bar}]")

    # Losses
    loss_count = status['consecutive_losses']
    loss_max = params.risk.max_consecutive_losses
    loss_pct = (loss_count / loss_max) * 100 if loss_max > 0 else 0
    loss_color = "red" if loss_count >= loss_max - 1 else "yellow" if loss_count >= loss_max // 2 else "green"
    loss_bar = '#' * int(loss_pct/10) + '-' * (10 - int(loss_pct/10))
    console.print(f"    Kayiplar:     [{loss_color}]{loss_count}/{loss_max}[/{loss_color}] [{loss_bar}]")
    
    console.print()
    return 0


def cmd_circuit_breaker_reset(args) -> int:
    """Circuit breaker sayaclarini sifirla."""
    console = Console()
    from rich.prompt import Confirm
    
    if not Confirm.ask("[yellow]Tum circuit breaker sayaclari sifirlansin mi?[/]"):
        return 0
    
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb.reset_fallbacks()
    cb.reset_llm_errors()
    cb.consecutive_losses = 0
    cb._save_state()
    
    console.print("[green]✓ Circuit breaker sayaclari sifirlandi[/]")
    return 0


def cmd_hesaplar(args) -> int:
    """Tum hesaplarin durumunu goster."""
    console = Console()
    from rich.table import Table
    
    from config.settings import get_settings
    from execution.account_manager import MultiAccountManager
    
    settings = get_settings()
    
    if not settings.binance_accounts:
        console.print("[yellow]Multi-account yapilandirmasi bulunamadi[/]")
        return 0
    
    try:
        manager = MultiAccountManager(settings.binance_accounts)
        summary = manager.get_status_summary()
        
        console.print(f"\n[bold cyan]Hesap Durumu[/]")
        console.print(f"  Toplam Hesap: {summary['total_accounts']}")
        console.print(f"  Aktif Hesap:  {summary['active_accounts']}\n")
        
        # Table
        table = Table(title="Hesaplar", show_lines=True)
        table.add_column("Ad", style="cyan", width=15)
        table.add_column("Durum", style="magenta", width=10)
        table.add_column("Equity", style="green", width=15)
        table.add_column("Cash", style="blue", width=15)
        table.add_column("Pozisyon", style="yellow", width=10)
        table.add_column("Hata", style="red", width=20)
        
        for name, data in summary['accounts'].items():
            durum = "[green]Aktif[/]" if data['is_active'] else "[red]Pasif[/]"
            equity = f"${data['equity']:,.2f}"
            cash = f"${data['cash']:,.2f}"
            pozisyon = str(data['open_positions'])
            hata = data['last_error'][:20] if data['last_error'] else "-"
            table.add_row(name, durum, equity, cash, pozisyon, hata)
        
        console.print(table)
        
        # Combined view
        if summary['total_accounts'] > 1:
            total_equity = sum(acc['equity'] for acc in summary['accounts'].values())
            total_cash = sum(acc['cash'] for acc in summary['accounts'].values())
            total_positions = sum(acc['open_positions'] for acc in summary['accounts'].values())
            
            console.print(f"\n[bold]★ Kombin Gorunum (Tum Hesaplar)[/]")
            console.print(f"  Toplam Equity:  [green]${total_equity:,.2f}[/]")
            console.print(f"  Toplam Cash:    [blue]${total_cash:,.2f}[/]")
            console.print(f"  Toplam Pozisyon: {total_positions}\n")
        
    except Exception as e:
        console.print(f"[red]Hata: {e}[/]")
    return 0


def cmd_dashboard(args) -> int:
    """Web dashboard URL'sini goster."""
    console = Console()
    
    console.print(f"\n[bold cyan]Web Dashboard[/]")
    console.print(f"  URL: [link=http://localhost:8000]http://localhost:8000[/]")
    console.print(f"  API: [link=http://localhost:8000/docs]http://localhost:8000/docs[/]")
    console.print(f"\n  Baslatmak icin: [cyan]python dashboard/server.py[/]\n")
    return 0


def ana() -> int:
    """Ana CLI fonksiyonu."""
    parser = argparse.ArgumentParser(
        description="LLM Trading System - Turkce Komut Satiri Arayuzu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ornekler:
  python cli.py saglik                    # Saglik kontrolu
  python cli.py calistir --sembol BTC/USDT     # Paper trading baslat
  python cli.py calistir --sembol BTC/USDT --yurut  # Canli trading
  python cli.py geriye-donuk-test --sembol BTC/USDT --gun 90
  python cli.py portfoy                 # Portfoy durumu
  python cli.py tarama                      # Piyasa taramasi
  python cli.py durum                    # Sistem durumu
  python cli.py kayitlar                      # Kayitlari goster
  python cli.py testler                     # Test paketi
        """,
    )
    
    alt_parserlar = parser.add_subparsers(dest="komut", help="Komutlar")
    
    # Saglik kontrolu
    saglik_parser = alt_parserlar.add_parser("saglik", help="Saglik kontrolu")
    saglik_parser.set_defaults(func=cmd_saglik)
    
    # Bot calistir
    calistir_parser = alt_parserlar.add_parser("calistir", help="Trading bot'u calistir")
    calistir_parser.add_argument("--sembol", "-s", default="AUTO", help="Sembol veya AUTO (otomatik tarama)")
    calistir_parser.add_argument("--aralik", "-a", default="1h", help="Aralik (5m, 15m, 30m, 1h, 4h)")
    calistir_parser.add_argument("--bekci", "-b", action="store_true", help="Flash crash korumasi")
    calistir_parser.add_argument("--yurut", "-y", action="store_true", help="Canli islem (DIKKAT!)")
    calistir_parser.add_argument("--oto-tarama", action="store_true", help="Otomatik piyasa taramasi")
    calistir_parser.add_argument("--maks-dongu", type=int, default=0, help="Maksimum dongu sayisi (0=sinirsiz)")
    calistir_parser.add_argument("--model", "-m", default="qwen/qwen3.5-flash-02-23", help="LLM modeli")
    calistir_parser.set_defaults(func=cmd_calistir)
    
    # Geriye donuk test
    geriye_parser = alt_parserlar.add_parser("geriye-donuk-test", help="Geriye donuk test calistir")
    geriye_parser.add_argument("--sembol", "-s", required=True, help="Sembol")
    geriye_parser.add_argument("--gun", "-g", type=int, default=90, help="Gecmis gun sayisi")
    geriye_parser.set_defaults(func=cmd_geriye_donuk_test)
    
    # Portfoy
    portfoy_parser = alt_parserlar.add_parser("portfoy", help="Portfoy durumu")
    portfoy_parser.set_defaults(func=cmd_portfoy)
    
    # Testler
    testler_parser = alt_parserlar.add_parser("testler", help="Test paketi calistir")
    testler_parser.add_argument("--ayrintili", "-a", action="store_true", help="Detayli cikti")
    testler_parser.set_defaults(func=cmd_testler)
    
    # Kayitlar
    kayitlar_parser = alt_parserlar.add_parser("kayitlar", help="Kayitlari (log) goster")
    kayitlar_parser.add_argument("--satir", "-n", type=int, default=50, help="Satir sayisi")
    kayitlar_parser.set_defaults(func=cmd_kayitlar)
    
    # Tarama
    tarama_parser = alt_parserlar.add_parser("tarama", help="Piyasa taramasi")
    tarama_parser.set_defaults(func=cmd_tarama)
    
    # Durum
    durum_parser = alt_parserlar.add_parser("durum", help="Sistem durumu")
    durum_parser.set_defaults(func=cmd_durum)
    
    # Fallback audit log
    fallbacklar_parser = alt_parserlar.add_parser("fallbacklar", help="Son fallback kayıtlarını göster")
    fallbacklar_parser.add_argument("--limit", "-l", type=int, default=10, help="Gösterilecek kayıt sayısı")
    fallbacklar_parser.set_defaults(func=cmd_fallbacklar)
    
    # Circuit breaker durumu
    cb_parser = alt_parserlar.add_parser("circuit-breaker", help="Circuit breaker durumunu göster")
    cb_parser.set_defaults(func=cmd_circuit_breaker)
    
    # Circuit breaker sıfırla
    cb_reset_parser = alt_parserlar.add_parser("circuit-breaker-sifirla", help="Circuit breaker sayaçlarını sıfırla")
    cb_reset_parser.set_defaults(func=cmd_circuit_breaker_reset)
    
    # Hesaplar
    hesaplar_parser = alt_parserlar.add_parser("hesaplar", help="Tüm hesapların durumunu göster")
    hesaplar_parser.set_defaults(func=cmd_hesaplar)
    
    # Dashboard URL
    dashboard_parser = alt_parserlar.add_parser("dashboard", help="Web dashboard URL'sini göster")
    dashboard_parser.set_defaults(func=cmd_dashboard)
    
    args = parser.parse_args()
    
    if not args.komut:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(ana())
