"""
전략 추상 기반 클래스
"""
from __future__ import annotations
from abc import ABC, abstractmethod

import pandas as pd

from config import ETF_UNIVERSE


class BaseStrategy(ABC):
    """
    모든 전략의 기반 클래스

    하위 클래스는 get_weights()를 구현해야 합니다.
    BacktestEngine에 전달할 때는 .signal_fn 프로퍼티를 사용합니다.
    """

    name: str = "BaseStrategy"

    @abstractmethod
    def get_weights(self, prices: pd.DataFrame) -> pd.Series:
        """
        Args:
            prices: 기준일까지의 ETF 가격 DataFrame (index=date, columns=ticker)
        Returns:
            ticker → 비중 Series (합산=1)
        """
        ...

    @property
    def signal_fn(self):
        """BacktestEngine에 넘길 callable 반환"""
        return self.get_weights

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._param_str()})"

    def _param_str(self) -> str:
        return ""

    # ── 공통 유틸리티 ────────────────────────────────────

    def _all_cash(
        self,
        tickers: pd.Index,
        preferred_order: list[str] | None = None,
    ) -> pd.Series:
        """
        전액 현금성 ETF에 배분하는 Series 반환.

        Args:
            tickers: 전체 티커 인덱스
            preferred_order: 우선 선택할 현금성 티커 목록 (없으면 config CASH 순서)
        """
        weights = pd.Series(0.0, index=tickers)
        cash_order = preferred_order or list(ETF_UNIVERSE.get("CASH", {}).keys())
        for ticker in cash_order:
            if ticker in tickers:
                weights[ticker] = 1.0
                return weights
        # 현금 ETF가 아무것도 없으면 첫 번째 티커
        if len(tickers) > 0:
            weights.iloc[0] = 1.0
        return weights

    @staticmethod
    def normalize_weights(weights: pd.Series) -> pd.Series:
        """비중 합계가 0보다 크면 합계=1로 정규화, 아니면 그대로 반환."""
        total = weights.sum()
        return weights / total if total > 0 else weights
