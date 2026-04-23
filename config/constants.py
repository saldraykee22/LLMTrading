"""
LLM Trading System - Constants
===============================
Merkezi sabit değerler ve konfigürasyon limitleri.
"""

from __future__ import annotations

# ── Security ──────────────────────────────────────────────
MAX_DYNAMIC_RULES_LENGTH = 2000  # Trader dynamic rules max karakter
MAX_HALLUCINATIONS_THRESHOLD = 2  # Risk manager max halüsinasyon sayısı
DUST_THRESHOLD_USDT = 1.0  # Dust bakiye eşiği (USD)

# ── Lock Timeouts ─────────────────────────────────────────
LOCK_TIMEOUT_SECONDS = 30  # Lock acquisition timeout
LOCK_WARNING_THRESHOLD = 5  # Lock hold süresi bu kadar uzunsa uyar

# ── Connection & Timeouts ────────────────────────────────
CONNECTION_TIMEOUT_SECONDS = 300  # API bağlantı timeout (5 dk)
LLM_REQUEST_TIMEOUT = 60  # LLM API request timeout (saniye)
RECONNECT_MAX_DELAY = 32  # Reconnect max delay (saniye)

# ── Risk Management ──────────────────────────────────────
DEFAULT_STOP_LOSS_PCT = 0.02  # Varsayılan stop-loss (%) - ATR yoksa kullanılır
MAX_POSITION_SIZE_CAP = 0.40  # Max pozisyon boyutu (%)
MIN_RISK_REWARD_RATIO = 1.5  # Minimum risk/reward oranı

# ── Retry & Backoff ──────────────────────────────────────
MAX_RETRY_ATTEMPTS = 3  # Varsayılan max retry
BASE_RETRY_DELAY = 2.0  # Initial retry delay (saniye)
MAX_RETRY_DELAY = 30.0  # Max retry delay cap (saniye)

# ── Rate Limiting ────────────────────────────────────────
DEFAULT_RATE_LIMIT_MS = 1200  # Request arası min delay (ms)
MAX_CONCURRENT_REQUESTS = 5  # Max eşzamanlı request

# ── Data Validation ──────────────────────────────────────
MIN_PRICE = 0.00000001  # Min fiyat (crypto precision)
MIN_AMOUNT = 0.00000001  # Min miktar
MAX_PRICE = 1000000.0  # Max fiyat (güvenlik)
MAX_AMOUNT = 1000000.0  # Max miktar (güvenlik)

# ── File Paths ───────────────────────────────────────────
PORTFOLIO_FILE = "data/portfolio_state.json"
STOP_FILE = "data/STOP"
LOGS_DIR = "logs"

# ── Circuit Breaker ──────────────────────────────────────
CIRCUIT_BREAKER_MAX_FAILURES = 5  # Devre kesici threshold
CIRCUIT_BREAKER_RESET_TIMEOUT = 3600  # Reset timeout (saniye)

# ── Ensemble Voting ──────────────────────────────────────
ENSEMBLE_MIN_CONSENSUS = 0.5  # Min konsensüs skoru
ENSEMBLE_MAX_MODELS = 5  # Max model sayısı

# ── Scanner ──────────────────────────────────────────────
SCANNER_MIN_VOLUME_24H = 1000000  # Min 24h hacim (USDT)
SCANNER_MIN_PRICE_CHANGE = 2.0  # Min fiyat değişimi (%)
SCANNER_MAX_CANDIDATES = 30  # Max aday sayısı

# ── Position Management ─────────────────────────────────
MAX_OPEN_POSITIONS = 5  # Max açık pozisyon
MAX_CORRELATED_POSITIONS = 3  # Max korele pozisyon
MAX_CORRELATION_THRESHOLD = 0.70  # Max korelasyon eşiği

# ── Drawdown Limits ─────────────────────────────────────
MAX_DRAWDOWN_PCT = 0.15  # Max drawdown (%15)
MAX_DAILY_LOSS_PCT = 0.03  # Max günlük kayıp (%3)
MAX_CONSECUTIVE_LOSSES = 5  # Max ardışık kayıp

# ── Emergency Stop ──────────────────────────────────────
EMERGENCY_CLOSE_ALL_ON_CRASH = True  # Crash durumunda tüm pozisyonları kapat
CRASH_1M_THRESHOLD = 0.03  # 1 dakikada %3 düşüş
CRASH_5M_THRESHOLD = 0.05  # 5 dakikada %5 düşüş

# ── Logging ──────────────────────────────────────────────
LOG_RETENTION_DAYS = 30  # Log saklama süresi (gün)
AUDIT_LOG_RETENTION_DAYS = 90  # Audit log saklama (gün)

# ── Cache ────────────────────────────────────────────────
CACHE_TTL_MINUTES = 15  # Varsayılan cache TTL
SENTIMENT_CACHE_MINUTES = 30  # Sentiment cache TTL

# ── Validation ───────────────────────────────────────────
MAX_SYMBOL_LENGTH = 50  # Max sembol uzunluğu
MAX_TOKENS_SENTIMENT = 2000  # Max tokens (sentiment)
MAX_TOKENS_RESEARCH = 8000  # Max tokens (research)
MAX_TOKENS_DEBATE = 8000  # Max tokens (debate)
MAX_TOKENS_TRADER = 2000  # Max tokens (trader)
