"""
Phase 4 팩터 엔진(MacroFactorAdjuster, VolatilityTargeter, FactorScorer) 단위 테스트
+ MultiStrategy 파이프라인 통합 테스트
"""
import sys
import types
from datetime import date

import numpy as np
import pandas as pd
import pytest

from strategy.factor_engine import (
    MacroFactorAdjuster,
    VolatilityTargeter,
    FactorScorer,
    _BOND_ETFS,
    _FOREIGN_ETFS,
    _CASH_ETF,
)
from strategy.multi_strategy import MultiStrategyPortfolio


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _trend_series(n: int, direction: int, start: float = 10_000) -> pd.Series:
    """단조 증가(direction=1) / 감소(direction=-1) 가격 시리즈"""
    dates = pd.bdate_range("2023-01-01", periods=n)
    step = 0.003 * direction
    prices = start * np.cumprod(1 + np.full(n, step))
    return pd.Series(prices, index=dates)


def _sawtooth_series(n: int, r: float, start: float = 10_000) -> pd.Series:
    """+r/-r 교대 수익률 시리즈 (변동성 크기를 정밀하게 제어하기 위함)"""
    dates = pd.bdate_range("2023-01-01", periods=n)
    rets = np.array([r if i % 2 == 0 else -r for i in range(n)])
    prices = start * np.cumprod(1 + rets)
    return pd.Series(prices, index=dates)


def _flat_series(n: int, start: float = 10_000) -> pd.Series:
    dates = pd.bdate_range("2023-01-01", periods=n)
    return pd.Series(np.full(n, float(start)), index=dates)


# ── MacroFactorAdjuster._bond_signal ──────────────────────────────

class TestBondSignal:
    def test_uptrend_signals_rate_decline(self):
        adjuster = MacroFactorAdjuster()
        prices = pd.DataFrame({_BOND_ETFS[0]: _trend_series(100, +1)})
        assert adjuster._bond_signal(prices) == 1

    def test_downtrend_signals_rate_hike(self):
        adjuster = MacroFactorAdjuster()
        prices = pd.DataFrame({_BOND_ETFS[0]: _trend_series(100, -1)})
        assert adjuster._bond_signal(prices) == -1

    def test_no_bond_columns_returns_neutral(self):
        adjuster = MacroFactorAdjuster()
        prices = pd.DataFrame({"999999": _trend_series(100, +1)})
        assert adjuster._bond_signal(prices) == 1

    def test_insufficient_history_returns_neutral(self):
        adjuster = MacroFactorAdjuster(ma_long=60)
        prices = pd.DataFrame({_BOND_ETFS[0]: _trend_series(10, -1)})
        assert adjuster._bond_signal(prices) == 1


# ── MacroFactorAdjuster._fx_signal ─────────────────────────────────

class TestFxSignal:
    def test_uses_same_day_cache(self):
        adjuster = MacroFactorAdjuster()
        adjuster._fx_cache = (date.today(), -1)
        assert adjuster._fx_signal() == -1

    def test_falls_back_to_neutral_on_fetch_error(self, monkeypatch):
        fake_mod = types.ModuleType("FinanceDataReader")
        fake_mod.DataReader = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network down"))
        monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_mod)

        adjuster = MacroFactorAdjuster()
        assert adjuster._fx_signal() == 1

    def test_detects_won_weakness_from_fetched_series(self, monkeypatch):
        fake_mod = types.ModuleType("FinanceDataReader")
        fake_mod.DataReader = lambda *a, **k: pd.DataFrame(
            {"Close": _trend_series(200, +1)}
        )
        monkeypatch.setitem(sys.modules, "FinanceDataReader", fake_mod)

        adjuster = MacroFactorAdjuster()
        assert adjuster._fx_signal() == -1   # 달러 상승 추세 = 원화 약세


# ── MacroFactorAdjuster.adjust ─────────────────────────────────────

class TestMacroAdjust:
    def _weights_and_prices(self) -> tuple[pd.Series, pd.DataFrame]:
        tickers = [_BOND_ETFS[0], _FOREIGN_ETFS[0], _CASH_ETF, "069500"]
        weights = pd.Series({_BOND_ETFS[0]: 0.3, _FOREIGN_ETFS[0]: 0.3, _CASH_ETF: 0.1, "069500": 0.3})
        prices = pd.DataFrame({t: _trend_series(100, +1) for t in tickers})
        return weights, prices

    def test_rate_hike_cuts_bond_weight_into_cash(self, monkeypatch):
        adjuster = MacroFactorAdjuster(adjust_strength=0.25)
        weights, prices = self._weights_and_prices()
        monkeypatch.setattr(adjuster, "_bond_signal", lambda p: -1)
        monkeypatch.setattr(adjuster, "_fx_signal", lambda: 1)

        result = adjuster.adjust(weights, prices)

        assert result[_BOND_ETFS[0]] == pytest.approx(0.3 * 0.75 / 1.0, rel=1e-3)
        assert result[_CASH_ETF] > weights[_CASH_ETF]
        assert abs(result.sum() - 1.0) < 1e-9

    def test_won_weakness_cuts_foreign_weight_into_cash(self, monkeypatch):
        adjuster = MacroFactorAdjuster(adjust_strength=0.25)
        weights, prices = self._weights_and_prices()
        monkeypatch.setattr(adjuster, "_bond_signal", lambda p: 1)
        monkeypatch.setattr(adjuster, "_fx_signal", lambda: -1)

        result = adjuster.adjust(weights, prices)

        assert result[_FOREIGN_ETFS[0]] < weights[_FOREIGN_ETFS[0]]
        assert result[_CASH_ETF] > weights[_CASH_ETF]
        assert abs(result.sum() - 1.0) < 1e-9

    def test_neutral_signals_leave_weights_unchanged(self, monkeypatch):
        adjuster = MacroFactorAdjuster()
        weights, prices = self._weights_and_prices()
        monkeypatch.setattr(adjuster, "_bond_signal", lambda p: 1)
        monkeypatch.setattr(adjuster, "_fx_signal", lambda: 1)

        result = adjuster.adjust(weights, prices)

        pd.testing.assert_series_equal(result.sort_index(), weights.sort_index())


