"""
LLM Trading System - Komut Satırı Arayüzü (CLI)
================================================
Türkçe kullanıcı dostu komut satırı arayüzü.

Kullanım:
    python cli.py --yardim
    python cli.py saglik
    python cli.py calistir --sembol BTC/USDT
    python cli.py geriye-donuk-test --sembol BTC/USDT --gun 90
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Proje kökünü path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_baslik(baslik: str) -> None:
    """Başlık yazdır."""
    width = 70
    print("\n" + "=" * width)
    print(f"  {baslik}".center(width))
    print("=" * width + "\n")


def print_bolum(bolum_adi: str) -> None:
    """Bölüm başlığı yazdır."""
    print(f"\n▶ {bolum_adi}")
    print("-" * 50)


def cmd_saglik(args) -> int:
    """Sağlık kontrolü."""
    from scripts.health_check import main as saglik_ana
    return saglik_ana()


def cmd_calistir(args) -> int:
    """Trading bot'u çalıştır."""
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
        print("\n\n[BİLGİ] Kullanıcı tarafından durduruldu.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[HATA] Bot hatası: {e}")
        return 1


def cmd_geriye_donuk_test(args) -> int:
    """Geriye dönük test çalıştır."""
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
        print(f"\n[HATA] Backtest hatası: {e}")
        return 1


def cmd_portfoy(args) -> int:
    """Portföy durumu."""
    import json
    
    print_baslik("PORTFÖY DURUMU")
    
    portfoy_dosya = PROJECT_ROOT / "data" / "portfolio_state.json"
    
    if not portfoy_dosya.exists():
        print("[BİLGİ] Henüz açık pozisyon yok.")
        return 0
    
    try:
        with open(portfoy_dosya, "r", encoding="utf-8") as f:
            veri = json.load(f)
        
        print(f"Başlangıç Nakit:    ${veri.get('initial_cash', 0):,.2f}")
        print(f"Şu Anki Nakit:      ${veri.get('cash', 0):,.2f}")
        print(f"Toplam Özvarlık:    ${veri.get('equity', sum(p.get('current_price', 0) * p.get('amount', 0) for p in veri.get('positions', [])) + veri.get('cash', 0)):,.2f}")
        print(f"Toplam Kâr/Zarar:   ${veri.get('total_pnl', 0):,.2f}")
        print(f"Günlük Kâr/Zarar:   ${veri.get('daily_pnl', 0):,.2f}")
        print(f"Maksimum Erime:     {veri.get('current_drawdown', 0):.2%}")
        print(f"Alpha:              {veri.get('alpha', 0):.2%}")
        
        pozisyonlar = veri.get("positions", [])
        if pozisyonlar:
            print_bolum(f"AÇIK POZİSYONLAR ({len(pozisyonlar)})")
            for poz in pozisyonlar:
                print(f"\n  {poz.get('symbol')}")
                print(f"    Taraf:        {poz.get('side', 'long').upper()}")
                print(f"    Giriş:        ${poz.get('entry_price', 0):,.2f}")
                print(f"    Miktar:       {poz.get('amount', 0):.6f}")
                print(f"    Stop-Loss:    ${poz.get('stop_loss', 0):,.2f}")
                print(f"    Take-Profit:  ${poz.get('take_profit', 0):,.2f}")
                print(f"    Kâr/Zarar:    ${poz.get('unrealized_pnl', 0):,.2f} ({poz.get('unrealized_pnl_pct', 0):.2%})")
        
        print()
        return 0
    except Exception as e:
        print(f"[HATA] Portföy okunamadı: {e}")
        return 1


def cmd_testler(args) -> int:
    """Test paketi çalıştır."""
    import subprocess
    
    print_baslik("TEST PAKETİ")
    
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
        result = subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[HATA] Testler başarısız: {e}")
        return 1


def cmd_kayitlar(args) -> int:
    """Kayıtları (log) göster."""
    from rich.console import Console
    
    console = Console()
    
    print_baslik("SON KAYIT SATIRLARI")
    
    kayit_dosya = PROJECT_ROOT / "logs" / "trading.log"
    
    if not kayit_dosya.exists():
        print("[BİLGİ] Henüz kayıt dosyası oluşturulmadı.")
        return 0
    
    try:
        with open(kayit_dosya, "r", encoding="utf-8") as f:
            satirlar = f.readlines()
        
        # Son N satır
        n = args.satir or 50
        for satir in satirlar[-n:]:
            console.print(satir.strip())
        
        return 0
    except Exception as e:
        print(f"[HATA] Kayıt okunamadı: {e}")
        return 1


