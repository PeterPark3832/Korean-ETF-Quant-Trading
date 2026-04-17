from .base import BaseStrategy
from .dual_momentum import DualMomentumStrategy
from .vaa import VAAStrategy
from .risk_parity import RiskParityStrategy
from .multi_strategy import MultiStrategyPortfolio, MarketRegimeDetector

ALL_STRATEGIES = {
    "dual_momentum": DualMomentumStrategy,
    "vaa":           VAAStrategy,
    "risk_parity":   RiskParityStrategy,
    "multi":         MultiStrategyPortfolio,
}

__all__ = [
    "BaseStrategy",
    "DualMomentumStrategy",
    "VAAStrategy",
    "RiskParityStrategy",
    "MultiStrategyPortfolio",
    "MarketRegimeDetector",
    "ALL_STRATEGIES",
]
