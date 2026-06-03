"""
backtest/engine.py 단위 테스트
"""
import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestEngine, BacktestResult


@pytest.fixture
def simple_prices() -> pd.DataFrame:
    """단순 상승 시나리오 가격 데이터"""
    np.random.seed(10)
    dates = pd.bdate_range("2020-01-01", periods=500)
    tickers = ["A", "B", "C"]
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.randn(500, 3) * 0.008, axis=0) * 10_000,
        index=dates,
        columns=tickers,
    )
    return prices.round(0).astype(float)


def equal_weight_fn(prices: pd.DataFrame) -> pd.Series:
    n = len(prices.columns)
    return pd.Series(1.0 / n, index=prices.columns)


def all_first_fn(prices: pd.DataFrame) -> pd.Series:
    w = pd.Series(0.0, index=prices.columns)
    w.iloc[0] = 1.0
    return w


class TestBacktestEngine:
    def test_run_returns_backtest_result(self, simple_prices):
        engine = BacktestEngine(simple_prices, initial_capital=10_000_000)
        result = engine.run(equal_weight_fn, "2020-06-01", "2021-12-31")
        assert isinstance(result, BacktestResult)

    def test_portfolio_values_non_negative(self, simple_prices):
        engine = BacktestEngine(simple_prices, initial_capital=10_000_000)
        result = engine.run(equal_weight_fn, "2020-06-01", "2021-12-31")
        assert (result.portfolio_values >= 0).all()

    def test_initial_capital_preserved_no_cost(self, simple_prices):
        # 거래 비용 0일 때 초기 자본이 유지되는지
        engine = BacktestEngine(simple_prices, initial_capital=10_000_000,
                                transaction_cost=0.0, slippage=0.0)
        result = engine.run(equal_weight_fn, "2020-06-01", "2020-07-31")
        # 첫 포트폴리오 가치가 초기 자본에 가까워야
        assert abs(result.portfolio_values.iloc[0] - 10_000_000) / 10_000_000 < 0.05

    def test_rebalance_log_has_dates(self, simple_prices):
        engine = BacktestEngine(simple_prices)
        result = engine.run(equal_weight_fn, "2020-06-01", "2021-12-31")
        assert not result.rebalance_log.empty
        assert "turnover" in result.rebalance_log.columns

    def test_metrics_computed(self, simple_prices):
        engine = BacktestEngine(simple_prices)
        result = engine.run(equal_weight_fn, "2020-06-01", "2021-12-31")
        m = result.metrics
        assert m.trading_days > 0
        assert m.rebalance_count > 0

    def test_invalid_date_range_raises(self, simple_prices):
        engine = BacktestEngine(simple_prices)
        with pytest.raises(ValueError):
            engine.run(equal_weight_fn, "2030-01-01", "2030-12-31")

    def test_strategy_error_gracefully_handled(self, simple_prices):
        call_count = {"n": 0}

        def flaky_fn(prices):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("전략 오류 시뮬레이션")
            return equal_weight_fn(prices)

        engine = BacktestEngine(simple_prices)
        result = engine.run(flaky_fn, "2020-06-01", "2021-06-30")
        # 오류가 발생해도 결과 반환
        assert isinstance(result, BacktestResult)

    def test_weekly_rebalance_more_frequent_than_monthly(self, simple_prices):
        monthly_engine = BacktestEngine(simple_prices, rebalance_frequency="monthly")
        weekly_engine = BacktestEngine(simple_prices, rebalance_frequency="weekly")
        r_monthly = monthly_engine.run(equal_weight_fn, "2020-06-01", "2021-12-31")
        r_weekly = weekly_engine.run(equal_weight_fn, "2020-06-01", "2021-12-31")
        assert r_weekly.metrics.rebalance_count > r_monthly.metrics.rebalance_count
