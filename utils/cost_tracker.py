"""
LLM Maliyet Takip Modülü
==========================
Her LLM çağrısının maliyetini izler, günlük bütçe kontrolü yapar.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Model fiyatları ($/token) — OpenRouter referans
MODEL_PRICES: dict[str, dict[str, float]] = {
    "deepseek/deepseek-chat-v3-0324": {"input": 2e-7, "output": 2e-7},
    "deepseek/deepseek-reasoner": {"input": 5.5e-7, "output": 2.2e-6},
    "anthropic/claude-sonnet-4-20250514": {"input": 3e-6, "output": 1.5e-5},
    "openai/gpt-4o-mini": {"input": 1.5e-7, "output": 6e-7},
}

DEFAULT_PRICE = {"input": 1e-6, "output": 2e-6}


class CostTracker:
    """LLM API maliyet takipçisi."""

    def __init__(self, daily_budget_usd: float = 5.0) -> None:
        self.daily_budget = daily_budget_usd
        self.total_cost = 0.0
        self.daily_cost = 0.0
        self.daily_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.calls: list[dict[str, Any]] = []

    def record_call(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float | None = None,
    ) -> None:
        """
        LLM çağrısını kaydeder.

        Args:
            model: Model ismi
            input_tokens: Giriş token sayısı
            output_tokens: Çıkış token sayısı
            cost_usd: Maliyet (None = model fiyatlarından hesapla)
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.daily_date:
            self.daily_cost = 0.0
            self.daily_date = today

        if cost_usd is None:
            cost_usd = estimate_cost(model, input_tokens, output_tokens)

        self.total_cost += cost_usd
        self.daily_cost += cost_usd
        self.calls.append(
            {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        logger.debug(
            "LLM çağrı maliyeti: %s — $%.6f (günlük: $%.4f / $%.2f)",
            model,
            cost_usd,
            self.daily_cost,
            self.daily_budget,
        )

    def is_within_budget(self) -> bool:
        """Günlük bütçe içinde mi?"""
        return self.daily_cost < self.daily_budget

    def get_summary(self) -> dict[str, Any]:
        """Maliyet özeti."""
        return {
            "total_cost_usd": round(self.total_cost, 4),
            "daily_cost_usd": round(self.daily_cost, 4),
            "daily_budget_usd": self.daily_budget,
            "within_budget": self.is_within_budget(),
            "total_calls": len(self.calls),
            "budget_usage_pct": round((self.daily_cost / self.daily_budget) * 100, 1)
            if self.daily_budget > 0
            else 0,
        }

    def reset(self) -> None:
        """Tüm sayaçları sıfırlar."""
        self.total_cost = 0.0
        self.daily_cost = 0.0
        self.calls.clear()


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Model bazlı maliyet tahmini.

    Args:
        model: Model ismi
        input_tokens: Giriş token sayısı
        output_tokens: Çıkış token sayısı

    Returns:
        Tahmini maliyet (USD)
    """
    prices = MODEL_PRICES.get(model, DEFAULT_PRICE)
    return input_tokens * prices["input"] + output_tokens * prices["output"]
