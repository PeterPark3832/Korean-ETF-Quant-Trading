"""
멀티 전략 포트폴리오 + 시장 국면 감지
────────────────────────────────────────────────────────────────
DualMomentum + VAA + RiskParity 세 전략을 시장 국면에 따라 동적으로 배합합니다.

시장 국면 감지:
  - 강세: S&P500 ETF(360750) 현재가 > 200일 이동평균  → 공격적 배분
  - 약세: S&P500 ETF(360750) 현재가 ≤ 200일 이동평균 → 방어적 배분

강세장 배합 (DM 중심):
  DualMomentum 50% + RiskParity 30% + VAA 20%

약세장 배합 (VAA 중심):
  VAA 60% + DualMomentum 25% + RiskParity 15%
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from loguru import logger

from strategy.base import BaseStrategy
from strategy.dual_momentum import DualMomentumStrategy
from strategy.vaa import VAAStrategy
from strategy.risk_parity import RiskParityStrategy


class MarketRegimeDetector:
    """
    S&P500 ETF 200일 이동평균 기반 시장 국면 감지

    Args:
        sp500_ticker: S&P500 추종 ETF 코드 (기본: 360750 TIGER 미국S&P500)
        ma_window:    이동평균 기간 (기본: 200일)
    """

    def __init__(self, sp500_ticker: str = "360750", ma_window: int = 200):
        self.sp500_ticker = sp500_ticker
        self.ma_window    = ma_window

    def detect(self, prices: pd.DataFrame) -> str:
        """
        Returns:
            "bull" | "bear" | "unknown"
        """
        if self.sp500_ticker not in prices.columns:
            logger.warning(
                f"[RegimeDetector] {self.sp500_ticker} 없음 → 강세장으로 가정"
            )
            return "bull"

        series = prices[self.sp500_ticker].dropna()
        if len(series) < self.ma_window:
            logger.warning(
                f"[RegimeDetector] 데이터 부족({len(series)}일 < {self.ma_window}일) → 강세장으로 가정"
            )
            return "bull"

        current_price = series.iloc[-1]
        ma200         = series.rolling(self.ma_window).mean().iloc[-1]

        regime = "bull" if current_price > ma200 else "bear"
        gap_pct = (current_price / ma200 - 1) * 100
        logger.info(
            f"[RegimeDetector] {self.sp500_ticker} "
            f"현재가={current_price:,.0f} | MA{self.ma_window}={ma200:,.0f} | "
            f"괴리={gap_pct:+.1f}% → 국면={regime.upper()}"
        )
        return regime


class MultiStrategyPortfolio(BaseStrategy):
    """
    멀티 전략 포트폴리오

    Args:
        bull_weights: 강세장 전략 배합 dict {전략명: 비중}
        bear_weights: 약세장 전략 배합 dict {전략명: 비중}
        dm_kwargs:    DualMomentumStrategy 파라미터
        vaa_kwargs:   VAAStrategy 파라미터
        rp_kwargs:    RiskParityStrategy 파라미터
    """

    name = "MultiStrategy"

    # 기본 배합 비중
    _DEFAULT_BULL = {"dual_momentum": 0.50, "risk_parity": 0.30, "vaa": 0.20}
    _DEFAULT_BEAR = {"vaa": 0.60, "dual_momentum": 0.25, "risk_parity": 0.15}

    def __init__(
        self,
        bull_weights: dict[str, float] | None = None,
        bear_weights: dict[str, float] | None = None,
        dm_kwargs:    dict | None = None,
        vaa_kwargs:   dict | None = None,
        rp_kwargs:    dict | None = None,
        sp500_ticker: str = "360750",
        ma_window:    int = 200,
    ):
        self.bull_weights = bull_weights or self._DEFAULT_BULL
        self.bear_weights = bear_weights or self._DEFAULT_BEAR

        self.strategies: dict[str, BaseStrategy] = {
            "dual_momentum": DualMomentumStrategy(**(dm_kwargs  or {})),
            "vaa":           VAAStrategy(**(vaa_kwargs           or {})),
            "risk_parity":   RiskParityStrategy(**(rp_kwargs     or {})),
        }
        self.regime_detector = MarketRegimeDetector(sp500_ticker, ma_window)

    def get_weights(self, prices: pd.DataFrame) -> pd.Series:
        regime       = self.regime_detector.detect(prices)
        mix_weights  = self.bull_weights if regime == "bull" else self.bear_weights

        logger.info(
            f"[MultiStrategy] 국면={regime.upper()} | "
            f"배합={mix_weights}"
        )

        combined = pd.Series(0.0, index=prices.columns)

        for strategy_name, mix_w in mix_weights.items():
            if mix_w <= 0:
                continue
            strategy = self.strategies[strategy_name]
            try:
                w = strategy.get_weights(prices)
                # 인덱스 정렬 (전략마다 반환 컬럼이 다를 수 있음)
                w = w.reindex(prices.columns).fillna(0.0)
                combined = combined + w * mix_w
                logger.debug(
                    f"  [{strategy_name}] 기여 비중 {mix_w*100:.0f}%: "
                    + ", ".join(
                        f"{t}={v*mix_w*100:.1f}%"
                        for t, v in w[w > 0.01].sort_values(ascending=False).items()
                    )
                )
            except Exception as e:
                logger.warning(f"[MultiStrategy] {strategy_name} 오류, 스킵: {e}")

        # 합산 정규화
        total = combined.sum()
        if total > 0:
            combined = combined / total

        top_holdings = combined[combined > 0.01].sort_values(ascending=False)
        logger.info(
            "[MultiStrategy] 최종 목표 비중: "
            + " | ".join(f"{t}={v*100:.1f}%" for t, v in top_holdings.items())
        )
        return combined

    def _param_str(self) -> str:
        return f"bull={self.bull_weights}, bear={self.bear_weights}"
