"""Unit tests for Portfolio Management."""

import pytest

from risk.portfolio import PortfolioState, Position


class TestPortfolioState:
    def test_initial_state(self):
        p = PortfolioState()
        assert p.cash == 10000.0
        assert p.equity == 10000.0
        assert p.open_position_count == 0

    def test_open_long_position(self):
        p = PortfolioState(initial_cash=10000, cash=10000)
        pos = p.open_position("BTC/USDT", "long", 50000, 0.1, stop_loss=48000)
        assert pos is not None
        assert p.open_position_count == 1
        assert p.cash == 5000.0

    def test_open_position_exceeds_cash(self):
        p = PortfolioState(initial_cash=10000, cash=10000)
        pos = p.open_position("BTC/USDT", "long", 50000, 1.0)
        assert pos is None

    def test_close_long_position(self):
        p = PortfolioState(initial_cash=10000, cash=10000)
        p.open_position("BTC/USDT", "long", 50000, 0.1, stop_loss=48000)
        trade = p.close_position("BTC/USDT", 55000)
        assert trade is not None
        assert trade["pnl"] > 0
        assert p.open_position_count == 0

    def test_close_nonexistent_position(self):
        p = PortfolioState()
        trade = p.close_position("NONEXISTENT", 100)
        assert trade is None

    def test_max_positions_limit(self, monkeypatch):
        from config.settings import get_trading_params

        params = get_trading_params()
        orig = params.risk.max_open_positions
        params.risk.max_open_positions = 1
        try:
            p = PortfolioState(initial_cash=100000, cash=100000)
            p.open_position("A", "long", 100, 10)
            pos2 = p.open_position("B", "long", 100, 10)
            assert pos2 is None
        finally:
            params.risk.max_open_positions = orig

    def test_to_dict(self):
        p = PortfolioState(initial_cash=10000, cash=10000)
        p.open_position("BTC/USDT", "long", 50000, 0.1)
        d = p.to_dict()
        assert "cash" in d
        assert "equity" in d
        assert "positions" in d
        assert len(d["positions"]) == 1

    def test_drawdown_update(self):
        p = PortfolioState(initial_cash=10000, cash=10000)
        p.open_position("BTC/USDT", "long", 50000, 0.1)
        p.positions[0].update_price(45000)  # Loss
        p.update_drawdown()
        assert p.current_drawdown >= 0

    def test_daily_pnl_reset(self):
        p = PortfolioState()
        p.daily_pnl = 100.0
        old_date = p.daily_pnl_date
        p.daily_pnl_date = "2000-01-01"
        changed = p.reset_daily_pnl_if_needed()
        assert changed is True
        assert p.daily_pnl == 0.0
