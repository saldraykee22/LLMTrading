"""
İnteraktif Komut Sistemi - Windows Uyumlu
==========================================
Her cycle sonunda kullanıcıya "/" komutları ile sistem durumu gösterir.
"""
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

# Windows UTF-8 fix
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# Notlar dosyası
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
NOTES_FILE = DATA_DIR / "user_notes.jsonl"

_notes_lock = threading.Lock()


def show_help():
    """Yardım mesajı göster."""
    help_table = Table(show_header=False, box=None, padding=(0, 2))
    help_table.add_column("Komut", style="cyan", width=15)
    help_table.add_column("Açıklama", style="white")
    
    help_table.add_row("/durum", "Anlık sistem durumu")
    help_table.add_row("/pozisyon", "Açık pozisyonlar ve PnL")
    help_table.add_row("/fallback", "Fallback istatistikleri")
    help_table.add_row("/circuit", "Circuit breaker durumu")
    help_table.add_row("/log", "Son 10 hata logu")
    help_table.add_row("/not-yaz", "Kullanıcı notu ekle")
    help_table.add_row("/notlar", "Tüm notları göster")
    help_table.add_row("/yardim", "Bu yardım mesajı")
    help_table.add_row("/cikis", "Normal görünüme dön")
    
    console.print(Panel(help_table, title="📋 KOMUTLAR", border_style="blue"))


def cmd_durum(portfolio=None, cycle=0, start_time=None, cb=None):
    """Sistem durumu göster."""
    if cb is None:
        from risk.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
    
    cb_status = cb.get_status()
    
    # Bot uptime
    uptime = ""
    if start_time:
        delta = datetime.now(timezone.utc) - start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        uptime = f"{hours}s {minutes}dk"
    
    # Portfolio stats
    positions = portfolio.get_positions_safe() if portfolio else []
    equity_str = f"${portfolio.equity:,.2f}" if portfolio else "N/A"
    pnl_str = f"${portfolio.total_pnl:,.2f}" if portfolio else "N/A"
    positions_str = str(len(positions)) if portfolio else "0"
    
    status_table = Table(show_header=False, box=None, padding=(0, 2))
    status_table.add_column("Özellik", style="cyan", width=20)
    status_table.add_column("Değer", style="white")
    
    status_table.add_row("Bot Durumu", "🟢 ÇALIŞIYOR")
    status_table.add_row("Çalışma Süresi", uptime if uptime else "Bilinmiyor")
    status_table.add_row("Cycle", f"{cycle} tamamlandı")
    status_table.add_row("Özvarlık", equity_str)
    status_table.add_row("Toplam PnL", pnl_str)
    status_table.add_row("Açık Pozisyon", positions_str)
    status_table.add_row("Fallback", f"{cb_status['consecutive_fallbacks']}/5 {'✓' if cb_status['consecutive_fallbacks'] < 3 else '⚠️'}")
    status_table.add_row("Circuit Breaker", f"{cb_status['consecutive_fallbacks']}/5 {'✓' if not cb_status['halted'] else '🔴'}")
    
    console.print(Panel(status_table, title="📈 SİSTEM DURUMU", border_style="green"))


def cmd_pozisyon(portfolio=None):
    """Açık pozisyonları göster."""
    if not portfolio or not portfolio.get_positions_safe():
        console.print(Panel("Açık pozisyon yok", title="💼 POZİSYONLAR", border_style="yellow"))
        return
    
    pos_table = Table(title="Açık Pozisyonlar", show_header=True)
    pos_table.add_column("Sembol", style="cyan")
    pos_table.add_column("Yön", style="magenta")
    pos_table.add_column("Boyut", justify="right", style="white")
    pos_table.add_column("Giriş", justify="right", style="white")
    pos_table.add_column("PnL", justify="right", style="green")
    
    total_pnl = 0
    for pos in portfolio.get_positions_safe():
        pnl = pos.unrealized_pnl
        total_pnl += pnl
        pnl_str = f"${pnl:+,.2f}"
        pnl_style = "green" if pnl >= 0 else "red"
        
        pos_table.add_row(
            pos.symbol,
            "Long",
            f"${pos.amount * pos.entry_price:,.0f}",
            f"${pos.entry_price:,.2f}",
            f"[{pnl_style}]{pnl_str}[/{pnl_style}]"
        )
    
    pos_table.add_row("", "", "", "Toplam:", f"[{'green' if total_pnl >= 0 else 'red'}]${total_pnl:+,.2f}[/{'green' if total_pnl >= 0 else 'red'}]")
    
    console.print(pos_table)


