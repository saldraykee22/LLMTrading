"""
LLM Trading System — Pydantic Settings Configuration
=====================================================
Tüm yapılandırma merkezi olarak buradan yönetilir.
.env dosyasından API anahtarları, trading_params.yaml'dan strateji parametreleri yüklenir.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Paths ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
PROMPTS_DIR = PROJECT_ROOT / "models" / "prompts"


# ── Enums ──────────────────────────────────────────────────
class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class LLMProvider(str, Enum):
    OPENROUTER = "openrouter"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"


class RegimeState(str, Enum):
    LOW_VOL = "low_vol"
    NORMAL = "normal"
    HIGH_VOL = "high_vol"
    CRISIS = "crisis"


# ── Environment Settings (.env) ────────────────────────────
class Settings(BaseSettings):
    """Ana yapılandırma — .env dosyasından yüklenir."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "deepseek/deepseek-chat-v3-0324"
    openrouter_reasoning_model: str = "deepseek/deepseek-reasoner"

    # DeepSeek Direct
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "llama3:8b"

    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True

    # News APIs
    finnhub_api_key: str = ""
    cryptopanic_api_key: str = ""

    # System
    log_level: str = "INFO"
    trading_mode: TradingMode = TradingMode.PAPER


# ── YAML Trading Parameters ───────────────────────────────
class RiskParams(BaseModel):
    max_position_pct: float = 0.05
    max_portfolio_risk_pct: float = 0.20
    max_drawdown_pct: float = 0.15
    max_daily_loss_pct: float = 0.03
    cvar_confidence: float = 0.95
    max_open_positions: int = 5
    max_correlated_positions: int = 3


class RegimeParams(BaseModel):
    vix_sma_period: int = 25
    vix_threshold_multiplier: float = 1.10
    crypto_fear_greed_threshold: int = 20
    halt_on_high_vol: bool = True


class StopLossParams(BaseModel):
    atr_period: int = 14
    atr_multiplier: float = 2.5
    trailing_enabled: bool = True
    hard_stop_pct: float = 0.08


class ExecutionParams(BaseModel):
    mode: TradingMode = TradingMode.PAPER
    exchange: str = "binance"
    default_order_type: str = "limit"
    slippage_pct: float = 0.001
    commission_pct: float = 0.001
    rate_limit_ms: int = 1200
    retry_count: int = 3
    retry_delay_ms: int = 2000


class SentimentParams(BaseModel):
    provider: LLMProvider = LLMProvider.OPENROUTER
    model: str = "deepseek/deepseek-chat-v3-0324"
    reasoning_model: str = "deepseek/deepseek-reasoner"
    score_range: list[float] = [-1.0, 1.0]
    bullish_threshold: float = 0.3
    bearish_threshold: float = -0.3
    min_confidence: float = 0.6


class AgentParams(BaseModel):
    max_debate_rounds: int = 3
    max_retry_iterations: int = 3
    coordinator_model: str = "deepseek/deepseek-chat-v3-0324"
    analyst_model: str = "deepseek/deepseek-chat-v3-0324"
    risk_model: str = "deepseek/deepseek-chat-v3-0324"
    trader_model: str = "deepseek/deepseek-chat-v3-0324"


class BacktestParams(BaseModel):
    train_pct: float = 0.70
    validation_pct: float = 0.15
    test_pct: float = 0.15
    initial_cash: float = 10000
    benchmark: str = "BTC/USDT"


class DataParams(BaseModel):
    crypto_exchange: str = "binance"
    default_timeframe: str = "1h"
    history_days: int = 365
    news_lookback_hours: int = 24
    cache_enabled: bool = True
    cache_ttl_minutes: int = 15


class TradingParams(BaseModel):
    """trading_params.yaml'dan yüklenen strateji parametreleri."""

    risk: RiskParams = RiskParams()
    regime: RegimeParams = RegimeParams()
    stop_loss: StopLossParams = StopLossParams()
    execution: ExecutionParams = ExecutionParams()
    sentiment: SentimentParams = SentimentParams()
    agents: AgentParams = AgentParams()
    backtest: BacktestParams = BacktestParams()
    data: DataParams = DataParams()


def load_trading_params(path: Path | None = None) -> TradingParams:
    """YAML dosyasından strateji parametrelerini yükler."""
    yaml_path = path or CONFIG_DIR / "trading_params.yaml"
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}
        return TradingParams(**raw)
    return TradingParams()


# ── Singleton Helpers ──────────────────────────────────────
_settings: Settings | None = None
_trading_params: TradingParams | None = None


def get_settings() -> Settings:
    """Tekil Settings nesnesi döndürür."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_trading_params() -> TradingParams:
    """Tekil TradingParams nesnesi döndürür."""
    global _trading_params
    if _trading_params is None:
        _trading_params = load_trading_params()
    return _trading_params
