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
    binance_testnet: bool = False  # Mainnet by default (unless sandbox keys are used)

    # News APIs
    finnhub_api_key: str = ""
    cryptopanic_api_key: str = ""

    # System
    log_level: str = "INFO"
    trading_mode: TradingMode = TradingMode.PAPER
    confirm_live_trade: bool = True  # Safety lock for LIVE trading

    # Dashboard
    dashboard_api_key: str | None = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._validate_security()
    
    def _validate_security(self) -> None:
        """Güvenlik doğrulaması - API anahtarları ve dosya izinleri."""
        import sys
        import stat
        
        # .env dosya izinlerini kontrol et (Unix sistemler)
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists() and sys.platform != "win32":
            try:
                file_stat = env_file.stat()
                # Eğer başkaları tarafından okunabiliyorsa uyar
                if file_stat.st_mode & stat.S_IROTH:
                    logger.warning(
                        "⚠️  GÜVENLİK UYARISI: .env dosyası başkaları tarafından okunabilir! "
                        "chmod 600 .env komutuyla düzeltin."
                    )
            except Exception as e:
                logger.debug("File permission check failed: %s", e)
        
        # API anahtarları için uyarı (production'ta environment variable kullanılmalı)
        if self.binance_api_key and self.trading_mode == TradingMode.LIVE:
            logger.warning(
                "⚠️  CANLI İŞLEM MODU: Binance API anahtarı .env dosyasında saklanıyor. "
                "Production ortamında güvenli bir vault (AWS Secrets Manager, Azure Key Vault) kullanın."
            )
    
    @property
    def masked_openrouter_key(self) -> str:
        return mask_api_key(self.openrouter_api_key)

    @property
    def masked_binance_key(self) -> str:
        return mask_api_key(self.binance_api_key)


# ── YAML Trading Parameters ───────────────────────────────
class CvarParams(BaseModel):
    max_weight: float = 0.40


class RiskParams(BaseModel):
    max_position_pct: float = 0.05
    max_portfolio_risk_pct: float = 0.20
    max_drawdown_pct: float = 0.15
    max_daily_loss_pct: float = 0.03
    cvar_confidence: float = 0.95
    max_open_positions: int = 5
    max_correlated_positions: int = 3
    max_correlation_threshold: float = 0.70
    max_consecutive_losses: int = 5
    max_consecutive_llm_errors: int = 10
    cvar: CvarParams = CvarParams()


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
    model: str = "openai/gpt-oss-120b:free"
    reasoning_model: str = "openai/gpt-oss-120b:free"
    score_range: list[float] = [-1.0, 1.0]
    bullish_threshold: float = 0.3
    bearish_threshold: float = -0.3
    min_confidence: float = 0.6


class AgentParams(BaseModel):
    max_debate_rounds: int = 3
    max_retry_iterations: int = 3
    coordinator_model: str = "openai/gpt-oss-120b:free"
    analyst_model: str = "openai/gpt-oss-120b:free"
    risk_model: str = "openai/gpt-oss-120b:free"
    trader_model: str = "openai/gpt-oss-120b:free"
    ensemble_enabled: bool = False
    ensemble_models: list[str] = Field(
        default_factory=lambda: ["deepseek/deepseek-chat-v3-0324", "ollama/llama3:8b"]
    )
    ensemble_min_consensus: float = 0.5


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


class LimitsParams(BaseModel):
    max_news_items: int = 20
    debate_truncate_chars: int = 300
    debate_rebuttal_truncate_chars: int = 1500
    moderator_truncate_chars: int = 2000
    min_risk_reward: float = 1.5
    vix_crisis_threshold: float = 40
    vix_low_vol_multiplier: float = 0.8
    backtest_lookback_window: int = 30
    monte_carlo_simulations: int = 5000
    sentiment_cache_minutes: int = 30
    news_rate_limit_delay: float = 0.5
    max_tokens_sentiment: int = 300
    max_tokens_research: int = 500
    max_tokens_debate: int = 400
    max_tokens_moderator: int = 400
    max_tokens_risk: int = 400
    max_tokens_trader: int = 250
    max_tokens_coordinator: int = 200


class ScannerParams(BaseModel):
    enabled: bool = True
    min_volume_24h_usdt: float = 1000000
    min_price_change_24h_pct: float = 2.0
    max_initial_candidates: int = 30
    max_scout_recommendations: int = 5
    scout_model: str = "deepseek/deepseek-chat-v3-0324"
    quote_asset: str = "USDT"


class WatchdogParams(BaseModel):
    enabled: bool = False
    check_interval_seconds: int = 30
    crash_1m_pct: float = 0.03
    crash_5m_pct: float = 0.05
    alert_5m_pct: float = 0.02


class LLMParams(BaseModel):
    default_model: str = "deepseek/deepseek-chat-v3-0324"
    reasoning_model: str = "deepseek/deepseek-reasoner"
    fallback_providers: list[str] = ["openrouter", "deepseek", "ollama"]


class TradingParams(BaseModel):
    """trading_params.yaml'dan yüklenen strateji parametreleri."""

    risk: RiskParams = RiskParams()
    llm: LLMParams = LLMParams()
    regime: RegimeParams = RegimeParams()
    stop_loss: StopLossParams = StopLossParams()
    execution: ExecutionParams = ExecutionParams()
    sentiment: SentimentParams = SentimentParams()
    agents: AgentParams = AgentParams()
    backtest: BacktestParams = BacktestParams()
    data: DataParams = DataParams()
    limits: LimitsParams = LimitsParams()
    watchdog: WatchdogParams = WatchdogParams()
    scanner: ScannerParams = ScannerParams()


def load_trading_params(path: Path | None = None) -> TradingParams:
    """YAML dosyasından strateji parametrelerini yükler."""
    yaml_path = path or CONFIG_DIR / "trading_params.yaml"
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}
        return TradingParams(**raw)
    return TradingParams()


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:6] + "****" + key[-4:]


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
