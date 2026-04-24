"""Unit tests for Portfolio Management."""


from risk.portfolio import PortfolioState


class TestPortfolioState:
    def test_initial_state(self):
        p = PortfolioState()
        assert p.cash == 10000.0
        assert p.equity == 10000.0
        assert p.open_position_count == 0

    def test_benchmark_defaults(self):
        p = PortfolioState()
        assert p.benchmark_symbol == "BTC/USDT"
        assert p.benchmark_return == 0.0
        assert p.alpha == 0.0

    def test_update_benchmark(self):
        import pandas as pd

        p = PortfolioState(initial_cash=10000, cash=10000)
        df = pd.DataFrame({"close": [100.0, 110.0, 105.0]})
        bench_ret = p.update_benchmark(df)
        assert bench_ret == 0.05
        assert p.benchmark_return == 0.05
        assert p.alpha == -0.05

    def test_update_benchmark_custom_symbol(self):
        import pandas as pd

        p = PortfolioState()
        df = pd.DataFrame({"close": [50.0, 60.0]})
        bench_ret = p.update_benchmark(df, "ETH/USDT")
        assert bench_ret == 0.2
        assert p.benchmark_symbol == "ETH/USDT"

    def test_update_benchmark_empty_df(self):
        import pandas as pd

        p = PortfolioState()
        df = pd.DataFrame()
        bench_ret = p.update_benchmark(df)
        assert bench_ret == 0.0

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
        assert "benchmark_symbol" in d
        assert "benchmark_return" in d
        assert "alpha" in d

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

    def test_save_and_load_benchmark(self, tmp_path):
        import pandas as pd

        p = PortfolioState(initial_cash=10000, cash=10000)
        df = pd.DataFrame({"close": [100.0, 120.0]})
        p.update_benchmark(df, "ETH/USDT")
        filepath = tmp_path / "portfolio.json"
        p.save_to_file(filepath)
        loaded = PortfolioState.load_from_file(filepath)
        assert loaded.benchmark_symbol == "ETH/USDT"
        assert loaded.benchmark_return == 0.2
        assert loaded.alpha == -0.2