def cmd_tarama(args) -> int:
    """Piyasa taraması."""
    from data.scanner import MarketScanner
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    print_baslik("PİYASA TARAMASI")
    
    tarayici = MarketScanner()
    
    print_bolum("Adaylar Taraniyor...")
    try:
        adaylar = tarayici.get_candidates()
    except Exception as e:
        console.print(f"[red]✗ Tarama hatası: {e}[/red]")
        return 1
    
    if not adaylar:
        console.print("[yellow]⚠ Kriterlere uygun aday bulunamadı.[/yellow]")
        return 0
    
    console.print(f"[green]✓ {len(adaylar)} aday bulundu.[/green]")
    
    print_bolum("En İyi Adaylar")
    
    tablo = Table(title="Önerilen Varlıklar", show_header=True, header_style="bold cyan")
    tablo.add_column("Sembol", style="bold")
    tablo.add_column("Fiyat", justify="right")
    tablo.add_column("24s Hacim", justify="right")
    tablo.add_column("24s Değişim", justify="right")
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
    
    print_baslik("SİSTEM DURUMU")
    
    # Circuit Breaker
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb_durum = cb.get_status()
    
    panel_veri = []
    panel_veri.append(f"Circuit Breaker: {'[red]AKTİF[/red]' if cb_durum.get('halted') else '[green]PASİF[/green]'}")
    if cb_durum.get('halt_reason'):
        panel_veri.append(f"  Sebep: {cb_durum['halt_reason']}")
    panel_veri.append(f"Art Arda Kayıp: {cb_durum.get('consecutive_losses', 0)}")
    panel_veri.append(f"Art Arda LLM Hatası: {cb_durum.get('consecutive_llm_errors', 0)}")
    
    console.print(Panel("\n".join(panel_veri), title="Circuit Breaker", border_style="red" if cb_durum.get('halted') else "green"))
    
    # Portföy
    from risk.portfolio import PortfolioState
    portfoy = PortfolioState.load_from_file()
    
    portfoy_tablo = Table(title="Portföy Özeti", show_header=False)
    portfoy_tablo.add_column("Özellik", style="bold")
    portfoy_tablo.add_column("Değer")
    
    portfoy_tablo.add_row("Özvarlık", f"${portfoy.equity:,.2f}")
    portfoy_tablo.add_row("Nakit", f"${portfoy.cash:,.2f}")
    portfoy_tablo.add_row("Açık Pozisyon", str(portfoy.open_position_count))
    portfoy_tablo.add_row("Toplam Kâr/Zarar", f"${portfoy.total_pnl:,.2f}")
    portfoy_tablo.add_row("Günlük Kâr/Zarar", f"${portfoy.daily_pnl:,.2f}")
    portfoy_tablo.add_row("Erime", f"{portfoy.current_drawdown:.2%}")
    
    console.print(portfoy_tablo)
    print()
    
    return 0


def ana() -> int:
    """Ana CLI fonksiyonu."""
    parser = argparse.ArgumentParser(
        description="LLM Trading System - Türkçe Komut Satırı Arayüzü",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python cli.py saglik                    # Sağlık kontrolü
  python cli.py calistir --sembol BTC/USDT     # Paper trading başlat
  python cli.py calistir --sembol BTC/USDT --yurut  # Canlı trading
  python cli.py geriye-donuk-test --sembol BTC/USDT --gun 90
  python cli.py portfoy                 # Portföy durumu
  python cli.py tarama                      # Piyasa taraması
  python cli.py durum                    # Sistem durumu
  python cli.py kayitlar                      # Kayıtları göster
  python cli.py testler                     # Test paketi
        """,
    )
    
    alt_parserlar = parser.add_subparsers(dest="komut", help="Komutlar")
    
    # Sağlık kontrolü
    saglik_parser = alt_parserlar.add_parser("saglik", help="Sağlık kontrolü")
    saglik_parser.set_defaults(func=cmd_saglik)
    
    # Bot çalıştır
    calistir_parser = alt_parserlar.add_parser("calistir", help="Trading bot'u çalıştır")
    calistir_parser.add_argument("--sembol", "-s", required=True, help="Sembol (örn: BTC/USDT)")
    calistir_parser.add_argument("--aralik", "-a", default="1h", help="Aralık (5m, 15m, 30m, 1h, 4h)")
    calistir_parser.add_argument("--bekci", "-b", action="store_true", help="Flash crash koruması")
    calistir_parser.add_argument("--yurut", "-y", action="store_true", help="Canlı işlem (DİKKAT!)")
    calistir_parser.add_argument("--oto-tarama", action="store_true", help="Otomatik piyasa taraması")
    calistir_parser.add_argument("--maks-dongu", type=int, default=0, help="Maksimum döngü sayısı (0=sınırsız)")
    calistir_parser.set_defaults(func=cmd_calistir)
    
    # Geriye dönük test
    geriye_parser = alt_parserlar.add_parser("geriye-donuk-test", help="Geriye dönük test çalıştır")
    geriye_parser.add_argument("--sembol", "-s", required=True, help="Sembol")
    geriye_parser.add_argument("--gun", "-g", type=int, default=90, help="Geçmiş gün sayısı")
    geriye_parser.set_defaults(func=cmd_geriye_donuk_test)
    
    # Portföy
    portfoy_parser = alt_parserlar.add_parser("portfoy", help="Portföy durumu")
    portfoy_parser.set_defaults(func=cmd_portfoy)
    
    # Testler
    testler_parser = alt_parserlar.add_parser("testler", help="Test paketi çalıştır")
    testler_parser.add_argument("--ayrintili", "-a", action="store_true", help="Detaylı çıktı")
    testler_parser.set_defaults(func=cmd_testler)
    
    # Kayıtlar
    kayitlar_parser = alt_parserlar.add_parser("kayitlar", help="Kayıtları (log) göster")
    kayitlar_parser.add_argument("--satir", "-n", type=int, default=50, help="Satır sayısı")
    kayitlar_parser.set_defaults(func=cmd_kayitlar)
    
    # Tarama
    tarama_parser = alt_parserlar.add_parser("tarama", help="Piyasa taraması")
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