def cmd_fallback():
    """Fallback istatistikleri."""
    from data.fallback_store import get_fallback_store
    
    store = get_fallback_store()
    fallbacks = store.get_fallbacks(limit=10)
    summary = store.get_fallback_summary(hours=24)
    
    fb_table = Table(show_header=False, box=None, padding=(0, 2))
    fb_table.add_column("Metrik", style="cyan", width=20)
    fb_table.add_column("Değer", style="white")
    
    fb_table.add_row("Toplam Fallback", str(summary['total_fallbacks']))
    fb_table.add_row("Limit", "5")
    fb_table.add_row("Durum", "✓ Normal" if summary['total_fallbacks'] < 5 else "⚠️ Yüksek")
    
    console.print(Panel(fb_table, title="⚠️ FALLBACK İSTATİSTİKLERİ", border_style="yellow"))
    
    if fallbacks:
        console.print("\n[dim]Son 10 fallback:[/dim]")
        for fb in fallbacks[:5]:
            time_str = datetime.fromisoformat(fb['timestamp']).strftime('%H:%M')
            console.print(f"  [{time_str}] {fb['agent']} - {fb['reason'][:50]}")


def cmd_circuit():
    """Circuit breaker durumu."""
    from risk.circuit_breaker import CircuitBreaker
    
    cb = CircuitBreaker()
    status = cb.get_status()
    
    cb_table = Table(show_header=False, box=None, padding=(0, 2))
    cb_table.add_column("Sayaç", style="cyan", width=20)
    cb_table.add_column("Değer", style="white")
    
    cb_table.add_row("Fallbacklar", f"{status['consecutive_fallbacks']}/5")
    cb_table.add_row("LLM Hataları", f"{status['consecutive_llm_errors']}/10")
    cb_table.add_row("Kayıplar", f"{status['consecutive_losses']}/5")
    cb_table.add_row("Durum", "🟢 AKTİF" if not status['halted'] else "🔴 DURDURULDU")
    
    if status['halt_reason']:
        cb_table.add_row("Neden", status['halt_reason'])
    
    console.print(Panel(cb_table, title="🔌 CIRCUIT BREAKER", border_style="red" if status['halted'] else "green"))


def cmd_log():
    """Son 10 hata logu."""
    from data.fallback_store import get_fallback_store
    
    store = get_fallback_store()
    fallbacks = store.get_fallbacks(limit=10)
    
    if not fallbacks:
        console.print(Panel("Son 24 saatte hata yok", title="📋 HATA LOGU", border_style="green"))
        return
    
    console.print(f"[bold]Son {len(fallbacks)} fallback:[/bold]\n")
    for i, fb in enumerate(fallbacks[:10], 1):
        time_str = datetime.fromisoformat(fb['timestamp']).strftime('%Y-%m-%d %H:%M')
        console.print(f"{i:2}. [{time_str}] [cyan]{fb['agent']}[/cyan]: {fb['reason'][:60]}")


def cmd_not_yaz():
    """Kullanıcı notu ekle."""
    try:
        note = input("Notunuzu yazın: ").strip()
        if not note:
            console.print("[yellow]Boş not eklenemez[/yellow]")
            return
        
        save_note(note)
        console.print(f"[green]✓ Not eklendi ({datetime.now().strftime('%H:%M')})[/green]")
    except Exception as e:
        console.print(f"[red]Hata: {e}[/red]")


