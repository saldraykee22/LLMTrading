"""
LLM Trading System — Dashboard API Server
===========================================
FastAPI tabanlı backend server:
- Portfolio durumu, pozisyonlar, işlemler API endpoint'leri
- Statik dashboard dosyalarını serve eder
- SSE (Server-Sent Events) ile ajan aktivite logları
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Trading Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


from config.settings import get_settings


@app.middleware("http")
async def check_api_key(request: Request, call_next):
    settings = get_settings()
    api_key = settings.dashboard_api_key
    if api_key:
        client_key = request.headers.get("X-API-Key")
        if client_key != api_key:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.middleware("http")
async def block_sensitive_files(request: Request, call_next):
    """Python kaynak kodları, .env ve config dosyalarına erişimi engeller."""
    if request.url.path.endswith((".py", ".pyc", ".env", ".yaml")):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await call_next(request)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
PORTFOLIO_FILE = DATA_DIR / "portfolio_state.json"
EXPORTS_DIR = DATA_DIR / "exports"


@app.get("/")
async def index():
    """Dashboard ana sayfası."""
    return FileResponse(DASHBOARD_DIR / "index.html")


@app.get("/api/portfolio")
async def get_portfolio():
    """Portföy durumu."""
    fallback = {
        "cash": 10000.0,
        "equity": 10000.0,
        "total_pnl": 0.0,
        "daily_pnl": 0.0,
        "drawdown": 0.0,
        "max_equity": 10000.0,
        "open_positions": 0,
        "positions": [],
        "benchmark_symbol": "BTC/USDT",
        "benchmark_return": 0.0,
        "alpha": 0.0,
    }
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            data.setdefault("benchmark_symbol", "BTC/USDT")
            data.setdefault("benchmark_return", 0.0)
            data.setdefault("alpha", 0.0)
            return data
        except (json.JSONDecodeError, OSError):
            return fallback
    return fallback


@app.get("/api/benchmark")
async def get_benchmark():
    """Benchmark karşılaştırma verisi."""
    fallback = {
        "benchmark_symbol": "BTC/USDT",
        "benchmark_return": 0.0,
        "alpha": 0.0,
    }
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            return {
                "benchmark_symbol": data.get("benchmark_symbol", "BTC/USDT"),
                "benchmark_return": data.get("benchmark_return", 0.0),
                "alpha": data.get("alpha", 0.0),
            }
        except (json.JSONDecodeError, OSError):
            return fallback
    return fallback


@app.get("/api/positions")
async def get_positions():
    """Açık pozisyonlar."""
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            return {"positions": data.get("positions", [])}
        except (json.JSONDecodeError, OSError):
            return {"positions": []}
    return {"positions": []}


@app.get("/api/trades")
async def get_trades(limit: int = 20):
    """Son işlemler."""
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            trades = data.get("closed_trades", [])
            return {"trades": trades[-limit:]}
        except (json.JSONDecodeError, OSError):
            return {"trades": []}
    return {"trades": []}


@app.get("/api/analysis")
async def get_latest_analysis():
    """En son analiz sonucu."""
    if EXPORTS_DIR.exists():
        files = sorted(
            EXPORTS_DIR.glob("analysis_*.json"), key=lambda f: f.stat().st_mtime
        )
        if files:
            latest = files[-1]
            try:
                return json.loads(latest.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {"status": "no_analysis"}
    return {"status": "no_analysis"}


@app.get("/api/status")
async def get_status():
    """Sistem durumu."""
    portfolio_exists = PORTFOLIO_FILE.exists()
    analysis_count = (
        len(list(EXPORTS_DIR.glob("analysis_*.json"))) if EXPORTS_DIR.exists() else 0
    )

    status = {
        "portfolio_loaded": portfolio_exists,
        "total_analyses": analysis_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if portfolio_exists:
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            status["equity"] = data.get("equity", 0)
            status["positions"] = data.get("open_positions", 0)
            status["total_pnl"] = data.get("total_pnl", 0)
        except (json.JSONDecodeError, OSError):
            status["error"] = "Failed to read portfolio data"

    return status


@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/portfolio_allocation")
async def get_portfolio_allocation():
    """En son portföy dağılımı (run_portfolio.py çıktısı)."""
    if EXPORTS_DIR.exists():
        files = sorted(
            EXPORTS_DIR.glob("portfolio_*.json"), key=lambda f: f.stat().st_mtime
        )
        if files:
            latest = files[-1]
            try:
                return json.loads(latest.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {"status": "no_allocation"}
    return {"status": "no_allocation"}


# Statik dosyalar (CSS, JS)
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Server'ı çalıştırır."""
    import uvicorn

    logger.info("Dashboard API: http://%s:%d", host, port)
    logger.info("Dashboard UI: http://%s:%d/", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
