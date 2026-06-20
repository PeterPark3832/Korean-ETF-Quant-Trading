"""
KR GEM (한국·미국 멀티에셋 모멘텀) 전략
────────────────────────────────────────────────────────────────
SeedNGrow(strategies/kr_momentum.py::KRGemStrategy) 포팅 — 동일한 GTAA형 듀얼 모멘텀
메커니즘을 이 봇의 ETF 유니버스(config.ETF_UNIVERSE, 국내 상장 ETF 코드)에 맞춰 구현.

규칙:
  1. 위험자산 5종(KOSPI200·미국S&P500·나스닥100·금·반도체)의 블렌드 모멘텀(3·6·12개월 평균) 계산
  2. 모멘텀 상위 TOP_N(3)개를 동일비중으로 편입 (상대 모멘텀)
  3. 각 슬롯의 모멘텀이 현금성 ETF(단기채권) 모멘텀보다 낮으면(절대 모멘텀 미달) 그 슬롯은
     안전자산(국고채 3년)으로 대체 → 하락장에서 채권으로 도피
  4. 월간 리밸런싱
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from strategy.base import BaseStrategy

# 모멘텀 룩백(거래일): 약 3·6·12개월 — 셋의 단순 평균으로 신호를 매끄럽게 한다.
_LOOKBACKS = (63, 126, 252)

_NAMES = {
    "069500": "KODEX 200 (KOSPI200)",
    "360750": "TIGER 미국S&P500",
    "379800": "KODEX 미국나스닥100TR",
    "132030": "KODEX 골드선물(H)",
    "091160": "KODEX 반도체",
    "114820": "KODEX 국고채3년 (안전자산)",
    "136340": "KODEX 단기채권PLUS (현금성)",
}


def _blended_momentum(close: pd.Series | None) -> float | None:
    """3·6·12개월 누적수익률의 평균. 데이터가 한 구간도 안 되면 None."""
    if close is None or len(close) == 0:
        return None
    close = close.dropna()
    if len(close) == 0:
        return None
    rets = [
        float(close.iloc[-1] / close.iloc[-d] - 1)
        for d in _LOOKBACKS
        if len(close) > d
    ]
    return sum(rets) / len(rets) if rets else None


class KRGemStrategy(BaseStrategy):
    """
    KR GEM — 한국·미국 멀티에셋 모멘텀 (월간)

    Args:
        top_n: 위험자산 중 동일비중 편입 개수 (기본 3)
    """

    name = "KRGem"

    RISK_ASSETS = ["069500", "360750", "379800", "132030", "091160"]
    SAFE_ASSET  = "114820"   # 절대 모멘텀 미달 슬롯이 도피하는 채권
    CASH_PROXY  = "136340"   # 절대 모멘텀 기준(현금 수익률)
    NAMES       = _NAMES

    def __init__(self, top_n: int = 3):
        self.top_n = top_n

    def get_weights(self, prices: pd.DataFrame) -> pd.Series:
        weights = pd.Series(0.0, index=prices.columns)

        if self.SAFE_ASSET not in prices.columns:
            logger.warning(f"[KRGem] 안전자산({self.SAFE_ASSET}) 가격 없음 → 전액 안전자산 불가, 첫 종목 현금화")
            if len(prices.columns):
                weights.iloc[0] = 1.0
            return weights

        cash_mom = _blended_momentum(prices.get(self.CASH_PROXY)) or 0.0
        ranked = [
            (tk, m) for tk in self.RISK_ASSETS
            if tk in prices.columns and (m := _blended_momentum(prices[tk])) is not None
        ]

        if not ranked:
            logger.warning("[KRGem] 위험자산 모멘텀 계산 불가(데이터 부족) → 전액 안전자산")
            weights[self.SAFE_ASSET] = 1.0
            return weights

        ranked.sort(key=lambda x: x[1], reverse=True)
        top = ranked[: self.top_n]

        n = len(top)
        slot = 1.0 / n
        for tk, mom in top:
            dest = tk if mom > cash_mom else self.SAFE_ASSET
            weights[dest] += slot

        logger.info(
            "[KRGem] 모멘텀 랭킹: "
            + ", ".join(f"{self.NAMES.get(tk, tk)}={m*100:+.1f}%" for tk, m in ranked)
            + f" | 현금성 모멘텀={cash_mom*100:+.1f}%"
        )

        total = weights.sum()
        if total > 0:
            weights = weights / total
        else:
            weights[self.SAFE_ASSET] = 1.0

        return weights

    def _param_str(self) -> str:
        return f"top_n={self.top_n}"
