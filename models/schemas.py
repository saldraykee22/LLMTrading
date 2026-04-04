# DEPRECATED: Not used, consider removing
"""
Pydantic Schemas for LLM Output Validation
=============================================
LLM çıktılarını doğrulamak için Pydantic modelleri.
Geçersiz çıktı durumunda fallback değerlerle devam eder.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class TradeDecision(BaseModel):
    """LLM trader kararı için validasyon şeması."""

    action: str = Field(..., pattern="^(buy|sell|hold)$")
    symbol: str = Field(..., min_length=1)
    order_type: str = Field(default="market", pattern="^(market|limit)$")
    amount: float = Field(default=0, gt=0)
    entry_price: float = Field(default=0, ge=0)
    stop_loss: float = Field(default=0, ge=0)
    take_profit: float = Field(default=0, ge=0)
    confidence: float = Field(default=0, ge=0, le=1)
    reasoning: str = ""
    time_horizon: str = Field(
        default="swing", pattern="^(scalp|intraday|swing|position)$"
    )
    urgency: str = Field(default="normal", pattern="^(immediate|normal|patient)$")

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be positive for buy/sell")
        return v


class SentimentOutput(BaseModel):
    """LLM sentiment analizi çıktısı için validasyon şeması."""

    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_score: float = Field(..., ge=0.0, le=1.0)
    signal: str = Field(..., pattern="^(bullish|bearish|neutral)$")
    reasoning: str = ""
    key_factors: list[str] = Field(default_factory=list)
    news_summary: str = ""


class RiskAssessment(BaseModel):
    """LLM risk değerlendirmesi çıktısı için validasyon şeması."""

    decision: str = Field(..., pattern="^(approved|rejected)$")
    approved_size: float = Field(default=0, ge=0)
    stop_loss_level: float = Field(default=0, ge=0)
    take_profit_level: float = Field(default=0, ge=0)
    risk_reward_ratio: float = Field(default=0, ge=0)
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    reasoning: str = ""
    warnings: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """LLM araştırma raporu çıktısı için validasyon şeması."""

    symbol: str
    analysis_type: str = "comprehensive"
    trend: str = Field(..., pattern="^(bullish|bearish|neutral)$")
    trend_strength: float = Field(default=0, ge=0, le=1)
    sentiment_summary: str = ""
    risk_factors: list[str] = Field(default_factory=list)
    recommendation: str = Field(
        default="hold",
        pattern="^(strong_buy|buy|hold|sell|strong_sell)$",
    )
    confidence: float = Field(default=0, ge=0, le=1)
    reasoning: str = ""
    time_horizon: str = Field(default="short", pattern="^(short|medium|long)$")


def validate_llm_output(
    model_class: type[BaseModel],
    data: dict[str, Any],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    LLM çıktısını Pydantic modeli ile doğrular.

    Args:
        model_class: Pydantic model sınıfı
        data: LLM'den gelen ham dict
        fallback: Validasyon başarısız olursa kullanılacak fallback

    Returns:
        Validated dict veya fallback
    """
    try:
        validated = model_class(**data)
        return validated.model_dump()
    except Exception as e:
        logger.warning(
            "LLM çıktı validasyon hatası (%s): %s — fallback kullanılıyor",
            model_class.__name__,
            e,
        )
        return fallback or {}
