"""
Walk-Forward Doğrulama Pipeline'ı
====================================
Aşırı uyumu (overfitting) engellemek için kronolojik veri bölme:
  [====== Eğitim %70 ======][=== Doğrulama %15 ===][=== Test %15 ===]

Look-ahead bias'ı engeller — gelecek verisi asla eğitimde kullanılmaz.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from config.settings import get_trading_params

logger = logging.getLogger(__name__)


@dataclass
class DataSplit:
    """Veri bölme sonucu."""
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    train_range: str
    validation_range: str
    test_range: str


@dataclass
class BacktestResult:
    """Tek periyot backtest sonucu."""
    period: int
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    profitable_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    profit_factor: float
    train_range: str
    test_range: str


def chronological_split(
    df: pd.DataFrame,
    train_pct: float | None = None,
    validation_pct: float | None = None,
    test_pct: float | None = None,
) -> DataSplit:
    """
    Veriyi kronolojik sırayla böler.

    Args:
        df: Sıralı OHLCV + sentiment DataFrame
        train_pct: Eğitim oranı (varsayılan: YAML'den)
        validation_pct: Doğrulama oranı
        test_pct: Test oranı

    Returns:
        DataSplit: Bölünmüş veri setleri
    """
    params = get_trading_params()
    tp = train_pct or params.backtest.train_pct
    vp = validation_pct or params.backtest.validation_pct
    _test_p = test_pct or params.backtest.test_pct

    n = len(df)
    train_end = int(n * tp)
    val_end = int(n * (tp + vp))

    train = df.iloc[:train_end].copy()
    validation = df.iloc[train_end:val_end].copy()
    test = df.iloc[val_end:].copy()

    def _range_str(d: pd.DataFrame) -> str:
        if d.empty:
            return "boş"
        dt_col = "datetime" if "datetime" in d.columns else d.columns[0]
        return f"{d[dt_col].iloc[0]} → {d[dt_col].iloc[-1]}"

    split = DataSplit(
        train=train,
        validation=validation,
        test=test,
        train_range=_range_str(train),
        validation_range=_range_str(validation),
        test_range=_range_str(test),
    )

    logger.info(
        "Veri bölündü: eğitim=%d, doğrulama=%d, test=%d",
        len(train), len(validation), len(test),
    )
    return split


def rolling_walk_forward(
    df: pd.DataFrame,
    train_window: int,
    test_window: int,
    step: int | None = None,
) -> list[DataSplit]:
    """
    Kayan pencere walk-forward bölmeleri oluşturur.

    Args:
        df: Tam veri seti
        train_window: Eğitim penceresi (mum sayısı)
        test_window: Test penceresi
        step: Adım boyutu (varsayılan: test_window)

    Returns:
        DataSplit listesi (her biri bir walk-forward periyodu)
    """
    s = step or test_window
    splits: list[DataSplit] = []
    n = len(df)

    i = 0
    while i + train_window + test_window <= n:
        train = df.iloc[i : i + train_window].copy()
        test = df.iloc[i + train_window : i + train_window + test_window].copy()

        def _range_str(d: pd.DataFrame) -> str:
            if d.empty:
                return "boş"
            dt_col = "datetime" if "datetime" in d.columns else d.columns[0]
            return f"{d[dt_col].iloc[0]} → {d[dt_col].iloc[-1]}"

        splits.append(
            DataSplit(
                train=train,
                validation=pd.DataFrame(),
                test=test,
                train_range=_range_str(train),
                validation_range="",
                test_range=_range_str(test),
            )
        )
        i += s

    logger.info("Walk-forward: %d periyot oluşturuldu", len(splits))
    return splits


def calculate_metrics(
    trades: list[dict[str, Any]],
    initial_cash: float | None = None,
) -> BacktestResult:
    """
    İşlem listesinden performans metriklerini hesaplar.

    Args:
        trades: İşlem kayıtları [{pnl, pnl_pct, ...}, ...]
        initial_cash: Başlangıç sermayesi

    Returns:
        BacktestResult
    """
    params = get_trading_params()
    cash = initial_cash or params.backtest.initial_cash

    if not trades:
        return BacktestResult(
            period=0, total_return=0, sharpe_ratio=0, max_drawdown=0,
            win_rate=0, total_trades=0, profitable_trades=0, losing_trades=0,
            avg_win=0, avg_loss=0, profit_factor=0,
            train_range="", test_range="",
        )

    pnls = [t.get("pnl", 0) for t in trades]
    pnl_pcts = [t.get("pnl_pct", 0) for t in trades]

    total_pnl = sum(pnls)
    total_return = total_pnl / cash if cash > 0 else 0

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    # Sharpe Oranı (yıllıklandırılmış, 252 iş günü varsayımı)
    if pnl_pcts and len(pnl_pcts) > 1:
        returns_arr = np.array(pnl_pcts)
        sharpe = (np.mean(returns_arr) / np.std(returns_arr)) * np.sqrt(252) if np.std(returns_arr) > 0 else 0
    else:
        sharpe = 0

    # Max Drawdown
    equity_curve = [cash]
    for pnl in pnls:
        equity_curve.append(equity_curve[-1] + pnl)
    equity_arr = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity_arr)
    drawdowns = (running_max - equity_arr) / running_max
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0

    return BacktestResult(
        period=0,
        total_return=round(total_return, 6),
        sharpe_ratio=round(float(sharpe), 4),
        max_drawdown=round(max_dd, 6),
        win_rate=round(win_rate, 4),
        total_trades=len(pnls),
        profitable_trades=len(wins),
        losing_trades=len(losses),
        avg_win=round(float(avg_win), 4),
        avg_loss=round(float(avg_loss), 4),
        profit_factor=round(float(profit_factor), 4),
        train_range="",
        test_range="",
    )
