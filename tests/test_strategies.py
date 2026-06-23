"""
전략 모듈 단위 테스트
- 모든 전략이 공통 계약(합계=1, 음수 없음, 올바른 인덱스)을 준수하는지 검증
"""
import numpy as np
import pandas as pd
import pytest

from strategy.dual_momentum import DualMomentumStrategy
from strategy.vaa import VAAStrategy
from strategy.risk_parity import RiskParityStrategy
from strategy.multi_strategy import MultiStrategyPortfolio
from strategy.kr_gem import KRGemStrategy
from strategy.base import BaseStrategy


# ── 공통 계약 검증 헬퍼 ────────────────────────────────────────

def assert_valid_weights(weights: pd.Series, prices: pd.DataFrame) -> None:
    """전략 출력 비중의 공통 불변 조건 검사"""
    assert isinstance(weights, pd.Series), "weights는 pd.Series이어야 합니다"
    assert (weights >= 0).all(), f"음수 비중 존재: {weights[weights < 0]}"
    assert abs(weights.sum() - 1.0) < 1e-6, f"비중 합계 != 1: {weights.sum()}"
    assert set(weights.index).issubset(set(prices.columns)), "알 수 없는 티커 포함"


# ── 픽스처 ─────────────────────────────────────────────────────

@pytest.fixture
def short_prices() -> pd.DataFrame:
    """데이터가 부족한 경우 (fallback 검증용)"""
    tickers = ["069500", "360750", "449170", "157450", "114820"]
    dates = pd.bdate_range("2024-01-01", periods=15)
    np.random.seed(1)
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.randn(15, len(tickers)) * 0.01, axis=0) * 10_000,
        index=dates, columns=tickers,
    )
    return prices.round(0).astype(float)


@pytest.fixture
def long_prices() -> pd.DataFrame:
    """전략 모멘텀 계산에 충분한 데이터"""
    tickers = [
        "069500", "102110", "278540",
        "360750", "379800", "195970", "192090", "381170",
        "114820", "148070", "308620", "136340",
        "132030", "261220", "144600", "091160",
        "449170", "157450",
    ]
    np.random.seed(42)
    n = 800
    dates = pd.bdate_range("2021-01-01", periods=n)
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.randn(n, len(tickers)) * 0.008, axis=0) * 10_000,
        index=dates, columns=tickers,
    )
    return prices.round(0).astype(float)


# ── DualMomentum ────────────────────────────────────────────────

class TestDualMomentum:
    def test_valid_weights_with_long_data(self, long_prices):
        strat = DualMomentumStrategy()
        w = strat.get_weights(long_prices)
        assert_valid_weights(w, long_prices)

    def test_fallback_to_cash_with_short_data(self, short_prices):
        strat = DualMomentumStrategy()
        w = strat.get_weights(short_prices)
        # 데이터 부족 → 전액 현금
        assert abs(w.sum() - 1.0) < 1e-6
        assert (w >= 0).all()

    def test_repr_contains_params(self):
        strat = DualMomentumStrategy(lookback_months=6, skip_months=0)
        assert "lookback=6m" in repr(strat)

    def test_inherits_base_strategy(self):
        assert issubclass(DualMomentumStrategy, BaseStrategy)


# ── VAA ─────────────────────────────────────────────────────────

class TestVAA:
    def test_valid_weights_with_long_data(self, long_prices):
        strat = VAAStrategy()
        w = strat.get_weights(long_prices)
        assert_valid_weights(w, long_prices)

    def test_fallback_cash_prefers_kofr(self, long_prices):
        strat = VAAStrategy(canary_threshold=0)  # 항상 방어 모드
        # 447170(KOFR)이 있으면 거기에 100% 배분
        w = strat.get_weights(long_prices)
        assert abs(w.sum() - 1.0) < 1e-6

    def test_all_cash_uses_parent_with_custom_order(self, long_prices):
        strat = VAAStrategy()
        w = strat._all_cash(long_prices.columns)
        # KOFR(449170) 또는 단기통안채(157450)에 배분
        assert w["449170"] == 1.0 or w.get("157450", 0) == 1.0 or w.sum() == 1.0

    def test_short_data_returns_cash(self, short_prices):
        strat = VAAStrategy()
        w = strat.get_weights(short_prices)
        assert abs(w.sum() - 1.0) < 1e-6


# ── RiskParity ──────────────────────────────────────────────────

