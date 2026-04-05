"""
CVaR (Conditional Value at Risk) Optimizer
============================================
Portföy ağırlıklarını kuyruk riskini minimize edecek şekilde optimize eder.
Mean-Variance yerine CVaR kullanarak nadir fakat yıkıcı kayıpları dikkate alır.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from config.settings import get_trading_params

logger = logging.getLogger(__name__)


def calculate_portfolio_cvar(
    returns: pd.DataFrame,
    weights: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """
    Portföy CVaR'ını hesaplar.

    Args:
        returns: Varlık getiri matrisi (her sütun bir varlık)
        weights: Portföy ağırlıkları
        confidence: Güven düzeyi (0.95 → en kötü %5'lik dilim)

    Returns:
        CVaR değeri (negatif → kayıp)
    """
    portfolio_returns = returns.values @ weights
    var_threshold = np.percentile(portfolio_returns, (1 - confidence) * 100)
    cvar = portfolio_returns[portfolio_returns <= var_threshold].mean()
    return float(cvar) if not np.isnan(cvar) else 0.0


def calculate_var(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Tek varlık VaR hesaplama."""
    if isinstance(returns, pd.Series):
        returns = returns.values
    return float(np.percentile(returns, (1 - confidence) * 100))


def optimize_portfolio_cvar(
    returns: pd.DataFrame,
    confidence: float | None = None,
    max_weight: float | None = None,
) -> dict:
    """
    CVaR'ı minimize eden portföy ağırlıklarını bulur.

    Args:
        returns: Varlık günlük getiri matrisi
        confidence: CVaR güven düzeyi
        max_weight: Tek varlık max ağırlığı

    Returns:
        {
            "weights": dict,
            "cvar": float,
            "expected_return": float,
            "var": float,
        }
    """
    params = get_trading_params()
    conf = confidence or params.risk.cvar_confidence
    mw = max_weight if max_weight is not None else params.risk.cvar.max_weight
    n_assets = returns.shape[1]

    if n_assets == 0:
        return {"weights": {}, "cvar": 0, "expected_return": 0, "var": 0}

    if n_assets == 1:
        # Tek varlık — optimizasyon gerekmez
        asset_returns = returns.iloc[:, 0].values
        return {
            "weights": {returns.columns[0]: 1.0},
            "cvar": calculate_var(asset_returns, conf),
            "expected_return": float(np.mean(asset_returns)),
            "var": calculate_var(asset_returns, conf),
        }

    # Amaç fonksiyonu: CVaR'ı minimize et
    def objective(w):
        return -calculate_portfolio_cvar(returns, w, conf)

    # Kısıtlamalar
    constraints = [
        {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},  # Ağırlıklar toplamı = 1
    ]

    # Sınırlar: 0 ≤ weight ≤ max_weight
    bounds = [(0.0, mw) for _ in range(n_assets)]

    # Başlangıç: eşit dağılım
    w0 = np.ones(n_assets) / n_assets

    try:
        result = minimize(
            objective,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-10},
        )

        if result.success:
            optimal_weights = result.x
        else:
            logger.warning(
                "CVaR optimizasyonu yakınsayamadı, eşit dağılım kullanılıyor"
            )
            optimal_weights = w0

    except Exception as e:
        logger.error("CVaR optimizasyon hatası: %s", e)
        optimal_weights = w0

    # Sonuçları hesapla
    portfolio_cvar = calculate_portfolio_cvar(returns, optimal_weights, conf)
    portfolio_returns = returns.values @ optimal_weights
    expected_return = float(np.mean(portfolio_returns)) * 252  # Yıllıklandır
    portfolio_var = calculate_var(portfolio_returns, conf)

    weights_dict = {
        col: round(float(w), 4)
        for col, w in zip(returns.columns, optimal_weights)
        if w > 0.001  # Çok küçük ağırlıkları filtrele
    }

    logger.info(
        "CVaR optimizasyonu: CVaR=%.4f, VaR=%.4f, Beklenen Getiri=%.2f%%",
        portfolio_cvar,
        portfolio_var,
        expected_return * 100,
    )

    return {
        "weights": weights_dict,
        "cvar": round(portfolio_cvar, 6),
        "var": round(portfolio_var, 6),
        "expected_return": round(expected_return, 6),
    }


def stress_test_monte_carlo(
    returns: pd.Series | np.ndarray,
    n_simulations: int = 10000,
    n_days: int = 30,
    confidence: float = 0.95,
    seed: int | None = None,
) -> dict:
    """
    Monte Carlo simülasyonu ile stres testi.

    Args:
        returns: Geçmiş günlük getiriler
        n_simulations: Simülasyon sayısı
        n_days: Simülasyon periyodu (gün)
        confidence: güven düzeyi

    Returns:
        Stres testi sonuçları
    """
    if isinstance(returns, pd.Series):
        returns = returns.values

    mean_return = np.mean(returns)
    std_return = np.std(returns)

    # Simüle edilmiş kümülatif getiriler
    np.random.seed(seed)
    simulated = np.random.normal(mean_return, std_return, (n_simulations, n_days))
    cumulative = np.cumprod(1 + simulated, axis=1)
    final_values = cumulative[:, -1]

    var = float(np.percentile(final_values - 1, (1 - confidence) * 100))
    cvar = (
        float(final_values[final_values - 1 <= var].mean() - 1)
        if np.any(final_values - 1 <= var)
        else var
    )
    max_drawdown = float(np.min(final_values) - 1)
    median_return = float(np.median(final_values) - 1)

    return {
        "var": round(var, 6),
        "cvar": round(cvar, 6),
        "max_loss": round(max_drawdown, 6),
        "median_return": round(median_return, 6),
        "worst_case_5pct": round(float(np.percentile(final_values - 1, 5)), 6),
        "best_case_95pct": round(float(np.percentile(final_values - 1, 95)), 6),
        "n_simulations": n_simulations,
        "n_days": n_days,
    }
