"""
리스크 패리티 전략 - 변동성 타겟팅 추가 버전
────────────────────────────────────────────────────────────────
각 자산이 포트폴리오 총 리스크에 동등하게 기여하도록 비중 배분.

[개선 사항]
1. 변동성 타겟팅 (Volatility Targeting):
   - 목표 연 변동성 8%에 맞게 포트폴리오 전체 스케일 조정
   - 포트폴리오 변동성 < 8%면 비중 상향, > 8%면 하향
   - 레버리지 없음 (최대 100%)
   - 효과: 너무 보수적이던 리스크 패리티를 목표 수익률 구간으로 조정

2. 현금성 ETF 최소 비중 확보:
   - 변동성 낮은 단기채/현금성이 과도하게 쏠리는 문제 해결
   - 단기채 최대 40% 캡 적용

구현 방법:
- Naive Risk Parity: 1/σ 비중 (기본, 과최적화 방지)
- ERC (Equal Risk Contribution): 선택적 최적화

모멘텀 필터:
- 음수 모멘텀 자산 제외 → 하락 구간 방어력 강화
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from scipy.optimize import minimize
from loguru import logger

from strategy.base import BaseStrategy
from config import ETF_UNIVERSE, ASSET_CLASS_CONSTRAINTS


class RiskParityStrategy(BaseStrategy):
    """
    리스크 패리티 + 변동성 타겟팅

    Args:
        vol_window:       변동성 계산 윈도우 (거래일, 기본 60일)
        target_vol:       목표 연 변동성 (기본 0.08 = 8%)
        use_erc:          True=ERC 최적화, False=Naive 역변동성
        momentum_filter:  True=음수 모멘텀 자산 제외
        momentum_months:  모멘텀 계산 기간
        min_assets:       최소 보유 종목 수
        max_single_weight: 단일 종목 최대 비중
    """

    name = "RiskParity-VT"   # VT = Volatility Targeting

    def __init__(
        self,
        vol_window: int            = 60,
        target_vol: float          = 0.10,   # 10% 목표 변동성
        use_erc: bool              = False,
        momentum_filter: bool      = True,
        momentum_months: int       = 6,
        momentum_threshold: float  = -0.05,  # -5% 이하만 제외 (0% → -5% 완화)
        min_assets: int            = 5,      # 최소 5종목 유지
        max_single_weight: float   = 0.35,
    ):
        self.vol_window           = vol_window
        self.target_vol           = target_vol
        self.use_erc              = use_erc
        self.momentum_filter      = momentum_filter
        self.momentum_months      = momentum_months
        self.momentum_threshold   = momentum_threshold
        self.min_assets           = min_assets
        self.max_single_weight    = max_single_weight

    def get_weights(self, prices: pd.DataFrame) -> pd.Series:
        if len(prices) < self.vol_window + 5:
            return self._equal_weight(prices.columns)

        returns    = prices.pct_change().dropna()
        recent_ret = returns.tail(self.vol_window)
        vols       = recent_ret.std() * np.sqrt(252)
        vols       = vols.replace(0, np.nan).dropna()

        if vols.empty:
            return self._equal_weight(prices.columns)

        # ── 모멘텀 필터 ────────────────────────────────
        candidates = vols.index.tolist()
        if self.momentum_filter:
            filtered = self._apply_momentum_filter(prices, candidates)
            if len(filtered) >= self.min_assets:
                candidates = filtered
            # 필터 후 종목 부족 시 원본 유지

        vols = vols.reindex(candidates).dropna()
        if vols.empty:
            return self._equal_weight(prices.columns)

        # ── 역변동성 비중 계산 ─────────────────────────
        if self.use_erc and len(candidates) >= 2:
            raw_weights = self._erc_weights(recent_ret[candidates])
        else:
            inv_vol     = 1.0 / vols
            raw_weights = inv_vol / inv_vol.sum()

        # ── 단일 종목 상한 클립 ────────────────────────
        raw_weights = raw_weights.clip(upper=self.max_single_weight)
        raw_weights = raw_weights / raw_weights.sum()

        # ── 자산군 비중 제약 ───────────────────────────
        raw_weights = self._apply_class_constraints(raw_weights)

        # ── 변동성 타겟팅 스케일링 ─────────────────────
        # 포트폴리오 예상 변동성 계산
        port_vol = self._estimate_portfolio_vol(recent_ret, raw_weights)
        if port_vol > 0:
            scale = min(self.target_vol / port_vol, 1.0)  # 레버리지 없음 (max=1.0)
            raw_weights = raw_weights * scale

            # 스케일 후 남은 비중 → 현금성 ETF(KOFR)에 배치
            remaining = 1.0 - raw_weights.sum()
            if remaining > 0.01:
                cash_tickers = list(ETF_UNIVERSE.get("CASH", {}).keys())
                avail_cash   = [t for t in cash_tickers if t in prices.columns]
                if avail_cash:
                    raw_weights = raw_weights.reindex(prices.columns).fillna(0)
                    # 현금성 ETF 중 단기통안채(157450) 우선
                    best_cash = next(
                        (t for t in ["157450", "449170"] if t in avail_cash),
                        avail_cash[0]
                    )
                    raw_weights[best_cash] = raw_weights.get(best_cash, 0) + remaining

        # ── 전체 ticker로 확장 ─────────────────────────
        weights = pd.Series(0.0, index=prices.columns)
        for t, w in raw_weights.items():
            if t in weights.index:
                weights[t] = w

        total = weights.sum()
        if total > 0:
            weights = weights / total

        return weights

    # ── 변동성 계산 ────────────────────────────────────

    def _estimate_portfolio_vol(
        self,
        returns: pd.DataFrame,
        weights: pd.Series,
    ) -> float:
        """포트폴리오 연간 변동성 추정"""
        common = weights.index.intersection(returns.columns)
        if common.empty:
            return 0.0
        w   = weights.reindex(common).fillna(0).values
        cov = returns[common].cov().values * 252
        pv  = float(w @ cov @ w) ** 0.5
        return pv

    # ── 모멘텀 필터 ────────────────────────────────────

    def _apply_momentum_filter(
        self, prices: pd.DataFrame, candidates: list[str]
    ) -> list[str]:
        td = self.momentum_months * 21
        if len(prices) <= td:
            return candidates
        momentum_ret = (prices.iloc[-1] / prices.iloc[-td]) - 1
        # 임계값 이하(-5%)만 제외 → 소폭 음수 자산은 유지
        return [t for t in candidates
                if momentum_ret.get(t, 0) > self.momentum_threshold]

    # ── 자산군 제약 ────────────────────────────────────

    def _apply_class_constraints(self, weights: pd.Series) -> pd.Series:
        adjusted = weights.copy()
        for asset_class, tickers_dict in ETF_UNIVERSE.items():
            class_tickers = [t for t in tickers_dict if t in weights.index]
            if not class_tickers:
                continue
            max_w       = ASSET_CLASS_CONSTRAINTS.get(asset_class, {}).get("max", 1.0)
            class_total = adjusted[class_tickers].sum()
            if class_total > max_w and class_total > 0:
                adjusted[class_tickers] *= max_w / class_total
        total = adjusted.sum()
        return adjusted / total if total > 0 else adjusted

    # ── ERC 최적화 ─────────────────────────────────────

    def _erc_weights(self, returns: pd.DataFrame) -> pd.Series:
        cov = returns.cov() * 252
        n   = len(returns.columns)

        def objective(w: np.ndarray) -> float:
            w   = np.array(w)
            pv  = float(w @ cov.values @ w) ** 0.5
            if pv == 0:
                return 1e10
            mrc = cov.values @ w / pv
            rc  = w * mrc
            target = np.full(n, rc.sum() / n)
            return float(np.sum((rc - target) ** 2))

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.01, self.max_single_weight)] * n
        w0     = np.full(n, 1.0 / n)

        try:
            res = minimize(
                objective, w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-9},
            )
            if res.success:
                return pd.Series(res.x, index=returns.columns)
        except Exception as e:
            logger.warning(f"ERC 최적화 실패: {e}")

        # fallback: 역변동성
        vols = returns.std().replace(0, np.nan).dropna()
        inv  = 1.0 / vols
        return (inv / inv.sum()).reindex(returns.columns).fillna(0)

    def _equal_weight(self, tickers: pd.Index) -> pd.Series:
        n = len(tickers)
        return pd.Series(1.0 / n, index=tickers) if n > 0 else pd.Series()

    def _param_str(self) -> str:
        mode = "ERC" if self.use_erc else "NaiveRP"
        return (
            f"{mode}+VT{int(self.target_vol*100)}%, "
            f"vol={self.vol_window}d, "
            f"mom={self.momentum_filter}"
        )