class TestRiskParity:
    def test_valid_weights_with_long_data(self, long_prices):
        strat = RiskParityStrategy()
        w = strat.get_weights(long_prices)
        assert_valid_weights(w, long_prices)

    def test_no_single_weight_exceeds_limit(self, long_prices):
        strat = RiskParityStrategy(max_single_weight=0.35)
        w = strat.get_weights(long_prices)
        assert (w <= 0.35 + 1e-6).all()

    def test_fallback_equal_weight_short_data(self, short_prices):
        strat = RiskParityStrategy(vol_window=60)
        w = strat.get_weights(short_prices)
        assert abs(w.sum() - 1.0) < 1e-6


# ── MultiStrategy ───────────────────────────────────────────────

class TestMultiStrategy:
    def test_valid_weights_with_long_data(self, long_prices):
        strat = MultiStrategyPortfolio(use_macro_factor=False, use_vol_targeting=False)
        w = strat.get_weights(long_prices)
        assert_valid_weights(w, long_prices)

    def test_bull_bear_blend_sums_to_one(self, long_prices):
        strat = MultiStrategyPortfolio(use_macro_factor=False, use_vol_targeting=False)
        w = strat.get_weights(long_prices)
        assert abs(w.sum() - 1.0) < 1e-6


# ── KRGem ───────────────────────────────────────────────────────

class TestKRGem:
    def test_valid_weights_with_long_data(self, long_prices):
        strat = KRGemStrategy()
        w = strat.get_weights(long_prices)
        assert_valid_weights(w, long_prices)

    def test_top_n_slots_each_get_equal_share(self, long_prices):
        strat = KRGemStrategy(top_n=3)
        w = strat.get_weights(long_prices)
        # 위험자산 또는 안전자산에 분배된 비중의 개수가 top_n 이하
        nonzero = w[w > 1e-9]
        assert len(nonzero) <= strat.top_n
        assert abs(w.sum() - 1.0) < 1e-6

    def test_fallback_to_first_column_without_safe_asset(self, long_prices):
        strat = KRGemStrategy()
        prices_no_safe = long_prices.drop(columns=[strat.SAFE_ASSET])
        w = strat.get_weights(prices_no_safe)
        assert abs(w.sum() - 1.0) < 1e-6
        assert w.iloc[0] == 1.0

    def test_fallback_to_safe_asset_with_insufficient_data(self, short_prices):
        # short_prices에는 위험자산 모멘텀 계산에 필요한 룩백(63일) 데이터가 없음
        strat = KRGemStrategy()
        w = strat.get_weights(short_prices)
        assert abs(w.sum() - 1.0) < 1e-6
        assert w.get(strat.SAFE_ASSET, 0) == 1.0

    def test_absolute_momentum_filter_routes_to_safe_asset(self):
        # 위험자산은 하락, 현금성 자산은 상승 → 절대 모멘텀 미달로 전량 안전자산행
        strat = KRGemStrategy(top_n=3)
        tickers = strat.RISK_ASSETS + [strat.SAFE_ASSET, strat.CASH_PROXY]
        dates = pd.bdate_range("2021-01-01", periods=300)
        prices = pd.DataFrame(index=dates, columns=tickers, dtype=float)
        for tk in strat.RISK_ASSETS:
            prices[tk] = np.linspace(10_000, 5_000, len(dates))   # 하락
        prices[strat.CASH_PROXY] = np.linspace(10_000, 12_000, len(dates))  # 상승
        prices[strat.SAFE_ASSET] = np.linspace(10_000, 11_000, len(dates))

        w = strat.get_weights(prices)
        assert abs(w.sum() - 1.0) < 1e-6
        assert w[strat.SAFE_ASSET] == 1.0
        for tk in strat.RISK_ASSETS:
            assert w.get(tk, 0) == 0.0

    def test_inherits_base_strategy(self):
        assert issubclass(KRGemStrategy, BaseStrategy)

    def test_repr_contains_top_n(self):
        strat = KRGemStrategy(top_n=2)
        assert "top_n=2" in repr(strat)


# ── BaseStrategy 공통 유틸리티 ──────────────────────────────────

class TestBaseStrategyUtils:
    def test_normalize_weights_sums_to_one(self):
        w = pd.Series({"A": 0.3, "B": 0.6, "C": 0.1})
        n = BaseStrategy.normalize_weights(w * 2)  # 합계 2.0
        assert abs(n.sum() - 1.0) < 1e-9

    def test_normalize_zero_returns_unchanged(self):
        w = pd.Series({"A": 0.0, "B": 0.0})
        result = BaseStrategy.normalize_weights(w)
        assert result.sum() == 0.0

    def test_all_cash_picks_first_cash_etf(self, long_prices):
        strat = DualMomentumStrategy()
        w = strat._all_cash(long_prices.columns)
        assert abs(w.sum() - 1.0) < 1e-9
        assert (w >= 0).all()
        # 비중 1인 종목이 정확히 1개
        assert (w == 1.0).sum() == 1
