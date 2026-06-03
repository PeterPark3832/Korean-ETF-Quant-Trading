"""
backtest/metrics.py 단위 테스트
"""
import numpy as np
import pandas as pd
import pytest

from backtest.metrics import calculate_metrics, _calculate_mdd, PerformanceMetrics


def make_portfolio(values: list[float], start: str = "2020-01-01") -> pd.Series:
    dates = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=dates, name="portfolio_value")


class TestCalculateMDD:
    def test_no_drawdown(self):
        pv = make_portfolio([100, 110, 120, 130, 140])
        mdd, duration = _calculate_mdd(pv)
        assert mdd == pytest.approx(0.0, abs=1e-9)
        assert duration == 0

    def test_single_drawdown(self):
        # 100 → 90 → 80 → 100: MDD = -20%
        pv = make_portfolio([100, 90, 80, 100])
        mdd, duration = _calculate_mdd(pv)
        assert mdd == pytest.approx(-0.20, abs=1e-9)
        assert duration == 2  # 90, 80 두 구간

    def test_full_recovery(self):
        pv = make_portfolio([100, 80, 60, 100, 120])
        mdd, _ = _calculate_mdd(pv)
        assert mdd == pytest.approx(-0.40, abs=1e-9)

    def test_mdd_duration_counts_correctly(self):
        # 고점 이후 5일 하락
        pv = make_portfolio([100, 95, 90, 85, 80, 75, 100])
        _, duration = _calculate_mdd(pv)
        assert duration == 5

    def test_vectorized_matches_loop(self):
        """벡터화 결과가 이전 루프 기반 로직과 동일한지 검증"""
        np.random.seed(0)
        values = np.cumprod(1 + np.random.randn(500) * 0.01) * 10_000
        pv = make_portfolio(values.tolist())

        mdd_new, dur_new = _calculate_mdd(pv)

        # 기존 루프 방식으로도 계산하여 비교
        cummax = pv.cummax()
        drawdown = (pv - cummax) / cummax
        mdd_old = float(drawdown.min())
        in_dd = drawdown < 0
        max_dur_old, cur = 0, 0
        for flag in in_dd:
            if flag:
                cur += 1
                max_dur_old = max(max_dur_old, cur)
            else:
                cur = 0

        assert mdd_new == pytest.approx(mdd_old, abs=1e-9)
        assert dur_new == max_dur_old


class TestCalculateMetrics:
    def test_basic_uptrend(self):
        pv = make_portfolio([10_000_000 * (1.0008 ** i) for i in range(252)])
        m = calculate_metrics(pv)
        assert m.cagr > 0
        assert m.mdd >= -0.05  # 상승장에서 MDD 작아야
        assert m.sharpe_ratio > 0

    def test_flat_portfolio_returns_zero_cagr(self):
        pv = make_portfolio([10_000_000] * 252)
        m = calculate_metrics(pv)
        assert m.cagr == pytest.approx(0.0, abs=1e-4)

    def test_returns_performance_metrics_dataclass(self):
        pv = make_portfolio([100, 110, 105, 115, 120])
        m = calculate_metrics(pv)
        assert isinstance(m, PerformanceMetrics)
        assert m.trading_days == 5
        assert m.start_date != ""
        assert m.end_date != ""

    def test_too_short_series_returns_empty(self):
        pv = make_portfolio([100])
        m = calculate_metrics(pv)
        assert m.cagr == 0.0
        assert m.mdd == 0.0

    def test_to_dict_has_required_keys(self):
        pv = make_portfolio([100, 110, 105])
        d = calculate_metrics(pv).to_dict()
        required = {"total_return", "cagr", "annual_volatility", "mdd",
                    "sharpe_ratio", "sortino_ratio", "calmar_ratio", "win_rate"}
        assert required.issubset(d.keys())
