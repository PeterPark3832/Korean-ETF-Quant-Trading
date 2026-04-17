from .base import BaseStrategy
from .dual_momentum import DualMomentumStrategy
from .vaa import VAAStrategy
from .risk_parity import RiskParityStrategy
from .multi_strategy import MultiStrategyPortfolio, MarketRegimeDetector
from .factor_momentum import FactorMomentumStrategy
from .factor_engine import MacroFactorAdjuster, VolatilityTargeter, FactorScorer

ALL_STRATEGIES = {
    "dual_momentum":   DualMomentumStrategy,
    "vaa":             VAAStrategy,
    "risk_parity":     RiskParityStrategy,
    "multi":           MultiStrategyPortfolio,
    "factor_momentum": FactorMomentumStrategy,
}

__all__ = [
    "BaseStrategy",
    "DualMomentumStrategy",
    "VAAStrategy",
    "RiskParityStrategy",
    "MultiStrategyPortfolio",
    "MarketRegimeDetector",
    "FactorMomentumStrategy",
    "MacroFactorAdjuster",
    "VolatilityTargeter",
    "FactorScorer",
    "ALL_STRATEGIES",
]
