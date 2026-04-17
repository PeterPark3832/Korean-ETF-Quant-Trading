"""
듀얼 모멘텀 전략 (Gary Antonacci)
────────────────────────────────────────────────────────────────
절대 모멘텀 + 상대 모멘텀 조합

1. 상대 모멘텀: 각 자산군 내에서 모멘텀 상위 N개 선택
2. 절대 모멘텀: 선택된 자산의 수익률이 현금(무위험)보다 낮으면 현금으로 대체
3. 자산군별 비중 상한 적용

과최적화 방지:
- 단 3개 파라미터 (lookback, skip, top_n)
- 파라미터 민감도 분석 지원
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from loguru import logger

from strategy.base import BaseStrategy
from config import ETF_UNIVERSE, ASSET_CLASS_CONSTRAINTS


class DualMomentumStrategy(BaseStrategy):
    """
    듀얼 모멘텀 (자산군별 상대 모멘텀 + 절대 모멘텀 필터)

    Args:
        lookback_months:  모멘텀 계산 기간 (기본 12개월)
        skip_months:      최근 반전 효과 제거 (기본 1개월)
        top_n_per_class:  자산군별 선택 종목 수 (기본 1개)
        abs_momentum_threshold: 절대 모멘텀 최소 수익률 (기본 0% = T-bill 대비)
    """

    name = "DualMomentum"

    def __init__(
        self,
        lookback_months: int = 12,
        skip_months: int = 1,
        top_n_per_class: int = 1,
        abs_momentum_threshold: float = 0.0,
    ):
        self.lookback_months          = lookback_months
        self.skip_months              = skip_months
        self.top_n_per_class          = top_n_per_class
        self.abs_momentum_threshold   = abs_momentum_threshold

        # 자산군별 기본 목표 비중 (현금 제외)
        self._class_target = {
            "KR_EQUITY":     0.20,
            "GLOBAL_EQUITY": 0.30,
            "BOND":          0.30,
            "COMMODITY":     0.10,
            "CASH":          0.10,
        }

    def get_weights(self, prices: pd.DataFrame) -> pd.Series:
        if len(prices) < 20:
            return self._all_cash(prices.columns)

        # ── 모멘텀 계산 기간 설정 ──────────────────────
        lookback_td = self.lookback_months * 21   # 거래일
        skip_td     = self.skip_months * 21

        if len(prices) < lookback_td + skip_td:
            return self._all_cash(prices.columns)

        # 모멘텀 = lookback 시작 → (오늘 - skip) 수익률
        end_idx   = len(prices) - skip_td - 1 if skip_td > 0 else len(prices) - 1
        start_idx = end_idx - lookback_td

        if start_idx < 0:
            return self._all_cash(prices.columns)

        price_now  = prices.iloc[end_idx]
        price_past = prices.iloc[start_idx]
        momentum   = (price_now / price_past) - 1

        weights = pd.Series(0.0, index=prices.columns)

        for asset_class, tickers in ETF_UNIVERSE.items():
            available = [t for t in tickers if t in prices.columns]
            if not available:
                continue

            if asset_class == "CASH":
                # 현금성 ETF는 모멘텀 계산 없이 고정 비중
                cash_weight = self._class_target.get("CASH", 0.10)
                best_cash = available[0]
                weights[best_cash] = cash_weight
                continue

            class_momentum = momentum[available].dropna()
            if class_momentum.empty:
                continue

            # 상대 모멘텀: 상위 top_n 선택
            top_n = min(self.top_n_per_class, len(class_momentum))
            selected = class_momentum.nlargest(top_n).index.tolist()

            # 절대 모멘텀 필터
            class_target = self._class_target.get(asset_class, 0.15)
            max_weight   = ASSET_CLASS_CONSTRAINTS[asset_class]["max"]
            alloc        = min(class_target, max_weight)

            for ticker in selected:
                mom = class_momentum[ticker]
                if mom > self.abs_momentum_threshold:
                    # 양의 모멘텀 → 배분
                    weights[ticker] += alloc / top_n
                else:
                    # 음의 모멘텀 → 현금으로 대체
                    cash_tickers = list(ETF_UNIVERSE.get("CASH", {}).keys())
                    if cash_tickers:
                        ct = cash_tickers[0]
                        if ct in weights.index:
                            weights[ct] += alloc / top_n

        # 합산 = 1 정규화
        total = weights.sum()
        if total > 0:
            weights = weights / total

        return weights

    def _all_cash(self, tickers: pd.Index) -> pd.Series:
        w = pd.Series(0.0, index=tickers)
        cash_tickers = list(ETF_UNIVERSE.get("CASH", {}).keys())
        available = [t for t in cash_tickers if t in tickers]
        if available:
            w[available[0]] = 1.0
        elif len(tickers) > 0:
            w.iloc[0] = 1.0
        return w

    def _param_str(self) -> str:
        return (
            f"lookback={self.lookback_months}m, "
            f"skip={self.skip_months}m, "
            f"top_n={self.top_n_per_class}"
        )
