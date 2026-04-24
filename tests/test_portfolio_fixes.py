import pytest
import pandas as pd

from risk.portfolio import PortfolioState, Position
from risk.stop_loss import DynamicStopLoss

def test_calculate_position_size_uses_cash_not_equity():
    portfolio = PortfolioState(initial_cash=10000.0, cash=5000.0)
    # Add a dummy position so equity != cash
    portfolio.positions.append(
        Position(symbol="BTC/USDT", entry_price=50000.0, amount=1.0, entry_time="2026-01-01T00:00:00Z", current_price=50000.0)
    )
    # Equity = 5000 (cash) + 50000 (position) = 55000
    assert portfolio.equity == 55000.0
    
    # Calculate size with 5% risk
    size = portfolio.calculate_position_size(price=50000.0, risk_per_trade=0.05)
    
    # Should be 5000 * 0.05 = 250 / 50000 = 0.005
    # If it was using equity: 55000 * 0.05 = 2750 / 50000 = 0.055
    assert abs(size - 0.005) < 1e-6

def test_atr_fallback_for_empty_or_short_data():
    stop_loss = DynamicStopLoss()
    
    # 1. Empty DataFrame
    df_empty = pd.DataFrame()
    atr = stop_loss.calculate_atr(df_empty, period=14)
    assert atr > 0.0, "ATR should return positive fallback for empty df"
    assert atr == 1.0  # Fallback logic handles empty DataFrame
    
    # 2. Short DataFrame
    df_short = pd.DataFrame({
        "high": [100, 105, 110],
        "low": [90, 95, 100],
        "close": [95, 100, 105]
    })
    atr_short = stop_loss.calculate_atr(df_short, period=14)
    assert atr_short > 0.0, "ATR should return positive average range for short df"
    # Average range = (10+10+10)/3 = 10.0
    assert abs(atr_short - 10.0) < 1e-6

def test_hard_stop_side_aware():
    stop_loss = DynamicStopLoss()
    stop_loss._params.stop_loss.hard_stop_pct = 0.08
    
    long_stop = stop_loss.calculate_hard_stop(50000.0, "long")
    assert abs(long_stop - 46000.0) < 1e-6
    
    short_stop = stop_loss.calculate_hard_stop(50000.0, "short")
    assert abs(short_stop - 54000.0) < 1e-6
    
    with pytest.raises(ValueError):
        stop_loss.calculate_hard_stop(50000.0, "invalid_side")