def save_note(note: str, category: str = "observation", priority: str = "normal"):
    """Notu kaydet."""
    with _notes_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Son ID'yi bul
        last_id = 0
        if NOTES_FILE.exists():
            with open(NOTES_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            last_id = max(last_id, data.get('id', 0))
                        except:
                            pass
        
        note_data = {
            'id': last_id + 1,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'note': note,
            'category': category,
            'priority': priority,
        }
        
        with open(NOTES_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(note_data, ensure_ascii=False) + '\n')
            f.flush()  # Hemen yaz


def cmd_notlar():
    """Tüm notları göster."""
    if not NOTES_FILE.exists():
        console.print(Panel("Henüz not yok", title="📝 KULLANICI NOTLARI", border_style="blue"))
        return
    
    notes = []
    with open(NOTES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    notes.append(json.loads(line))
                except:
                    pass
    
    if not notes:
        console.print(Panel("Henüz not yok", title="📝 KULLANICI NOTLARI", border_style="blue"))
        return
    
    # Son 10 not
    notes = sorted(notes, key=lambda x: x.get('timestamp', ''), reverse=True)[:10]
    
    console.print(f"[bold]📝 KULLANICI NOTLARI (son {len(notes)})[/bold]\n")
    for note in notes:
        time_str = datetime.fromisoformat(note['timestamp']).strftime('%Y-%m-%d %H:%M')
        emoji = "📝" if note.get('category') == 'observation' else "⏰" if note.get('category') == 'reminder' else "⚠️"
        console.print(f"[{time_str}] {emoji} {note['note']}")
    
    console.print(f"\n[dim]Toplam {len(notes)} not. Silmek için: python cli.py not-sil <id>[/dim]")


def cmd_yardim():
    """Yardım mesajı."""
    show_help()


def cmd_cikis():
    """Normal görünüme dön."""
    console.print("[dim]Normal görünüme dönüldü. Bot çalışmaya devam ediyor...[/dim]")


def handle_command(cmd: str, portfolio=None, cycle=0, start_time=None, cb=None):
    """Komutu işle."""
    cmd = cmd.strip().lower()
    
    if not cmd or cmd == '/':
        show_help()
        return True  # Komut modunda kal
    
    if cmd.startswith('/'):
        cmd = cmd[1:]
    
    cmd_parts = cmd.split(' ', 1)
    cmd_name = cmd_parts[0]
    
    commands = {
        'durum': lambda: cmd_durum(portfolio, cycle, start_time, cb),
        'pozisyon': lambda: cmd_pozisyon(portfolio),
        'fallback': cmd_fallback,
        'circuit': cmd_circuit,
        'log': cmd_log,
        'not-yaz': cmd_not_yaz,
        'notlar': cmd_notlar,
        'yardim': cmd_yardim,
        'cikis': cmd_cikis,
        'q': cmd_cikis,
        'd': lambda: cmd_durum(portfolio, cycle, start_time, cb),
        'p': lambda: cmd_pozisyon(portfolio),
        'f': cmd_fallback,
        'c': cmd_circuit,
        'l': cmd_log,
        'n': cmd_notlar,
        'h': cmd_yardim,
        'x': cmd_cikis,
    }
    
    if cmd_name in commands:
        commands[cmd_name]()
        return True
    else:
        console.print(f"[yellow]❌ Bilinmeyen komut: {cmd_name}[/yellow]")
        console.print("[dim]Yardım için '/' yazın.[/dim]")
        return True


def cycle_end_prompt(portfolio, cycle, start_time, cb):
    """Cycle sonunda kullanıcıya komut fırsatı ver."""
    console.print("\n[dim]Komut için '/' yazın, devam için Enter'a basın:[/dim]")
    try:
        user_input = input("> ").strip()
        if user_input == '/':
            show_help()
            # Tekrar input al
            user_input = input("> ").strip()
        
        if user_input:
            handle_command(user_input, portfolio, cycle, start_time, cb)
            return True  # Komut girildi
        return False  # Enter'a basıldı, devam et
    except (EOFError, KeyboardInterrupt):
        return False
