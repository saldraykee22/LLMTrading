"""
LLM Trading System — Portföy Yönetimi Scripti
===============================================
Birden fazla varlığı analiz eder, skorlar ve optimal portföy dağılımı yapar.

Kullanım:
    python scripts/run_portfolio.py --symbols BTC/USDT,ETH/USDT,SOL/USDT
    python scripts/run_portfolio.py --symbols BTC/USDT,ETH/USDT,SOL/USDT,AVAX/USDT --max-positions 3
    python scripts/run_portfolio.py --symbols BTC/USDT,ETH/USDT --provider deepseek
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows console encoding fix
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Proje kökünü path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from agents.portfolio_manager import PortfolioManager
from config.settings import get_trading_params

console = Console()


def setup_logging(level: str = "INFO") -> None:
    """Rich tabanlı loglama ayarla."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )


def run_portfolio(
    symbols: list[str],
    max_positions: int | None = None,
    min_score: float = 0.1,
    provider: str | None = None,
    max_workers: int = 3,
) -> dict:
    """
    Portföy analizi ve dağılımı çalıştırır.

    Args:
        symbols: Analiz edilecek semboller
        max_positions: Maksimum açık pozisyon sayısı
        min_score: Minimum bileşik skor eşiği
        provider: LLM sağlayıcı override
        max_workers: Aynı anda kaç sembol analiz edilsin (parallel)

    Returns:
        Portföy dağılımı sonucu
    """
    params = get_trading_params()

    # ── Portföy yükleme (persistence) ─────────────────────
    from risk.portfolio import PortfolioState

    portfolio = PortfolioState.load_from_file()
    portfolio.reset_daily_pnl_if_needed()

    # ── Circuit Breaker kontrolü ───────────────────────────
    from risk.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker()
    should_halt, halt_reason = cb.should_halt(
        equity=portfolio.equity, daily_pnl=portfolio.daily_pnl
    )
    if should_halt:
        console.print(f"[bold red]CIRCUIT BREAKER: {halt_reason}[/bold red]")
        return {"status": "halted", "reason": halt_reason}

    console.print(
        Panel(
            f"[bold cyan]Portföy Yöneticisi[/bold cyan]\n"
            f"Semboller: {', '.join(symbols)}\n"
            f"Max pozisyon: {max_positions or params.risk.max_open_positions}\n"
            f"Min skor eşiği: {min_score:.2f}\n"
            f"Mod: {params.execution.mode.value}\n"
            f"Ozvarlık: ${portfolio.equity:,.2f}\n"
            f"Zaman: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            title="Portföy Analizi Başlatılıyor",
            border_style="cyan",
        )
    )

    # ── Portfolio Manager ─────────────────────────────────
    pm = PortfolioManager(
        symbols=symbols,
        max_positions=max_positions,
        min_score_threshold=min_score,
        provider=provider,
    )

    # 1. Tüm sembolleri analiz et
    console.print("\n[bold yellow]1. Sembol Analizleri[/bold yellow]")
    console.print(f"  {len(symbols)} sembol için pipeline çalıştırılıyor...")
    console.print("  Her sembol: Coordinator → Research → Debate → Risk\n")

    analyses = pm.analyze_all(max_workers=max_workers)

    # 2. Analiz skorlarını göster
    console.print("\n[bold yellow]2. Analiz Skorları[/bold yellow]")
    score_table = Table(show_header=True, border_style="cyan")
    score_table.add_column("Sembol", style="bold")
    score_table.add_column("Skor", justify="right")
    score_table.add_column("Sentiment", justify="right")
    score_table.add_column("Debate", justify="right")
    score_table.add_column("Trend", justify="center")
    score_table.add_column("RSI", justify="right")
    score_table.add_column("Risk", justify="center")

    for sym, ana in sorted(
        analyses.items(), key=lambda x: x[1].composite_score, reverse=True
    ):
        if ana.raw_result.get("error"):
            score_table.add_row(
                sym,
                "[red]HATA[/red]",
                "-",
                "-",
                "-",
                "-",
                "-",
            )
            continue

        score_color = (
            "green"
            if ana.composite_score > 0.2
            else "yellow"
            if ana.composite_score > 0
            else "red"
        )
        score_table.add_row(
            sym,
            f"[{score_color}]{ana.composite_score:+.3f}[/{score_color}]",
            f"{ana.sentiment_score:+.2f}",
            f"{ana.debate_consensus:+.2f}",
            ana.trend,
            f"{ana.rsi:.1f}",
            "OK" if ana.risk_approved else "RED",
        )

    console.print(score_table)

    # 3. Portföy dağılımı oluştur
    console.print("\n[bold yellow]3. Portföy Dağılımı[/bold yellow]")
    console.print("  CVaR optimizasyonu ve skor bazlı alokasyon hesaplanıyor...\n")

    result = pm.build_portfolio()

    if result["status"] == "no_qualified_assets":
        console.print(f"[bold red]{result['reason']}[/bold red]")
        console.print("\n[dim]Tüm skorlar:[/dim]")
        for sym, score in result.get("all_scores", {}).items():
            console.print(f"  {sym}: {score:+.3f}")
        return result

    # 4. Dağılım tablosu
    alloc_table = Table(show_header=True, border_style="green")
    alloc_table.add_column("Sembol", style="bold")
    alloc_table.add_column("Ağırlık", justify="right")
    alloc_table.add_column("Nakıt Değeri", justify="right")
    alloc_table.add_column("Skor", justify="right")
    alloc_table.add_column("Trend", justify="center")
    alloc_table.add_column("Güven", justify="right")

    details = result.get("asset_details", {})
    for sym in sorted(
        details.keys(), key=lambda s: details[s]["allocation_pct"], reverse=True
    ):
        d = details[sym]
        cash_value = d["allocation_pct"] / 100 * portfolio.equity
        alloc_table.add_row(
            sym,
            f"{d['allocation_pct']:.1f}%",
            f"${cash_value:,.2f}",
            f"{d['composite_score']:+.3f}",
            d["trend"],
            f"{d['sentiment_confidence']:.2f}",
        )

    console.print(alloc_table)

    # 5. CVaR bilgisi
    cvar = result.get("cvar_info", {})
    if cvar:
        console.print(
            f"\n[dim]CVaR: {cvar.get('cvar', 0):.4%} | "
            f"VaR: {cvar.get('var', 0):.4%} | "
            f"Beklenen Getiri: {cvar.get('expected_return', 0):.2%}[/dim]"
        )

    # 6. Reddedilen varlıklar
    all_scores = result.get("all_scores", {})
    selected = set(result.get("allocations", {}).keys())
    excluded = {s: all_scores[s] for s in all_scores if s not in selected}
    if excluded:
        console.print("\n[bold yellow]Dışlanan Varlıklar:[/bold yellow]")
        for sym, info in sorted(
            excluded.items(), key=lambda x: x[1].get("composite_score", 0)
        ):
            score = info.get("composite_score", 0)
            reason = "skor düşük" if score < min_score else "max pozisyon limiti"
            console.print(f"  [dim]{sym}: {score:+.3f} ({reason})[/dim]")

    # ── Portföy kaydetme (persistence) ────────────────────
    portfolio.update_drawdown()
    portfolio.save_to_file()

    # Sonucu JSON dosyasına kaydet
    output_dir = PROJECT_ROOT / "data" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    symbols_str = "_".join(s.replace("/", "_") for s in symbols[:5])
    output_file = output_dir / f"portfolio_{symbols_str}_{ts}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    console.print(f"\n[dim]Portföy kaydedildi: {output_file}[/dim]")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Trading Portföy Yöneticisi")
    parser.add_argument(
        "--symbols",
        "-s",
        required=True,
        help="Virgülle ayrılmış semboller (örn: BTC/USDT,ETH/USDT,SOL/USDT)",
    )
    parser.add_argument(
        "--max-positions",
        "-m",
        type=int,
        default=None,
        help="Maksimum açık pozisyon sayısı",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.1,
        help="Minimum bileşik skor eşiği (varsayılan: 0.1)",
    )
    parser.add_argument(
        "--provider",
        "-p",
        choices=["openrouter", "deepseek", "ollama"],
        help="LLM sağlayıcı",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=3,
        help="Aynı anda kaç sembol analiz edilsin (varsayılan: 3)",
    )
    parser.add_argument("--log-level", "-l", default="INFO", help="Log seviyesi")

    args = parser.parse_args()

    setup_logging(args.log_level)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        console.print("[bold red]Hiç sembol belirtilmedi![/bold red]")
        sys.exit(1)

    result = run_portfolio(
        symbols=symbols,
        max_positions=args.max_positions,
        min_score=args.min_score,
        provider=args.provider,
        max_workers=args.workers,
    )

    console.print(f"\n[green]Portföy analizi tamamlandı ({result['status']})[/green]")


if __name__ == "__main__":
    main()
