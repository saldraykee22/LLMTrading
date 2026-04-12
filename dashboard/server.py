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
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Trading Dashboard API", version="1.0.0")

trade_total = Counter(
    "trade_total", "Total number of trades", ["symbol", "action", "result"]
)

trade_pnl = Histogram(
    "trade_pnl",
    "Trade profit and loss distribution",
    ["symbol"],
    buckets=[-500, -200, -100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100, 200, 500],
)

api_calls_total = Counter("api_calls_total", "Total API calls by type", ["type"])

portfolio_equity = Gauge("portfolio_equity", "Current portfolio equity in USD")

drawdown_pct = Gauge("drawdown_pct", "Current drawdown percentage")

llm_api_cost = Counter("llm_api_cost_total", "Total LLM API cost in USD", ["provider"])

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
            portfolio_equity.set(data.get("equity", 0))
            drawdown_pct.set(data.get("drawdown", 0) * 100)
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
            for trade in trades[-limit:]:
                symbol = trade.get("symbol", "UNKNOWN")
                action = trade.get("action", "unknown")
                pnl = trade.get("pnl", 0)
                result = "win" if pnl > 0 else "loss"
                trade_total.labels(symbol=symbol, action=action, result=result).inc()
                trade_pnl.labels(symbol=symbol).observe(pnl)
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


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/rl_status")
async def get_rl_status():
    api_calls_total.labels(type="rl_status").inc()
    model_paths = list(DATA_DIR.glob("rl_model*")) + list(DATA_DIR.glob("models/rl*"))
    model_loaded = any(p.exists() for p in model_paths)
    return {
        "model_loaded": model_loaded,
        "confidence": 0.0,
        "model_version": "v1.0.0" if model_loaded else "none",
        "last_trained": None,
        "total_episodes": 0,
    }


@app.get("/api/drift_heatmap")
async def get_drift_heatmap(days: int = 30):
    api_calls_total.labels(type="drift_heatmap").inc()
    try:
        from evaluation.drift_monitor import DriftMonitor

        monitor = DriftMonitor()
        heatmap = monitor.get_heatmap_data(days=days)
        return {"heatmap": heatmap, "days": days}
    except Exception as e:
        return {"heatmap": {}, "days": days, "error": str(e)}


@app.get("/api/rag_queries")
async def get_rag_queries(limit: int = 20):
    api_calls_total.labels(type="rag_queries").inc()
    try:
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection:
            results = store.collection.get(limit=limit, include=["metadatas"])
            queries = []
            if results and results.get("metadatas"):
                for meta in results["metadatas"]:
                    queries.append(
                        {
                            "symbol": meta.get("symbol", "UNKNOWN"),
                            "action": meta.get("action", "unknown"),
                            "accuracy": meta.get("accuracy", 0.0),
                            "timestamp": meta.get("timestamp", ""),
                            "market_regime": meta.get("market_regime", "unknown"),
                            "tags": meta.get("tags", "").split(",")
                            if meta.get("tags")
                            else [],
                        }
                    )
            return {"queries": queries}
        return {"queries": []}
    except Exception as e:
        return {"queries": [], "error": str(e)}


@app.get("/api/monte_carlo")
async def get_monte_carlo(n_simulations: int = 1000, days: int = 30):
    api_calls_total.labels(type="monte_carlo").inc()
    import math
    import random

    initial_equity = 10000.0
    daily_returns = []
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
            initial_equity = data.get("equity", 10000.0)
            trades = data.get("closed_trades", [])
            if trades:
                daily_returns = [
                    t.get("pnl", 0) / initial_equity for t in trades if t.get("pnl")
                ]
        except (json.JSONDecodeError, OSError):
            pass
    if len(daily_returns) >= 10:
        mean_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / max(
            len(daily_returns) - 1, 1
        )
        std_ret = math.sqrt(variance) if variance > 0 else 0.01
    else:
        mean_ret = 0.001
        std_ret = 0.02
    final_values = []
    for _ in range(n_simulations):
        equity = initial_equity
        for _ in range(days):
            equity *= 1 + random.gauss(mean_ret, std_ret)
        final_values.append(equity)
    final_values.sort()
    percentiles = {
        "p5": round(final_values[int(n_simulations * 0.05)], 2),
        "p25": round(final_values[int(n_simulations * 0.25)], 2),
        "p50": round(final_values[int(n_simulations * 0.50)], 2),
        "p75": round(final_values[int(n_simulations * 0.75)], 2),
        "p95": round(final_values[int(n_simulations * 0.95)], 2),
    }
    min_val = min(final_values)
    max_val = max(final_values)
    bin_count = 30
    bin_width = (max_val - min_val) / bin_count if max_val > min_val else 1
    histogram = []
    for i in range(bin_count):
        bin_start = min_val + i * bin_width
        count = sum(1 for v in final_values if bin_start <= v < bin_start + bin_width)
        histogram.append({"bin": round(bin_start, 2), "count": count})
    return {
        "simulations": n_simulations,
        "days": days,
        "initial_equity": round(initial_equity, 2),
        "percentiles": percentiles,
        "histogram": histogram,
        "probability_profit": round(
            sum(1 for v in final_values if v > initial_equity) / n_simulations, 4
        ),
        "mean_final": round(sum(final_values) / n_simulations, 2),
        "min_final": round(min_val, 2),
        "max_final": round(max_val, 2),
    }


@app.get("/api/drift_summary")
async def get_drift_summary():
    api_calls_total.labels(type="drift_summary").inc()
    try:
        from evaluation.drift_monitor import DriftMonitor

        monitor = DriftMonitor()
        return monitor.get_drift_summary()
    except Exception as e:
        return {
            "error": str(e),
            "total_records": 0,
            "symbols_tracked": [],
            "agents_tracked": [],
            "per_symbol": {},
            "per_agent": {},
            "worsening_drifts": [],
            "significant_drifts": [],
        }


@app.get("/api/retrospective")
async def get_retrospective(limit: int = 10):
    api_calls_total.labels(type="retrospective").inc()
    try:
        from data.vector_store import AgentMemoryStore

        store = AgentMemoryStore()
        if store.collection:
            results = store.collection.query(
                query_texts=["lesson learned losing trade"],
                n_results=limit,
            )
            retrospectives = []
            if results and results.get("metadatas"):
                for i, meta in enumerate(results["metadatas"][0]):
                    doc = results["documents"][0][i]
                    retrospectives.append(
                        {
                            "symbol": meta.get("symbol", "UNKNOWN"),
                            "root_cause": meta.get("root_cause_category", "unknown"),
                            "lesson": doc[:300],
                            "accuracy": meta.get("accuracy", 0.0),
                            "market_regime": meta.get("market_regime", "unknown"),
                            "timestamp": meta.get("timestamp", ""),
                            "entry_quality": meta.get("entry_quality", "unknown"),
                            "exit_quality": meta.get("exit_quality", "unknown"),
                        }
                    )
            return {"retrospectives": retrospectives}
        return {"retrospectives": []}
    except Exception as e:
        return {"retrospectives": [], "error": str(e)}


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
