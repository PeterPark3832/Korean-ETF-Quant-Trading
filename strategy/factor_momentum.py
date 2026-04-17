"""
팩터 모멘텀 전략
────────────────────────────────────────────────────────────────
DualMomentum의 단순 가격 모멘텀을 복합 팩터 스코어로 대체합니다.

선택 기준: 모멘텀(50%) + 저변동성(30%) + 샤프비율(20%) 복합 Z-스코어
절대 모멘텀 필터: 복합 점수 > 0 이어야 편입 (단순 양수 체크 대신)

장점:
  - 단기 반전·과최적화 위험 감소
  - 변동성 높은 ETF 자동 회피 (2022년 원유·기술주 급락 방어)
  - 최근 모멘텀 + 꾸준함(샤프) 동시 고려
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from strategy.base import BaseStrategy
from strategy.factor_engine import FactorScorer
from config import ETF_UNIVERSE, ASSET_CLASS_CONSTRAINTS


class FactorMomentumStrategy(BaseStrategy):
    """
    복합 팩터 스코어 기반 모멘텀 전략

    Args:
        top_n_per_class:   자산군별 선택 종목 수 (기본 1)
        score_threshold:   편입 최소 복합 점수 (기본 0.0 = Z-스코어 평균 이상)
        scorer_kwargs:     FactorScorer 파라미터
    """

    name = "FactorMomentum"

    _CLASS_TARGET = {
        "KR_EQUITY":     0.20,
        "GLOBAL_EQUITY": 0.30,
        "BOND":          0.30,
        "COMMODITY":     0.10,
        "CASH":          0.10,
    }

    def __init__(
        self,
        top_n_per_class:  int   = 1,
        score_threshold:  float = 0.0,
        scorer_kwargs:    dict  | None = None,
    ):
        self.top_n_per_class = top_n_per_class
        self.score_threshold = score_threshold
        self.scorer = FactorScorer(**(scorer_kwargs or {}))

    def get_weights(self, prices: pd.DataFrame) -> pd.Series:
        scores  = self.scorer.score(prices)
        weights = pd.Series(0.0, index=prices.columns)

        for asset_class, tickers in ETF_UNIVERSE.items():
            available = [t for t in tickers if t in prices.columns]
            if not available:
                continue

            if asset_class == "CASH":
                cash_w = self._CLASS_TARGET.get("CASH", 0.10)
                weights[available[0]] = cash_w
                continue

            class_scores = scores[available].dropna()
            if class_scores.empty:
                continue

            top_n    = min(self.top_n_per_class, len(class_scores))
            selected = class_scores.nlargest(top_n).index.tolist()

            class_target = self._CLASS_TARGET.get(asset_class, 0.15)
            max_weight   = ASSET_CLASS_CONSTRAINTS[asset_class]["max"]
            alloc        = min(class_target, max_weight)

            cash_tickers = list(ETF_UNIVERSE.get("CASH", {}).keys())

            for ticker in selected:
                if class_scores[ticker] > self.score_threshold:
                    weights[ticker] += alloc / top_n
                else:
                    # 복합 점수 미달 → 현금으로 대체
                    ct = next((t for t in cash_tickers if t in weights.index), None)
                    if ct:
                        weights[ct] += alloc / top_n
                    logger.debug(
                        f"[FactorMomentum] {ticker} 점수 미달 "
                        f"({class_scores[ticker]:.2f} < {self.score_threshold}) → 현금 대체"
                    )

        total = weights.sum()
        if total > 0:
            weights = weights / total

        return weights

    def _param_str(self) -> str:
        return f"top_n={self.top_n_per_class}, threshold={self.score_threshold}"
