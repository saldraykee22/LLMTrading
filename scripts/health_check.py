"""
LLM Trading System - Health Check Script
==========================================
Sistem saÄŸlÄ±k kontrolÃ¼ - BaÅŸlangÄ±Ã§ validasyonu
KullanÄ±m: python scripts/health_check.py
"""

import sys
from pathlib import Path

# Proje kÃ¶kÃ¼nÃ¼ path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_python_version() -> dict:
    """Python versiyonunu kontrol et."""
    return {
        "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "status": "OK" if sys.version_info >= (3, 10) else "FAIL",
    }


def check_dependencies() -> dict:
    """Kritik kÃ¼tÃ¼phaneleri kontrol et."""
    results = {}
    
    critical_packages = {
        "ccxt": "Borsa baÄŸlantÄ±sÄ±",
        "langchain": "LLM framework",
        "chromadb": "VektÃ¶r veritabanÄ±",
        "pydantic": "Config validation",
        "pandas": "Data analysis",
        "rich": "Console output",
    }
    
    for pkg, desc in critical_packages.items():
        try:
            mod = __import__(pkg)
            version = getattr(mod, "__version__", "unknown")
            results[pkg] = f"OK {version}"
        except ImportError:
            results[pkg] = f"MISSING ({desc})"
    
    return results


def check_env_file() -> dict:
    """.env dosyasÄ±nÄ± kontrol et."""
    env_file = PROJECT_ROOT / ".env"
    
    if not env_file.exists():
        return {"status": "âŒ", "message": ".env dosyasÄ± bulunamadÄ±"}
    
    # API anahtarlarÄ±nÄ±n varlÄ±ÄŸÄ±nÄ± kontrol et
    content = env_file.read_text()
    
    checks = {
        "OPENROUTER_API_KEY": "openrouter" in content.lower(),
        "BINANCE_API_KEY": "binance" in content.lower(),
    }
    
    results = []
    for key, present in checks.items():
        status = "OK" if present else "WARN"
        results.append(f"{status} {key}")
    
    return {
        "status": "OK" if all(checks.values()) else "WARN",
        "details": results,
    }


def check_api_keys() -> dict:
    """API anahtarlarÄ±nÄ± kontrol et (deÄŸerleri gÃ¶stermeden)."""
    try:
        from config.settings import get_settings
        
        settings = get_settings()
        
        checks = {
            "OpenRouter": bool(settings.openrouter_api_key),
            "Binance": bool(settings.binance_api_key and settings.binance_api_secret),
            "DeepSeek": bool(settings.deepseek_api_key),
        }
        
        results = {}
        for provider, has_key in checks.items():
            results[provider] = "âœ…" if has_key else "âŒ"
        
        return results
    except Exception as e:
        return {"error": str(e)}


def check_directories() -> dict:
    """Gerekli klasÃ¶rlerin varlÄ±ÄŸÄ±nÄ± kontrol et."""
    from config.settings import DATA_DIR, LOGS_DIR
    
    dirs = {
        "data": DATA_DIR,
        "logs": LOGS_DIR,
        "config": PROJECT_ROOT / "config",
    }
    
    results = {}
    for name, path in dirs.items():
        writable = False
        try:
            path.mkdir(parents=True, exist_ok=True)
            # Yazma izni testi
            test_file = path / ".write_test"
            test_file.touch()
            test_file.unlink()
            writable = True
        except Exception:
            writable = False
        
        results[name] = "âœ…" if writable else "âŒ"
    
    return results


def check_exchange_connection() -> dict:
    """Borsa baÄŸlantÄ±sÄ±nÄ± test et (sadece ping)."""
    try:
        from config.settings import get_settings, get_trading_params
        from execution.exchange_client import ExchangeClient
        
        settings = get_settings()
        params = get_trading_params()
        
        # Paper trading modunda mÄ±?
        if params.execution.mode.value == "paper":
            return {"status": "âœ…", "mode": "PAPER TRADING"}
        
        # Live mode - baÄŸlantÄ± testi
        client = ExchangeClient()
        balance = client.get_balance()
        
        if "error" in balance:
            return {"status": "âŒ", "error": balance["error"]}
        
        return {"status": "âœ…", "mode": "LIVE TRADING"}
    
    except Exception as e:
        return {"status": "âŒ", "error": str(e)}


