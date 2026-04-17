"""
VAA (Vigilant Asset Allocation) 전략 - 한국 ETF 최적화 버전
────────────────────────────────────────────────────────────────
원본: Wouter Keller & Jan Willem Keuning (2017)

[한국형 수정 사항]
문제: 원본 VAA는 방어모드에 장기채권 편입 → 2022년 금리인상 구간 -30% 폭락
해결:
  1. 방어 자산을 단기채권/현금성 ETF로 한정 (금리 상승 내성)
  2. 장기채권(미국채10년)은 공격 자산으로 재분류 (모멘텀 양수일 때만 편입)
  3. 카나리아(Canary) 자산 도입: 시장 선행 지표 2개가 음수면 즉시 전액 현금화
  4. 공격 모드에서도 단기채권 최소 20% 유지 (완충 역할)

자산 분류:
  공격(Offensive): 한국주식, 미국주식, 나스닥, 유럽, 골드, 미국채10년
  방어(Defensive): 단기통안채 157450, KOFR현금 449170  ← 금리 무관 안정
  카나리아(Canary): KODEX200 069500, TIGER미국S&P500 360750  ← 시장 경보기

모멘텀 스코어 = (12*r1 + 4*r3 + 2*r6 + r12) / 19
브레이크 규칙:
  - 카나리아 2개 모두 음수 → 전액 현금(KOFR)
  - 카나리아 1개 음수 또는 공격 자산 음수 다수 → 방어 모드
  - 공격 자산 대부분 양수 → 공격 모드
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from loguru import logger

from strategy.base import BaseStrategy
from config import ETF_UNIVERSE


# ── 한국형 자산 분류 ──────────────────────────────────────────

# 공격 자산: 모멘텀 경쟁 대상 (주식 + 원자재 + 장기채 선택 편입)
OFFENSIVE_TICKERS = [
    "069500",  # KODEX 200 (한국주식)
    "360750",  # TIGER 미국S&P500
    "379800",  # KODEX 미국나스닥100TR
    "195970",  # KODEX 유럽선진국
    "192090",  # TIGER 차이나CSI300
    "132030",  # KODEX 골드선물(H)
    "308620",  # KODEX 미국채10년선물 ← 공격 자산으로 재분류 (모멘텀 음수면 제외)
]

# 방어 자산: 금리 상승에도 안정 (단기채권/현금성만)
DEFENSIVE_TICKERS = [
    "157450",  # TIGER 단기통안채    ← 핵심 안전자산 (+1.5% in 2022)
    "449170",  # KODEX KOFR금리액티브 ← 사실상 MMF (+0.3% in 2022)
    "136340",  # KODEX 단기채권PLUS
]

# 카나리아: 시장 선행 경보 자산 (이 중 하나라도 음수 → 방어 강화)
CANARY_TICKERS = [
    "360750",  # TIGER 미국S&P500 (글로벌 위험 선호 지표)
    "069500",  # KODEX 200 (국내 시장 지표)
]

# 공격 모드에서도 유지할 최소 방어 비중
MIN_DEFENSIVE_RATIO = 0.20


class VAAStrategy(BaseStrategy):
    """
    VAA 한국형 (Vigilant Asset Allocation - Korean Edition)

    Args:
        top_n_offensive:     공격 모드에서 선택할 공격 자산 수 (기본 2)
        offensive_ratio:     공격 모드 시 공격 자산 합산 비중 (기본 0.70)
        canary_threshold:    카나리아 음수 개수 → 전액 현금 전환 기준 (기본 2)
        partial_defense_n:   일부 방어 모드 진입 기준 카나리아 음수 개수 (기본 1)
    """

    name = "VAA-KR"

    MOMENTUM_PERIODS = [1, 3, 6, 12]
    MOMENTUM_WEIGHTS = [12, 4, 2, 1]

    def __init__(
        self,
        top_n_offensive: int   = 2,
        offensive_ratio: float = 0.70,
        canary_threshold: int  = 1,   # 카나리아 1개만 음수여도 방어 전환
    ):
        self.top_n_offensive  = top_n_offensive
        self.offensive_ratio  = offensive_ratio
        self.canary_threshold = canary_threshold

    def get_weights(self, prices: pd.DataFrame) -> pd.Series:
        min_days = 12 * 21
        if len(prices) < min_days:
            return self._all_cash(prices.columns)

        scores = self._compute_momentum_scores(prices)
        if scores.empty:
            return self._all_cash(prices.columns)

        # ── 카나리아 신호: 단순 이진 판단 ───────────────
        # 카나리아 2개 중 1개라도 음수 → 즉시 방어모드
        # (부분 방어 모드 제거 - whipsaw 손실 방지)
        canary_available  = [t for t in CANARY_TICKERS if t in prices.columns]
        canary_scores     = scores.reindex(canary_available).dropna()
        n_negative_canary = int((canary_scores <= 0).sum())

        if n_negative_canary >= self.canary_threshold:
            # 전액 현금화 (카나리아 기준 이상 음수)
            logger.debug(f"[VAA-KR] 방어 모드 (카나리아 {n_negative_canary}/{len(canary_available)} 음수)")
            return self._all_cash(prices.columns)

        # ── 공격 모드: 양수 모멘텀 공격 자산 top_n + 방어 버퍼 ──
        weights = self._allocate_offensive(scores, prices.columns)
        total   = weights.sum()
        return weights / total if total > 0 else self._all_cash(prices.columns)

    # ── 모멘텀 스코어 ──────────────────────────────────

    def _compute_momentum_scores(self, prices: pd.DataFrame) -> pd.Series:
        scores = {}
        total_w = sum(self.MOMENTUM_WEIGHTS)
        for ticker in prices.columns:
            p = prices[ticker].dropna()
            if len(p) < 12 * 21:
                continue
            score = 0.0
            for months, w in zip(self.MOMENTUM_PERIODS, self.MOMENTUM_WEIGHTS):
                td = months * 21
                if len(p) > td:
                    score += w * ((p.iloc[-1] / p.iloc[-td]) - 1)
            scores[ticker] = score / total_w
        return pd.Series(scores)

    # ── 배분 로직 ──────────────────────────────────────

    def _allocate_offensive(
        self, scores: pd.Series, all_tickers: pd.Index
    ) -> pd.Series:
        """공격 모드: 모멘텀 상위 N 공격 자산 + 최소 방어 비중"""
        weights = pd.Series(0.0, index=all_tickers)

        # 양수 모멘텀 공격 자산만 후보
        off_available = [t for t in OFFENSIVE_TICKERS if t in all_tickers]
        off_scores    = scores.reindex(off_available).dropna()
        off_positive  = off_scores[off_scores > 0].sort_values(ascending=False)

        def_available = [t for t in DEFENSIVE_TICKERS if t in all_tickers]

        if off_positive.empty:
            # 양수 공격 자산 없음 → 방어 모드로 대체
            return self._allocate_defensive(scores, all_tickers)

        top_off   = off_positive.head(self.top_n_offensive).index.tolist()
        off_ratio = self.offensive_ratio
        def_ratio = 1.0 - off_ratio

        # 공격 자산 배분 (균등)
        per_off = off_ratio / len(top_off)
        for t in top_off:
            weights[t] = per_off

        # 방어 자산 배분: 모멘텀 1위
        if def_available:
            def_scores_sorted = scores.reindex(def_available).dropna().sort_values(ascending=False)
            best_def = def_scores_sorted.index[0] if not def_scores_sorted.empty else def_available[0]
            weights[best_def] = def_ratio

        return weights

    def _allocate_defensive(
        self, scores: pd.Series, all_tickers: pd.Index
    ) -> pd.Series:
        """완전 방어 모드: 단기채권/현금 100%"""
        weights = pd.Series(0.0, index=all_tickers)
        def_available = [t for t in DEFENSIVE_TICKERS if t in all_tickers]

        if def_available:
            # 방어 자산 중 모멘텀 1위
            def_s = scores.reindex(def_available).dropna().sort_values(ascending=False)
            best  = def_s.index[0] if not def_s.empty else def_available[0]
            weights[best] = 1.0
        else:
            weights.iloc[0] = 1.0
        return weights

    def _all_cash(self, tickers: pd.Index) -> pd.Series:
        """전액 KOFR(현금) 또는 단기채권"""
        w = pd.Series(0.0, index=tickers)
        # KOFR 우선, 없으면 단기통안채
        for t in ["449170", "157450", "136340"]:
            if t in tickers:
                w[t] = 1.0
                return w
        if len(tickers) > 0:
            w.iloc[0] = 1.0
        return w

    def _param_str(self) -> str:
        return (
            f"top_off={self.top_n_offensive}, "
            f"off_ratio={self.offensive_ratio:.0%}, "
            f"canary_thr={self.canary_threshold}"
        )
