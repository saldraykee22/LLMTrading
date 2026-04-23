"""Correlation checker for open positions."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from risk.portfolio import Position

logger = logging.getLogger(__name__)


class CorrelationChecker:
    """Checks correlation between open positions using daily returns."""

    def __init__(self, symbols: list[str], ohlcv_data: dict[str, pd.DataFrame]):
        self.symbols = symbols
        self.ohlcv_data = ohlcv_data

    def compute_correlation(self, df_dict: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Computes correlation matrix from OHLCV DataFrames using daily returns."""
        returns_dict: dict[str, pd.Series] = {}
        for symbol, df in df_dict.items():
            if "close" not in df.columns or len(df) < 2:
                logger.warning("Insufficient data for symbol: %s", symbol)
                continue
            returns_dict[symbol] = df["close"].pct_change().dropna()

        if not returns_dict:
            return pd.DataFrame()

        returns_df = pd.DataFrame(returns_dict)
        returns_df = returns_df.dropna(how="any")
        if returns_df.empty or len(returns_df) < 2:
            return pd.DataFrame()

        corr_matrix = returns_df.corr(method="pearson")
        return corr_matrix

    def check_positions(
        self,
        portfolio_positions: list[Position],
        market_data: dict[str, pd.DataFrame],
        max_correlation: float = 0.7,
    ) -> dict[str, Any]:
        """Checks if any open positions are too highly correlated."""
        symbols = [p.symbol for p in portfolio_positions]
        available = {s: market_data[s] for s in symbols if s in market_data}

        if len(available) < 2:
            return {
                "is_safe": True,
                "correlated_pairs": [],
                "max_correlation": 0.0,
            }

        corr_matrix = self.compute_correlation(available)
        if corr_matrix.empty:
            return {
                "is_safe": True,
                "correlated_pairs": [],
                "max_correlation": 0.0,
            }

        correlated_pairs: list[dict] = []
        global_max = 0.0

        sym_list = list(corr_matrix.columns)
        for i in range(len(sym_list)):
            for j in range(i + 1, len(sym_list)):
                s1, s2 = sym_list[i], sym_list[j]
                corr_value = corr_matrix.loc[s1, s2]
                if abs(corr_value) > global_max:
                    global_max = abs(corr_value)
                if corr_value > max_correlation:
                    correlated_pairs.append(
                        {
                            "symbol_1": s1,
                            "symbol_2": s2,
                            "correlation": round(corr_value, 4),
                        }
                    )
                    logger.warning(
                        "High correlation detected: %s <-> %s (%.4f)",
                        s1,
                        s2,
                        corr_value,
                    )

        is_safe = len(correlated_pairs) == 0
        return {
            "is_safe": is_safe,
            "correlated_pairs": correlated_pairs,
            "max_correlation": round(global_max, 4),
        }

    def get_correlated_pairs(
        self,
        portfolio_positions: list,
        market_data: dict[str, pd.DataFrame],
        threshold: float = 0.7,
    ) -> list[dict]:
        """Returns list of highly correlated pairs."""
        result = self.check_positions(
            portfolio_positions, market_data, max_correlation=threshold
        )
        return result["correlated_pairs"]
