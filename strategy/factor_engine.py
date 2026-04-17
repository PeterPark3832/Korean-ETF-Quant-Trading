"""
Phase 4 팩터 엔진
────────────────────────────────────────────────────────────────
세 가지 독립 모듈로 구성됩니다.

1. MacroFactorAdjuster
   - 채권 ETF 가격 추세로 금리 방향 판별 → 채권 비중 동적 조절
   - USD/KRW 이동평균으로 환율 방향 판별 → 해외 ETF 비중 동적 조절

2. VolatilityTargeter
   - 포트폴리오 실현 변동성 계산
   - 목표 변동성 대비 비율로 전체 투자 비중 스케일 조정
   - 초과분은 현금 ETF(KOFR)에 배분

3. FactorScorer
   - 모멘텀(50%) + 저변동성(30%) + 샤프비율(20%) 복합 점수
   - 자산군 내 ETF 순위 결정에 사용 (단순 가격 모멘텀 대체)
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from loguru import logger


# ── 자산군 분류 상수 ──────────────────────────────────────────

_BOND_ETFS    = ["114820", "148070", "308620", "136340"]
_FOREIGN_ETFS = ["360750", "379800", "195970", "192090", "381170"]
_CASH_ETF     = "449170"


# ══════════════════════════════════════════════════════════════
# 1. 매크로 팩터 조정기
# ══════════════════════════════════════════════════════════════

class MacroFactorAdjuster:
    """
    금리·환율 팩터 기반 비중 동적 조정

    금리 신호:  채권 ETF 단기 MA > 장기 MA → 금리 하락(채권 우호)
                채권 ETF 단기 MA < 장기 MA → 금리 상승(채권 비중 축소)

    환율 신호:  USD/KRW 단기 MA < 장기 MA → 원화 강세(해외 ETF 유지)
                USD/KRX 단기 MA > 장기 MA → 원화 약세(해외 ETF 비중 축소)

    Args:
        ma_short:         단기 이동평균 기간 (기본 20일)
        ma_long:          장기 이동평균 기간 (기본 60일)
        adjust_strength:  비중 조정 강도 (기본 25%, 0~1)
    """

    def __init__(
        self,
        ma_short:         int   = 20,
        ma_long:          int   = 60,
        adjust_strength:  float = 0.25,
    ):
        self.ma_short        = ma_short
        self.ma_long         = ma_long
        self.adjust_strength = adjust_strength
        self._fx_cache: tuple[date, int] | None = None   # (조회일, signal)

    def adjust(self, weights: pd.Series, prices: pd.DataFrame) -> pd.Series:
        """비중을 매크로 팩터 기반으로 조정하여 반환"""
        w         = weights.copy()
        cash_gain = 0.0

        # ── 금리 방향 조정 ────────────────────────────────
        bond_signal = self._bond_signal(prices)
        if bond_signal < 0:                             # 금리 상승 → 채권 비중 축소
            for t in _BOND_ETFS:
                if t in w.index and w[t] > 0:
                    cut = w[t] * self.adjust_strength
                    w[t]     -= cut
                    cash_gain += cut
            logger.info(
                f"[MacroAdj] 금리 상승 감지 → 채권 비중 -{self.adjust_strength*100:.0f}%"
            )

        # ── 환율 방향 조정 ────────────────────────────────
        fx_signal = self._fx_signal()
        if fx_signal < 0:                               # 원화 약세 → 해외 ETF 비중 축소
            for t in _FOREIGN_ETFS:
                if t in w.index and w[t] > 0:
                    cut = w[t] * self.adjust_strength
                    w[t]     -= cut
                    cash_gain += cut
            logger.info(
                f"[MacroAdj] 원화 약세 감지 → 해외 ETF 비중 -{self.adjust_strength*100:.0f}%"
            )

        # ── 축소분 현금 ETF에 추가 ────────────────────────
        if cash_gain > 0.001 and _CASH_ETF in w.index:
            w[_CASH_ETF] = w.get(_CASH_ETF, 0.0) + cash_gain

        total = w.sum()
        return w / total if total > 0 else w

    # ── 내부 신호 ──────────────────────────────────────────

    def _bond_signal(self, prices: pd.DataFrame) -> int:
        """채권 ETF 가격 추세 → 금리 방향 (+1=하락 / -1=상승)"""
        for ticker in _BOND_ETFS:
            if ticker not in prices.columns:
                continue
            s = prices[ticker].dropna()
            if len(s) < self.ma_long:
                continue
            ma_s = s.rolling(self.ma_short).mean().iloc[-1]
            ma_l = s.rolling(self.ma_long).mean().iloc[-1]
            sig  = 1 if ma_s > ma_l else -1
            logger.debug(
                f"[MacroAdj] 채권신호({ticker}) "
                f"MA{self.ma_short}={ma_s:.1f} vs MA{self.ma_long}={ma_l:.1f} "
                f"→ {'금리하락' if sig > 0 else '금리상승'}"
            )
            return sig
        return 1   # 데이터 부족 시 중립

    def _fx_signal(self) -> int:
        """USD/KRW 추세 → 원화 강약 (+1=강세 / -1=약세), 당일 캐시"""
        today = date.today()
        if self._fx_cache and self._fx_cache[0] == today:
            return self._fx_cache[1]

        try:
            import FinanceDataReader as fdr
            end   = today.strftime("%Y-%m-%d")
            start = (today - timedelta(days=180)).strftime("%Y-%m-%d")
            usdkrw = fdr.DataReader("USD/KRW", start, end)["Close"].dropna()
            if len(usdkrw) < self.ma_long:
                return 1
            ma_s = usdkrw.rolling(self.ma_short).mean().iloc[-1]
            ma_l = usdkrw.rolling(self.ma_long).mean().iloc[-1]
            sig  = -1 if ma_s > ma_l else 1   # 달러 강세 = 원화 약세
            logger.info(
                f"[MacroAdj] USD/KRW "
                f"MA{self.ma_short}={ma_s:.1f} vs MA{self.ma_long}={ma_l:.1f} "
                f"→ {'원화약세' if sig < 0 else '원화강세'}"
            )
            self._fx_cache = (today, sig)
            return sig
        except Exception as e:
            logger.warning(f"[MacroAdj] USD/KRW 조회 실패 → 중립: {e}")
            return 1


# ══════════════════════════════════════════════════════════════
# 2. 변동성 타겟터
# ══════════════════════════════════════════════════════════════

class VolatilityTargeter:
    """
    동적 변동성 타겟팅

    포트폴리오 실현 변동성(연환산)을 계산하여 목표치 대비 스케일 조정.
    스케일 < 1 이면 투자 비중 축소 → 초과분을 현금 ETF에 배분.
    레버리지 없음 (max_scale = 1.0).

    Args:
        target_vol:  목표 연 변동성 (기본 10%)
        vol_window:  실현 변동성 계산 기간 (기본 60 거래일)
        min_scale:   최소 투자 배율 (기본 0.5 = 최대 50% 현금화)
        max_scale:   최대 투자 배율 (기본 1.0 = 레버리지 없음)
        dead_band:   조정 최소 임계값 (기본 0.05 = 5% 이내 무시)
    """

    def __init__(
        self,
        target_vol: float = 0.10,
        vol_window: int   = 60,
        min_scale:  float = 0.50,
        max_scale:  float = 1.00,
        dead_band:  float = 0.05,
    ):
        self.target_vol = target_vol
        self.vol_window = vol_window
        self.min_scale  = min_scale
        self.max_scale  = max_scale
        self.dead_band  = dead_band

    def target(self, weights: pd.Series, prices: pd.DataFrame) -> pd.Series:
        """실현 변동성 기반으로 비중 스케일 조정"""
        realized = self._portfolio_vol(weights, prices)
        if realized <= 0:
            return weights

        raw_scale = self.target_vol / realized
        scale     = float(np.clip(raw_scale, self.min_scale, self.max_scale))

        logger.info(
            f"[VolTarget] 실현변동성={realized*100:.1f}% | "
            f"목표={self.target_vol*100:.1f}% | 스케일={scale:.2f}"
        )

        if abs(scale - 1.0) < self.dead_band:
            return weights                    # 변동 미미 → 그대로

        w        = weights.copy() * scale
        leftover = max(0.0, 1.0 - w.sum())

        if leftover > 0.01 and _CASH_ETF in w.index:
            w[_CASH_ETF] = w.get(_CASH_ETF, 0.0) + leftover

        total = w.sum()
        return w / total if total > 0 else w

    def _portfolio_vol(self, weights: pd.Series, prices: pd.DataFrame) -> float:
        """포트폴리오 실현 변동성 (연환산) 계산"""
        tickers = [
            t for t in weights.index
            if t in prices.columns and weights[t] > 0.01
        ]
        if not tickers:
            return 0.0

        sub = prices[tickers].tail(self.vol_window + 1).dropna()
        if len(sub) < 10:
            return 0.0

        rets = sub.pct_change().dropna()
        w    = weights[tickers] / weights[tickers].sum()

        try:
            cov      = rets.cov() * 252
            port_var = float(w.values @ cov.values @ w.values)
            return port_var ** 0.5 if port_var > 0 else 0.0
        except Exception:
            return 0.0


# ══════════════════════════════════════════════════════════════
# 3. 복합 팩터 스코어러
# ══════════════════════════════════════════════════════════════

class FactorScorer:
    """
    복합 팩터 스코어링

    단순 가격 모멘텀 대신 3가지 팩터의 Z-스코어 가중 합산으로
    자산군 내 ETF 순위를 결정합니다.

        score = 0.5 × 모멘텀_Z + 0.3 × 저변동성_Z + 0.2 × 샤프비율_Z

    Args:
        momentum_window:   모멘텀 계산 기간 (기본 252일 ≈ 1년)
        momentum_skip:     최근 반전 효과 제거 기간 (기본 21일 ≈ 1개월)
        vol_window:        변동성/샤프 계산 기간 (기본 60일)
        w_momentum:        모멘텀 가중치
        w_low_vol:         저변동성 가중치
        w_sharpe:          샤프비율 가중치
    """

    def __init__(
        self,
        momentum_window: int   = 252,
        momentum_skip:   int   = 21,
        vol_window:      int   = 60,
        w_momentum:      float = 0.50,
        w_low_vol:       float = 0.30,
        w_sharpe:        float = 0.20,
    ):
        self.momentum_window = momentum_window
        self.momentum_skip   = momentum_skip
        self.vol_window      = vol_window
        self.w_momentum      = w_momentum
        self.w_low_vol       = w_low_vol
        self.w_sharpe        = w_sharpe

    def score(self, prices: pd.DataFrame) -> pd.Series:
        """
        각 ETF의 복합 팩터 점수를 반환 (높을수록 선호)

        Returns:
            ticker → composite score (Z-스코어 기반, 부호 있음)
        """
        min_len = self.momentum_window + self.momentum_skip
        if len(prices) < min_len:
            return pd.Series(0.0, index=prices.columns)

        # ── 모멘텀 ────────────────────────────────────────
        end_idx   = len(prices) - self.momentum_skip - 1
        start_idx = end_idx - self.momentum_window
        if start_idx >= 0:
            momentum = prices.iloc[end_idx] / prices.iloc[start_idx] - 1
        else:
            momentum = pd.Series(0.0, index=prices.columns)

        # ── 저변동성 (역수) ───────────────────────────────
        recent  = prices.tail(self.vol_window + 1).pct_change().dropna()
        vol     = recent.std() * (252 ** 0.5)
        low_vol = 1.0 / (vol + 1e-8)

        # ── 샤프비율 ──────────────────────────────────────
        rf_daily = 0.025 / 252
        excess   = recent - rf_daily
        sharpe   = excess.mean() / (excess.std() + 1e-8) * (252 ** 0.5)

        # ── Z-스코어 정규화 후 가중 합산 ─────────────────
        def _z(s: pd.Series) -> pd.Series:
            std = s.std()
            return (s - s.mean()) / std if std > 0 else pd.Series(0.0, index=s.index)

        composite = (
            self.w_momentum * _z(momentum) +
            self.w_low_vol  * _z(low_vol)  +
            self.w_sharpe   * _z(sharpe)
        )
        return composite.fillna(0.0)
