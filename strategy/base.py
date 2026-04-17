"""
전략 추상 기반 클래스
"""
from __future__ import annotations
from abc import ABC, abstractmethod
import pandas as pd


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
