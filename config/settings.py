"""
LLM Trading System — Pydantic Settings Configuration
=====================================================
Tüm yapılandırma merkezi olarak buradan yönetilir.
.env dosyasından API anahtarları, trading_params.yaml'dan strateji parametreleri yüklenir.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Logger ──────────────────────────────────────────────────
logger = logging.getLogger(__name__)


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
    binance_testnet: bool = True  # Safety: testnet by default
    
    # Multi-Account Support
    binance_accounts_json: str = ""  # JSON array of account objects

    # Telegram Notifications
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # News APIs
    finnhub_api_key: str = ""

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
    
    @property
    def binance_accounts(self) -> list[dict[str, str]]:
        """
        Parse binance accounts from JSON or fallback to legacy single account.
        
        Returns:
            List of account dicts: [{"name": "Main", "api_key": "...", "api_secret": "..."}, ...]
        """
        import json
        
        if self.binance_accounts_json:
            try:
                accounts = json.loads(self.binance_accounts_json)
                if isinstance(accounts, list) and accounts:
                    logger.info(f"Loaded {len(accounts)} accounts from BINANCE_ACCOUNTS_JSON")
                    return accounts
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse BINANCE_ACCOUNTS_JSON: {e}")
        
        # Fallback to legacy single account (backwards compatibility)
        if self.binance_api_key and self.binance_api_secret:
            logger.info("Using legacy single account (Main) from BINANCE_API_KEY/SECRET")
            return [{"name": "Main", "api_key": self.binance_api_key, "api_secret": self.binance_api_secret}]
        
        logger.warning("No Binance accounts configured")
        return []


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
    # Rejim bazlı pozisyon limitleri
    bull_max_exposure: float = 1.0
    neutral_max_exposure: float = 0.60
    bear_max_exposure: float = 0.20
    crash_max_exposure: float = 0.0


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
    dca_enabled: bool = True
    default_execution_size_pct: float = 1.0
    min_dca_tranche_pct: float = 0.25
    max_dca_tranches: int = 4
    dca_price_improvement_pct: float = 0.02


class SentimentParams(BaseModel):
    provider: LLMProvider = LLMProvider.OPENROUTER
    model: str = "qwen/qwen3.5-flash-02-23"
    reasoning_model: str = "qwen/qwen3.5-flash-02-23"
    score_range: list[float] = [-1.0, 1.0]
    bullish_threshold: float = 0.3
    bearish_threshold: float = -0.3
    min_confidence: float = 0.6


class AgentParams(BaseModel):
    max_debate_rounds: int = 3
    max_retry_iterations: int = 3
    coordinator_model: str = "qwen/qwen3.5-flash-02-23"
    analyst_model: str = "qwen/qwen3.5-flash-02-23"
    risk_model: str = "qwen/qwen3.5-flash-02-23"
    trader_model: str = "qwen/qwen3.5-flash-02-23"
    ensemble_enabled: bool = True
    ensemble_models: list[str] = Field(
        default_factory=lambda: ["deepseek/deepseek-chat-v3-0324", "ollama/llama3:8b", "openrouter/openai/gpt-4o-mini"]
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
    max_tokens_sentiment: int = 2000
    max_tokens_research: int = 8000
    max_tokens_debate: int = 8000
    max_tokens_moderator: int = 4000
    max_tokens_risk: int = 4000
    max_tokens_trader: int = 2000
    max_tokens_coordinator: int = 2000


class MomentumThreshold(BaseModel):
    """Tek bir momentum skor basamağı."""
    min_pct: float
    max_pct: float
    score: float


class ScoringWeights(BaseModel):
    """Kalite skoru ağırlıkları."""
    volume_weight: float = 0.40
    momentum_1h_weight: float = 0.30
    momentum_24h_weight: float = 0.30


class AtrNormalization(BaseModel):
    """ATR bazlı normalizasyon ayarları."""
    enabled: bool = True
    lookback_days: int = 14
    use_normalized_score: bool = True


class SilentAccumulation(BaseModel):
    """Sessiz birikim (divergence) tespiti."""
    enabled: bool = True
    volume_threshold: float = 2.0
    price_threshold: float = 3.0
    bonus_score: float = 15.0
    min_quality_score: float = 40.0


class ScannerParams(BaseModel):
    enabled: bool = True
    min_volume_24h_usdt: float = 1000000
    min_price_change_24h_pct: float = 2.0
    max_price_change_24h_pct: float = 8.0
    max_initial_candidates: int = 30
    max_scout_recommendations: int = 5
    scout_model: str = "qwen/qwen3.5-flash-02-23"
    quote_asset: str = "USDT"
    dynamic_scanner_enabled: bool = True
    scan_interval_hours: int = 6
    scan_interval_hours_high_cash: int = 3
    min_cash_ratio_for_frequent_scan: float = 0.50
    
    # Momentum skorlama
    momentum_24h_thresholds: list[MomentumThreshold] = Field(
        default_factory=lambda: [
            MomentumThreshold(min_pct=2.0, max_pct=5.0, score=30),
            MomentumThreshold(min_pct=5.0, max_pct=8.0, score=15),
            MomentumThreshold(min_pct=0.0, max_pct=2.0, score=5),
            MomentumThreshold(min_pct=8.0, max_pct=100.0, score=0),
        ]
    )
    momentum_1h_thresholds: list[MomentumThreshold] = Field(
        default_factory=lambda: [
            MomentumThreshold(min_pct=0.0, max_pct=3.0, score=30),
            MomentumThreshold(min_pct=3.0, max_pct=6.0, score=20),
            MomentumThreshold(min_pct=-5.0, max_pct=0.0, score=10),
            MomentumThreshold(min_pct=6.0, max_pct=100.0, score=5),
        ]
    )
    
    # Hacim skorlama
    volume_score_multiplier: float = 8.0
    max_volume_score_cap: float = 5.0
    
    # ATR normalizasyonu
    atr_normalization: AtrNormalization = Field(default_factory=AtrNormalization)
    
    # Sessiz birikim
    silent_accumulation: SilentAccumulation = Field(default_factory=SilentAccumulation)
    
    # Ağırlıklar
    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)
    
    # Filtreler
    min_quality_score_threshold: float = 45.0
    prefer_early_momentum: bool = True
    avoid_overextended: bool = True


class WatchdogParams(BaseModel):
    enabled: bool = False
    check_interval_seconds: int = 30
    crash_1m_pct: float = 0.03
    crash_5m_pct: float = 0.05
    alert_5m_pct: float = 0.02
    emergency_close_all: bool = True


class SystemParams(BaseModel):
    cleanup_cycle_interval: int = 96
    max_workers: int = 5
    rate_limit_consecutive_threshold: int = 3
    llm_timeout_seconds: int = 60
    reconnect_max_attempts: int = 5
    circuit_breaker_state_ttl: int = 3600
    reset_counters_on_startup: bool = True
    max_symbol_length: int = 50
    stop_file_path: str = "data/STOP"
    # Fallback configuration
    max_consecutive_fallbacks: int = 5
    fallback_audit_enabled: bool = True
    fallback_audit_retention_days: int = 7


class LLMParams(BaseModel):
    default_model: str = "deepseek/deepseek-chat-v3-0324"
    reasoning_model: str = "deepseek/deepseek-reasoner"
    fallback_providers: list[str] = ["openrouter", "deepseek", "ollama"]
    # Fallback values (YAML'den yüklenir)
    fallbacks: dict[str, dict[str, Any]] = Field(default_factory=dict)


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
    system: SystemParams = SystemParams()


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
import threading

_settings: Settings | None = None
_trading_params: TradingParams | None = None
_settings_lock = threading.Lock()
_params_lock = threading.Lock()


def get_settings() -> Settings:
    """Tekil Settings nesnesi döndürür (thread-safe)."""
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                _settings = Settings()
    return _settings


def get_trading_params() -> TradingParams:
    """Tekil TradingParams nesnesi döndürür (thread-safe)."""
    global _trading_params
    if _trading_params is None:
        with _params_lock:
            if _trading_params is None:
                _trading_params = load_trading_params()
    return _trading_params


def get_fallback_config(agent_name: str) -> dict[str, Any] | None:
    """
    Ajan bazlı fallback config döndürür.
    
    Args:
        agent_name: "sentiment", "research", "debate_bull", "debate_bear", 
                    "debate_moderator", "risk_manager", "trader"
    
    Returns:
        Fallback config dict veya None
    """
    params = get_trading_params()
    fallbacks = params.llm.fallbacks
    
    # Agent name mapping
    agent_map = {
        "sentiment": "sentiment",
        "research": "research",
        "research_analyst": "research",
        "bull": "debate_bull",
        "bear": "debate_bear",
        "moderator": "debate_moderator",
        "debate_moderator": "debate_moderator",
        "risk": "risk_manager",
        "risk_manager": "risk_manager",
        "trader": "trader",
    }
    
    config_key = agent_map.get(agent_name.lower(), agent_name.lower())
    fallback_config = fallbacks.get(config_key)
    
    if fallback_config and fallback_config.get("enabled", True):
        # "enabled" flag'i çıkar
        return {k: v for k, v in fallback_config.items() if k != "enabled"}
    
    return None