def check_chromadb() -> dict:
    """ChromaDB baÄŸlantÄ±sÄ±nÄ± test et."""
    try:
        from data.vector_store import AgentMemoryStore
        
        store = AgentMemoryStore()
        collection = store.collection
        
        if collection is None:
            return {"status": "âŒ", "error": "Collection oluÅŸturulamadÄ±"}
        
        return {"status": "âœ…", "collection": collection.name}
    
    except Exception as e:
        return {"status": "âŒ", "error": str(e)}


def main():
    """Ana health check fonksiyonu."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    
    console = Console()
    
    console.print(
        Panel(
            "[bold cyan]LLM Trading System - Health Check[/bold cyan]\n"
            f"Path: {PROJECT_ROOT}",
            title="[bold]Sistem SaÄŸlÄ±k KontrolÃ¼[/bold]",
            border_style="cyan",
        )
    )
    
    all_passed = True
    
    # 1. Python Version
    console.print("\n[bold]1. Python Version[/bold]")
    py_result = check_python_version()
    console.print(f"   {py_result['status']} Python {py_result['version']}")
    if py_result['status'] == "âŒ":
        all_passed = False
    
    # 2. Dependencies
    console.print("\n[bold]2. Kritik KÃ¼tÃ¼phaneler[/bold]")
    dep_results = check_dependencies()
    for pkg, status in dep_results.items():
        console.print(f"   {pkg:15s}: {status}")
        if "âŒ" in status:
            all_passed = False
    
    # 3. Environment
    console.print("\n[bold]3. Environment (.env)[/bold]")
    env_result = check_env_file()
    console.print(f"   Status: {env_result['status']}")
    for detail in env_result.get('details', []):
        console.print(f"   {detail}")
    
    # 4. API Keys
    console.print("\n[bold]4. API AnahtarlarÄ±[/bold]")
    api_result = check_api_keys()
    if "error" in api_result:
        console.print(f"   âŒ Error: {api_result['error']}")
        all_passed = False
    else:
        for provider, status in api_result.items():
            console.print(f"   {provider:15s}: {status}")
            if status == "âŒ":
                all_passed = False
    
    # 5. Directories
    console.print("\n[bold]5. KlasÃ¶rler ve Ä°zinler[/bold]")
    dir_result = check_directories()
    for name, status in dir_result.items():
        console.print(f"   {name:15s}: {status}")
        if status == "âŒ":
            all_passed = False
    
    # 6. ChromaDB
    console.print("\n[bold]6. ChromaDB (RAG Memory)[/bold]")
    chroma_result = check_chromadb()
    console.print(f"   Status: {chroma_result['status']}")
    if "collection" in chroma_result:
        console.print(f"   Collection: {chroma_result['collection']}")
    if "error" in chroma_result:
        console.print(f"   Error: {chroma_result['error']}")
        all_passed = False
    
    # 7. Exchange Connection
    console.print("\n[bold]7. Borsa BaÄŸlantÄ±sÄ±[/bold]")
    exchange_result = check_exchange_connection()
    console.print(f"   Status: {exchange_result['status']}")
    if "mode" in exchange_result:
        console.print(f"   Mode: {exchange_result['mode']}")
    if "error" in exchange_result:
        console.print(f"   Error: {exchange_result['error']}")
        all_passed = False
    
    # Final Summary
    console.print("\n" + "=" * 60)
    if all_passed:
        console.print("[bold green]âœ… TÃœM KONTROLLER BAÅARILI - Sistem hazÄ±r![/bold green]")
        sys.exit(0)
    else:
        console.print(
            "[bold red]âŒ BAZI KONTROLLER BAÅARISIZ - LÃ¼tfen yukarÄ±daki hatalarÄ± dÃ¼zeltin.[/bold red]"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

