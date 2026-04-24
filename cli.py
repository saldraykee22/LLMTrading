"""
LLM Trading System - Komut Satırı Arayüzü (CLI)
================================================
Türkçe kullanıcı dostu, Typer tabanlı komut satırı arayüzü.

Kullanım:
    python cli.py --help
    python cli.py saglik
    python cli.py calistir --sembol BTC/USDT
    python cli.py geriye-donuk-test --sembol BTC/USDT --gun 90
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

# Proje kökünü path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

app = typer.Typer(
    help="LLM Trading System - Türkçe Komut Satırı Arayüzü",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()


def print_baslik(baslik: str) -> None:
    """Başlık yazdır."""
    console.print(f"\n[bold cyan]{'=' * 70}[/]")
    console.print(f"[bold cyan]  {baslik.center(66)}[/]")
    console.print(f"[bold cyan]{'=' * 70}[/]\n")


def print_bolum(bolum_adi: str) -> None:
    """Bölüm başlığı yazdır."""
    console.print(f"\n[bold magenta]> {bolum_adi}[/]")
    console.print(f"[magenta]{'-' * 50}[/]")


@app.command("saglik")
def cmd_saglik():
    """Sistem sağlık kontrolü yapar."""
    from scripts.health_check import main as saglik_ana
    sys.exit(saglik_ana())


@app.command("calistir")
def cmd_calistir(
    sembol: str = typer.Option("AUTO", "--sembol", "-s", help="Sembol veya AUTO (otomatik tarama)"),
    aralik: str = typer.Option("1h", "--aralik", "-a", help="Aralık (5m, 15m, 30m, 1h, 4h)"),
    bekci: bool = typer.Option(False, "--bekci", "-b", help="Flash crash koruması"),
    yurut: bool = typer.Option(False, "--yurut", "-y", help="Canlı işlem (DİKKAT!)"),
    oto_tarama: bool = typer.Option(False, "--oto-tarama", help="Otomatik piyasa taraması"),
    maks_dongu: int = typer.Option(0, "--maks-dongu", help="Maksimum döngü sayısı (0=sınırsız)"),
    model: str = typer.Option("qwen/qwen3.5-flash-02-23", "--model", "-m", help="LLM modeli"),
    arka_plan: bool = typer.Option(False, "--arka-plan", help="Arka planda (daemon) çalıştır (konsolu bloklamaz)"),
):
    """Trading bot'u çalıştırır."""
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_live.py"),
        "--symbol", sembol,
        "--interval", aralik,
    ]
    
    if bekci:
        cmd.append("--watchdog")
    if yurut:
        cmd.append("--execute")
    if oto_tarama:
        cmd.append("--auto-scan")
    if maks_dongu:
        cmd.extend(["--max-cycles", str(maks_dongu)])
    if model:
        cmd.extend(["--model", model])

    console.print(Panel.fit(
        f"[bold]Sembol:[/] {sembol}\n"
        f"[bold]Aralık:[/] {aralik}\n"
        f"[bold]Mod:[/] {'[red]CANLI İŞLEM[/red]' if yurut else '[green]PAPER TRADING[/green]'}\n"
        f"[bold]Arka Plan:[/] {'[green]Evet[/green]' if arka_plan else '[yellow]Hayır[/yellow]'}",
        title="Bot Başlatılıyor", border_style="cyan"
    ))
    
    try:
        if arka_plan:
            # Arka planda çalıştır (detach process)
            if sys.platform == "win32":
                subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                log_file = open(PROJECT_ROOT / "logs" / "daemon_trading.log", "a")
                subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
            console.print("[green]✓ Bot arka planda başlatıldı![/green]")
            console.print("Logları izlemek için: [bold cyan]python cli.py kayitlar[/bold cyan]")
        else:
            subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        console.print("\n\n[bold yellow][BİLGİ] Kullanıcı tarafından durduruldu.[/bold yellow]")
    except subprocess.CalledProcessError as e:
        console.print(f"\n[bold red][HATA] Bot hatası: {e}[/bold red]")
        sys.exit(1)


