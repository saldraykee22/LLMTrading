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
    """Saglik kontrolu."""
    from scripts.health_check import main as saglik_ana
    return saglik_ana()


def cmd_calistir(args) -> int:
    """Trading bot'u calistir."""
    import subprocess
    
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_live.py"),
        "--sembol", args.sembol,
        "--aralik", args.aralik,
    ]
    
    if args.bekci:
        cmd.append("--watchdog")
    
    if args.yurut:
        cmd.append("--execute")
    
    if args.oto_tarama:
        cmd.append("--auto-scan")
    
    if args.maks_dongu:
        cmd.extend(["--max-cycles", str(args.maks_dongu)])
    
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
        "--sembol", args.sembol,
        "--gun", str(args.gun),
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
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    
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
    calistir_parser.add_argument("--sembol", "-s", required=True, help="Sembol (orn: BTC/USDT)")
    calistir_parser.add_argument("--aralik", "-a", default="1h", help="Aralik (5m, 15m, 30m, 1h, 4h)")
    calistir_parser.add_argument("--bekci", "-b", action="store_true", help="Flash crash korumasi")
    calistir_parser.add_argument("--yurut", "-y", action="store_true", help="Canli islem (DIKKAT!)")
    calistir_parser.add_argument("--oto-tarama", action="store_true", help="Otomatik piyasa taramasi")
    calistir_parser.add_argument("--maks-dongu", type=int, default=0, help="Maksimum dongu sayisi (0=sinirsiz)")
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
    
    args = parser.parse_args()
    
    if not args.komut:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(ana())
