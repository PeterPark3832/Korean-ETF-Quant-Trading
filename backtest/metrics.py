"""
포트폴리오 성과 지표 계산 모듈
- CAGR, MDD, Sharpe, Sortino, Calmar, 승률 등
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field


@dataclass
class PerformanceMetrics:
    """백테스트 결과 지표 컨테이너"""
    # 수익률
    total_return: float = 0.0
    cagr: float = 0.0
    annual_volatility: float = 0.0

    # 리스크
    mdd: float = 0.0                # Maximum Drawdown (음수)
    mdd_duration_days: int = 0      # MDD 지속 기간

    # 위험조정 수익률
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # 거래 통계
    win_rate: float = 0.0
    rebalance_count: int = 0
    avg_turnover: float = 0.0       # 리밸런싱당 평균 회전율

    # 기간
    start_date: str = ""
    end_date: str = ""
    trading_days: int = 0

    def __str__(self) -> str:
        return (
            f"{'='*50}\n"
            f"  기간: {self.start_date} ~ {self.end_date} ({self.trading_days}일)\n"
            f"{'─'*50}\n"
            f"  총 수익률:      {self.total_return*100:+.2f}%\n"
            f"  CAGR:           {self.cagr*100:+.2f}%\n"
            f"  연 변동성:      {self.annual_volatility*100:.2f}%\n"
            f"  MDD:            {self.mdd*100:.2f}%\n"
            f"  MDD 기간:       {self.mdd_duration_days}일\n"
            f"{'─'*50}\n"
            f"  샤프 비율:      {self.sharpe_ratio:.3f}\n"
            f"  소르티노 비율:  {self.sortino_ratio:.3f}\n"
            f"  칼마 비율:      {self.calmar_ratio:.3f}\n"
            f"{'─'*50}\n"
            f"  리밸런싱 횟수:  {self.rebalance_count}회\n"
            f"  평균 회전율:    {self.avg_turnover*100:.1f}%\n"
            f"{'='*50}"
        )

    def to_dict(self) -> dict:
        return {
            "total_return":      self.total_return,
            "cagr":              self.cagr,
            "annual_volatility": self.annual_volatility,
            "mdd":               self.mdd,
            "mdd_duration_days": self.mdd_duration_days,
            "sharpe_ratio":      self.sharpe_ratio,
            "sortino_ratio":     self.sortino_ratio,
            "calmar_ratio":      self.calmar_ratio,
            "win_rate":          self.win_rate,
            "rebalance_count":   self.rebalance_count,
            "avg_turnover":      self.avg_turnover,
        }


def calculate_metrics(
    portfolio_values: pd.Series,
    rebalance_log: pd.DataFrame | None = None,
    risk_free_rate: float = 0.035,   # 한국 무위험 이자율 (3.5%)
) -> PerformanceMetrics:
    """
    포트폴리오 가치 시계열로 성과 지표 계산

    Args:
        portfolio_values: DatetimeIndex가 있는 포트폴리오 가치 Series
        rebalance_log: 리밸런싱 기록 DataFrame (optional)
        risk_free_rate: 연간 무위험 이자율
    """
    pv = portfolio_values.dropna()
    if len(pv) < 2:
        return PerformanceMetrics()

    returns = pv.pct_change().dropna()
    n_days  = len(pv)
    n_years = n_days / 252

    # ── 수익률 ──────────────────────────────────────
    total_return = (pv.iloc[-1] / pv.iloc[0]) - 1
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
    annual_vol = returns.std() * np.sqrt(252)

    # ── MDD ─────────────────────────────────────────
    mdd, mdd_duration = _calculate_mdd(pv)

    # ── 샤프 비율 ────────────────────────────────────
    daily_rf = (1 + risk_free_rate) ** (1 / 252) - 1
    excess_ret = returns - daily_rf
    sharpe = (excess_ret.mean() / returns.std() * np.sqrt(252)
              if returns.std() > 0 else 0.0)

    # ── 소르티노 비율 ────────────────────────────────
    downside_returns = returns[returns < daily_rf] - daily_rf
    downside_std = np.sqrt((downside_returns ** 2).mean()) * np.sqrt(252)
    sortino = ((cagr - risk_free_rate) / downside_std
               if downside_std > 0 else 0.0)

    # ── 칼마 비율 ────────────────────────────────────
    calmar = (cagr / abs(mdd)) if mdd != 0 else 0.0

    # ── 승률 ─────────────────────────────────────────
    monthly_ret = pv.resample("ME").last().pct_change().dropna()
    win_rate = (monthly_ret > 0).sum() / len(monthly_ret) if len(monthly_ret) > 0 else 0

    # ── 리밸런싱 통계 ────────────────────────────────
    rebalance_count = 0
    avg_turnover    = 0.0
    if rebalance_log is not None and not rebalance_log.empty:
        rebalance_count = len(rebalance_log)
        if "turnover" in rebalance_log.columns:
            avg_turnover = rebalance_log["turnover"].mean()

    return PerformanceMetrics(
        total_return       = total_return,
        cagr               = cagr,
        annual_volatility  = annual_vol,
        mdd                = mdd,
        mdd_duration_days  = mdd_duration,
        sharpe_ratio       = sharpe,
        sortino_ratio      = sortino,
        calmar_ratio       = calmar,
        win_rate           = win_rate,
        rebalance_count    = rebalance_count,
        avg_turnover       = avg_turnover,
        start_date         = str(pv.index[0].date()),
        end_date           = str(pv.index[-1].date()),
        trading_days       = n_days,
    )


def _calculate_mdd(portfolio_values: pd.Series) -> tuple[float, int]:
    """(MDD 비율, MDD 지속 거래일 수) 반환. MDD는 음수."""
    cummax = portfolio_values.cummax()
    drawdown = (portfolio_values - cummax) / cummax

    mdd = drawdown.min()

    # MDD 지속 기간: 고점 대비 하락 구간 최대 길이
    in_drawdown = drawdown < 0
    max_duration = 0
    current_duration = 0
    for flag in in_drawdown:
        if flag:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0

    return mdd, max_duration


def rolling_metrics(
    portfolio_values: pd.Series,
    window: int = 252,
) -> pd.DataFrame:
    """롤링 윈도우 지표 (연간 기준)"""
    returns = portfolio_values.pct_change().dropna()
    roll    = returns.rolling(window)

    df = pd.DataFrame(index=returns.index)
    df["rolling_return"]     = roll.apply(lambda r: (1 + r).prod() - 1)
    df["rolling_volatility"] = roll.std() * np.sqrt(252)
    df["rolling_sharpe"]     = (roll.mean() / roll.std() * np.sqrt(252)).fillna(0)
    return df
