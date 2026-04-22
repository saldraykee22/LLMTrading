"""
LLM Trading System - Health Check Script
==========================================
Sistem sağlık kontrolü - Başlangıç validasyonu
Kullanım: python scripts/health_check.py
"""

import sys
from pathlib import Path

# Proje kökünü path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_python_version() -> dict:
    """Python versiyonunu kontrol et."""
    return {
        "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "status": "OK" if sys.version_info >= (3, 10) else "FAIL",
    }


def check_dependencies() -> dict:
    """Kritik kütüphaneleri kontrol et."""
    results = {}
    
    critical_packages = {
        "ccxt": "Borsa bağlantısı",
        "langchain": "LLM framework",
        "chromadb": "Vektör veritabanı",
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
    """.env dosyasını kontrol et."""
    env_file = PROJECT_ROOT / ".env"
    
    if not env_file.exists():
        return {"status": "❌", "message": ".env dosyası bulunamadı"}
    
    # API anahtarlarının varlığını kontrol et
    content = env_file.read_text(encoding="utf-8")
    
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
    """API anahtarlarını kontrol et (değerleri göstermeden)."""
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
            results[provider] = "✅" if has_key else "❌"
        
        return results
    except Exception as e:
        return {"error": str(e)}


def check_directories() -> dict:
    """Gerekli klasörlerin varlığını kontrol et."""
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
        
        results[name] = "✅" if writable else "❌"
    
    return results


def check_exchange_connection() -> dict:
    """Borsa bağlantısını test et (sadece ping)."""
    try:
        from config.settings import get_settings, get_trading_params
        from execution.exchange_client import ExchangeClient
        
        settings = get_settings()
        params = get_trading_params()
        
        # Paper trading modunda mı?
        if params.execution.mode.value == "paper":
            return {"status": "✅", "mode": "PAPER TRADING"}
        
        # Live mode - bağlantı testi
        client = ExchangeClient()
        balance = client.get_balance()
        
        if "error" in balance:
            return {"status": "❌", "error": balance["error"]}
        
        return {"status": "✅", "mode": "LIVE TRADING"}
    
    except Exception as e:
        return {"status": "❌", "error": str(e)}


def check_chromadb() -> dict:
    """ChromaDB bağlantısını test et."""
    try:
        from data.vector_store import AgentMemoryStore
        
        store = AgentMemoryStore()
        collection = store.collection
        
        if collection is None:
            return {"status": "❌", "error": "Collection oluşturulamadı"}
        
        return {"status": "✅", "collection": collection.name}
    
    except Exception as e:
        return {"status": "❌", "error": str(e)}


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
            title="[bold]Sistem Sağlık Kontrolü[/bold]",
            border_style="cyan",
        )
    )
    
    all_passed = True
    
    # 1. Python Version
    console.print("\n[bold]1. Python Version[/bold]")
    py_result = check_python_version()
    console.print(f"   {py_result['status']} Python {py_result['version']}")
    if py_result['status'] == "❌":
        all_passed = False
    
    # 2. Dependencies
    console.print("\n[bold]2. Kritik Kütüphaneler[/bold]")
    dep_results = check_dependencies()
    for pkg, status in dep_results.items():
        console.print(f"   {pkg:15s}: {status}")
        if "❌" in status or "MISSING" in status:
            all_passed = False
    
    # 3. Environment
    console.print("\n[bold]3. Environment (.env)[/bold]")
    env_result = check_env_file()
    console.print(f"   Status: {env_result['status']}")
    for detail in env_result.get('details', []):
        console.print(f"   {detail}")
    
    # 4. API Keys
    console.print("\n[bold]4. API Anahtarları[/bold]")
    api_result = check_api_keys()
    if "error" in api_result:
        console.print(f"   ❌ Error: {api_result['error']}")
        all_passed = False
    else:
        for provider, status in api_result.items():
            console.print(f"   {provider:15s}: {status}")
            if status == "❌":
                all_passed = False
    
    # 5. Directories
    console.print("\n[bold]5. Klasörler ve İzinler[/bold]")
    dir_result = check_directories()
    for name, status in dir_result.items():
        console.print(f"   {name:15s}: {status}")
        if status == "❌":
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
    console.print("\n[bold]7. Borsa Bağlantısı[/bold]")
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
        console.print("[bold green]✅ TÜM KONTROLLER BAŞARILI - Sistem hazır![/bold green]")
        sys.exit(0)
    else:
        console.print(
            "[bold red]❌ BAZI KONTROLLER BAŞARISIZ - Lütfen yukarıdaki hataları düzeltin.[/bold red]"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