@app.command("geriye-donuk-test")
def cmd_geriye_donuk_test(
    sembol: str = typer.Option(..., "--sembol", "-s", help="Sembol (örn. BTC/USDT)"),
    gun: int = typer.Option(90, "--gun", "-g", help="Geçmiş gün sayısı"),
    arka_plan: bool = typer.Option(False, "--arka-plan", help="Arka planda (daemon) çalıştır"),
):
    """Geriye dönük test (backtest) çalıştırır."""
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_backtest.py"),
        "--symbol", sembol,
        "--days", str(gun),
    ]
    
    console.print(f"[bold cyan]Geriye Dönük Test Başlatılıyor: {sembol} (Son {gun} gün)[/bold cyan]")

    try:
        if arka_plan:
            if sys.platform == "win32":
                subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                log_file = open(PROJECT_ROOT / "logs" / "daemon_backtest.log", "a")
                subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
            console.print("[green]✓ Backtest arka planda başlatıldı![/green]")
        else:
            subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"\n[bold red][HATA] Backtest hatası: {e}[/bold red]")
        sys.exit(1)


@app.command("portfoy")
def cmd_portfoy():
    """Portföy durumunu gösterir."""
    print_baslik("PORTFÖY DURUMU")
    
    portfoy_dosya = PROJECT_ROOT / "data" / "portfolio_state.json"
    
    if not portfoy_dosya.exists():
        console.print("[yellow][BİLGİ] Henüz açık pozisyon yok.[/yellow]")
        return
    
    try:
        with open(portfoy_dosya, "r", encoding="utf-8") as f:
            veri = json.load(f)
        
        ozet_tablo = Table(show_header=False, box=None)
        ozet_tablo.add_row("Başlangıç Nakit:", f"[blue]${veri.get('initial_cash', 0):,.2f}[/]")
        ozet_tablo.add_row("Şu Anki Nakit:", f"[green]${veri.get('cash', 0):,.2f}[/]")
        ozet_tablo.add_row("Toplam Özvarlık:", f"[bold cyan]${veri.get('equity', 0):,.2f}[/]")

        toplam_pnl = veri.get('total_pnl', 0)
        pnl_renk = "green" if toplam_pnl >= 0 else "red"
        ozet_tablo.add_row("Toplam K/Z:", f"[{pnl_renk}]${toplam_pnl:+,.2f}[/]")

        gunluk_pnl = veri.get('daily_pnl', 0)
        gpnl_renk = "green" if gunluk_pnl >= 0 else "red"
        ozet_tablo.add_row("Günlük K/Z:", f"[{gpnl_renk}]${gunluk_pnl:+,.2f}[/]")
        ozet_tablo.add_row("Maksimum Erime:", f"[red]{veri.get('current_drawdown', 0):.2%}[/]")

        console.print(ozet_tablo)
        
        pozisyonlar = veri.get("positions", [])
        if pozisyonlar:
            print_bolum(f"AÇIK POZİSYONLAR ({len(pozisyonlar)})")

            poz_tablo = Table(show_header=True, header_style="bold cyan")
            poz_tablo.add_column("Sembol")
            poz_tablo.add_column("Taraf")
            poz_tablo.add_column("Giriş", justify="right")
            poz_tablo.add_column("Miktar", justify="right")
            poz_tablo.add_column("K/Z", justify="right")

            for poz in pozisyonlar:
                taraf = poz.get('side', 'long').upper()
                taraf_renk = "green" if taraf == "LONG" else "red"
                kz = poz.get('unrealized_pnl', 0)
                kz_renk = "green" if kz >= 0 else "red"

                poz_tablo.add_row(
                    poz.get('symbol'),
                    f"[{taraf_renk}]{taraf}[/]",
                    f"${poz.get('entry_price', 0):,.2f}",
                    f"{poz.get('amount', 0):.6f}",
                    f"[{kz_renk}]${kz:+,.2f}[/]"
                )
            console.print(poz_tablo)
        
    except Exception as e:
        console.print(f"[bold red][HATA] Portföy okunamadı: {e}[/bold red]")
        sys.exit(1)


@app.command("testler")
def cmd_testler(
    ayrintili: bool = typer.Option(False, "--ayrintili", "-a", help="Detaylı çıktı gösterir")
):
    """Test paketini çalıştırır."""
    print_baslik("TEST PAKETİ")
    
    cmd = [
        sys.executable,
        "-m", "pytest",
        str(PROJECT_ROOT / "tests" / "test_integration.py"),
        "-v",
        "--tb=short",
    ]
    
    if ayrintili:
        cmd.append("-s")
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"\n[bold red][HATA] Testler başarısız: {e}[/bold red]")
        sys.exit(1)