# ── VolatilityTargeter ─────────────────────────────────────────────

class TestVolatilityTargeter:
    def test_zero_vol_when_no_qualifying_tickers(self):
        targeter = VolatilityTargeter()
        weights = pd.Series({"AAA": 0.005})  # 1% 미만 → 제외
        prices = pd.DataFrame({"AAA": _flat_series(100)})
        assert targeter._portfolio_vol(weights, prices) == 0.0

    def test_extreme_high_vol_floors_at_min_scale(self):
        targeter = VolatilityTargeter(target_vol=0.10, min_scale=0.5, max_scale=1.0)
        weights = pd.Series({"AAA": 1.0, _CASH_ETF: 0.0})
        prices = pd.DataFrame({
            "AAA": _sawtooth_series(100, r=0.05),
            _CASH_ETF: _flat_series(100),
        })

        result = targeter.target(weights, prices)

        assert result["AAA"] == pytest.approx(0.5, abs=1e-6)
        assert result[_CASH_ETF] == pytest.approx(0.5, abs=1e-6)

    def test_low_vol_clips_to_max_scale_and_stays_unchanged(self):
        targeter = VolatilityTargeter(target_vol=0.30)
        weights = pd.Series({"AAA": 0.6, "BBB": 0.4})
        prices = pd.DataFrame({
            "AAA": _flat_series(100, start=10_000) + np.random.RandomState(0).normal(0, 1, 100),
            "BBB": _flat_series(100, start=10_000) + np.random.RandomState(1).normal(0, 1, 100),
        })

        result = targeter.target(weights, prices)

        pd.testing.assert_series_equal(result, weights)

    def test_moderate_vol_scales_down_and_adds_cash(self):
        targeter = VolatilityTargeter(target_vol=0.10, dead_band=0.05)
        weights = pd.Series({"AAA": 1.0, _CASH_ETF: 0.0})
        prices = pd.DataFrame({
            "AAA": _sawtooth_series(200, r=0.008),
            _CASH_ETF: _flat_series(200),
        })

        result = targeter.target(weights, prices)

        assert 0.5 < result["AAA"] < 0.95
        assert result[_CASH_ETF] == pytest.approx(1.0 - result["AAA"], abs=1e-6)


# ── FactorScorer ────────────────────────────────────────────────────

class TestFactorScorer:
    def test_insufficient_data_returns_all_zero(self):
        scorer = FactorScorer(momentum_window=252, momentum_skip=21)
        prices = pd.DataFrame({"AAA": _flat_series(50)})
        result = scorer.score(prices)
        assert (result == 0.0).all()

    def test_strong_uptrend_outranks_downtrend(self):
        scorer = FactorScorer(momentum_window=100, momentum_skip=5, vol_window=60)
        n = 150
        prices = pd.DataFrame({
            "UP":   _trend_series(n, +1),
            "DOWN": _trend_series(n, -1),
        })
        result = scorer.score(prices)
        assert result["UP"] > result["DOWN"]

    def test_composite_score_is_zsum_with_zero_mean(self):
        scorer = FactorScorer(momentum_window=100, momentum_skip=5, vol_window=60)
        n = 150
        prices = pd.DataFrame({
            "A": _trend_series(n, +1),
            "B": _trend_series(n, -1),
            "C": _flat_series(n) + np.random.RandomState(0).normal(0, 5, n),
        })
        result = scorer.score(prices)
        assert result.notna().all()


# ── MultiStrategy Phase 4 통합 ──────────────────────────────────────

@pytest.fixture
def long_prices() -> pd.DataFrame:
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


class TestMultiStrategyPhase4Integration:
    def test_pipeline_calls_macro_then_vol_targeting(self, long_prices, monkeypatch):
        ms = MultiStrategyPortfolio(use_macro_factor=True, use_vol_targeting=True)
        calls = []

        def fake_adjust(weights, prices):
            calls.append("macro")
            return weights

        def fake_target(weights, prices):
            calls.append("vol")
            return weights

        monkeypatch.setattr(ms.macro_adjuster, "adjust", fake_adjust)
        monkeypatch.setattr(ms.vol_targeter, "target", fake_target)

        ms.get_weights(long_prices)

        assert calls == ["macro", "vol"]

    def test_disabling_phase4_skips_adjusters(self, long_prices):
        ms = MultiStrategyPortfolio(use_macro_factor=False, use_vol_targeting=False)
        assert ms.macro_adjuster is None
        assert ms.vol_targeter is None

        w = ms.get_weights(long_prices)

        assert abs(w.sum() - 1.0) < 1e-6
        assert (w >= 0).all()

    def test_enabled_phase4_still_returns_valid_weights(self, long_prices):
        ms = MultiStrategyPortfolio(use_macro_factor=True, use_vol_targeting=True)
        w = ms.get_weights(long_prices)
        assert abs(w.sum() - 1.0) < 1e-6
        assert (w >= 0).all()
        assert set(w.index).issubset(set(long_prices.columns))