@app.command("kayitlar")
def cmd_kayitlar(
    satir: int = typer.Option(50, "--satir", "-n", help="Gösterilecek satır sayısı")
):
    """Kayıtları (log) gösterir."""
    print_baslik(f"SON {satir} KAYIT SATIRI")
    
    kayit_dosya = PROJECT_ROOT / "logs" / "trading.log"
    
    if not kayit_dosya.exists():
        console.print("[yellow][BİLGİ] Henüz kayıt dosyası oluşturulmadı.[/yellow]")
        return
    
    try:
        with open(kayit_dosya, "r", encoding="utf-8") as f:
            satirlar = f.readlines()
        
        for s in satirlar[-satir:]:
            if "ERROR" in s or "CRITICAL" in s:
                console.print(f"[red]{s.strip()}[/]")
            elif "WARNING" in s:
                console.print(f"[yellow]{s.strip()}[/]")
            else:
                console.print(s.strip())

    except Exception as e:
        console.print(f"[bold red][HATA] Kayıt okunamadı: {e}[/bold red]")
        sys.exit(1)


@app.command("tarama")
def cmd_tarama():
    """Piyasa taraması yapar."""
    from data.scanner import MarketScanner
    
    print_baslik("PİYASA TARAMASI")
    
    tarayici = MarketScanner()
    
    with console.status("[bold green]Adaylar Taranıyor...[/bold green]"):
        try:
            adaylar = tarayici.get_candidates()
        except Exception as e:
            console.print(f"[bold red]❌ Tarama hatası: {e}[/bold red]")
            sys.exit(1)
    
    if not adaylar:
        console.print("[yellow]Kriterlere uygun aday bulunamadı.[/yellow]")
        return
    
    console.print(f"[green]✓ {len(adaylar)} aday bulundu.[/green]\n")
    
    tablo = Table(title="Önerilen Varlıklar (İlk 10)", show_header=True, header_style="bold cyan")
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
            
            renk = "green" if degisim >= 0 else "red"

            tablo.add_row(
                sembol,
                f"${fiyat:,.4f}",
                f"${hacim:,.0f}",
                f"[{renk}]{degisim:+.2f}%[/]",
                f"{skor:.1f}",
            )
    
    console.print(tablo)


@app.command("durum")
def cmd_durum():
    """Sistem ve portföy durumunu gösterir."""
    print_baslik("SİSTEM DURUMU")
    
    # Circuit Breaker Durumu
    from risk.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    cb_durum = cb.get_status()
    
    cb_renk = "red" if cb_durum.get('halted') else "green"
    cb_metin = "AKTİF (DURDURULDU)" if cb_durum.get('halted') else "PASİF (ÇALIŞIYOR)"
    
    panel_veri = f"[bold]Circuit Breaker:[/] [{cb_renk}]{cb_metin}[/{cb_renk}]\n"
    if cb_durum.get('halt_reason'):
        panel_veri += f"[bold]Sebep:[/] {cb_durum['halt_reason']}\n"
    panel_veri += f"[bold]Art Arda Kayıp:[/] {cb_durum.get('consecutive_losses', 0)}\n"
    panel_veri += f"[bold]Art Arda LLM Hatası:[/] {cb_durum.get('consecutive_llm_errors', 0)}"
    
    console.print(Panel(panel_veri, title="Circuit Breaker", border_style=cb_renk))
    
    # Portföy Durumu
    try:
        from risk.portfolio import PortfolioState
        portfoy = PortfolioState.load_from_file()

        portfoy_tablo = Table(title="Portföy Özeti", show_header=False, box=None)
        portfoy_tablo.add_row("[bold]Özvarlık[/]", f"[cyan]${portfoy.equity:,.2f}[/cyan]")
        portfoy_tablo.add_row("[bold]Nakit[/]", f"${portfoy.cash:,.2f}")
        portfoy_tablo.add_row("[bold]Açık Pozisyon[/]", str(portfoy.open_position_count))
        portfoy_tablo.add_row("[bold]Toplam K/Z[/]", f"${portfoy.total_pnl:,.2f}")
        portfoy_tablo.add_row("[bold]Günlük K/Z[/]", f"${portfoy.daily_pnl:,.2f}")
        portfoy_tablo.add_row("[bold]Erime (Drawdown)[/]", f"[red]{portfoy.current_drawdown:.2%}[/red]")

        console.print(portfoy_tablo)
    except Exception as e:
        console.print(f"[yellow]Portföy bilgisi alınamadı: {e}[/yellow]")


@app.command("fallbacklar")
def cmd_fallbacklar(
    limit: int = typer.Option(10, "--limit", "-l", help="Gösterilecek kayıt sayısı")
):
    """Son fallback kayıtlarını gösterir."""
    from data.fallback_store import get_fallback_store
    store = get_fallback_store()
    fallbacks = store.get_fallbacks(limit=limit)
    summary = store.get_fallback_summary(hours=24)
    
    if not fallbacks:
        console.print("[yellow]Fallback kaydı bulunamadı.[/yellow]")
        return
    
    console.print(f"\n[bold cyan]Fallback Özeti (Son 24s)[/]")
    console.print(f"  Toplam: {summary['total_fallbacks']}")
    if summary.get('by_agent'):
        console.print(f"  Ajanlara göre:")
        for agent, count in summary['by_agent'].items():
            console.print(f"    - {agent}: {count}")
    
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


@app.command("circuit-breaker")
def cmd_circuit_breaker():
    """Circuit breaker detaylı durumunu gösterir."""
    from risk.circuit_breaker import CircuitBreaker
    from config.settings import get_trading_params

    cb = CircuitBreaker()
    status = cb.get_status()
    params = get_trading_params()
    
    console.print(f"\n[bold]Circuit Breaker Durumu[/]")
    
    if status['halted']:
        console.print(f"  Durum: [bold red]DURDURULDU[/]")
        console.print(f"  Neden: [red]{status['halt_reason']}[/]")
    else:
        console.print(f"  Durum: [bold green]AKTİF[/]")
    
    console.print(f"\n  Sayaçlar:")

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
    console.print(f"    LLM Hataları: [{llm_color}]{llm_count}/{llm_max}[/{llm_color}] [{llm_bar}]")

    # Losses
    loss_count = status['consecutive_losses']
    loss_max = params.risk.max_consecutive_losses
    loss_pct = (loss_count / loss_max) * 100 if loss_max > 0 else 0
    loss_color = "red" if loss_count >= loss_max - 1 else "yellow" if loss_count >= loss_max // 2 else "green"
    loss_bar = '#' * int(loss_pct/10) + '-' * (10 - int(loss_pct/10))
    console.print(f"    Kayıplar:     [{loss_color}]{loss_count}/{loss_max}[/{loss_color}] [{loss_bar}]")


@app.command("circuit-breaker-sifirla")
def cmd_circuit_breaker_sifirla():
    """Circuit breaker sayaçlarını sıfırlar."""
    if Confirm.ask("[yellow]Tüm circuit breaker sayaçları sıfırlansın mı?[/]"):
        from risk.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        cb.reset_fallbacks()
        cb.reset_llm_errors()
        cb.consecutive_losses = 0
        cb._save_state()
        console.print("[bold green]✓ Circuit breaker sayaçları sıfırlandı.[/bold green]")


@app.command("hesaplar")
def cmd_hesaplar():
    """Tüm hesapların durumunu gösterir."""
    from config.settings import get_settings
    from execution.account_manager import MultiAccountManager
    
    settings = get_settings()
    
    if not settings.binance_accounts:
        console.print("[yellow]Multi-account (Çoklu hesap) yapılandırması bulunamadı.[/yellow]")
        return
    
    try:
        manager = MultiAccountManager(settings.binance_accounts)
        summary = manager.get_status_summary()
        
        console.print(f"\n[bold cyan]Hesap Durumu[/]")
        console.print(f"  Toplam Hesap: {summary['total_accounts']}")
        console.print(f"  Aktif Hesap:  {summary['active_accounts']}\n")
        
        table = Table(title="Hesaplar", show_lines=True)
        table.add_column("Ad", style="cyan", width=15)
        table.add_column("Durum", style="magenta", width=10)
        table.add_column("Özvarlık", style="green", width=15)
        table.add_column("Nakit", style="blue", width=15)
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
        
        if summary['total_accounts'] > 1:
            total_equity = sum(acc['equity'] for acc in summary['accounts'].values())
            total_cash = sum(acc['cash'] for acc in summary['accounts'].values())
            total_positions = sum(acc['open_positions'] for acc in summary['accounts'].values())
            
            console.print(f"\n[bold]★ Kombin Görünüm (Tüm Hesaplar)[/]")
            console.print(f"  Toplam Özvarlık:  [green]${total_equity:,.2f}[/]")
            console.print(f"  Toplam Nakit:    [blue]${total_cash:,.2f}[/]")
            console.print(f"  Toplam Pozisyon: {total_positions}\n")

    except Exception as e:
        console.print(f"[bold red]Hata: {e}[/bold red]")


@app.command("dashboard")
def cmd_dashboard():
    """Web dashboard URL'sini gösterir."""
    console.print(f"\n[bold cyan]Web Dashboard[/]")
    console.print(f"  URL: [link=http://localhost:8000]http://localhost:8000[/]")
    console.print(f"  API: [link=http://localhost:8000/docs]http://localhost:8000/docs[/]")
    console.print(f"\n  Başlatmak için: [bold cyan]python dashboard/server.py[/bold cyan]\n")


if __name__ == "__main__":
    app()
