"""
백테스트 엔진
- 월별 리밸런싱 기반 포트폴리오 시뮬레이션
- 수수료 / 슬리피지 반영
- 거래 로그 및 포트폴리오 히스토리 기록
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from loguru import logger

from config import (
    INITIAL_CAPITAL,
    TRANSACTION_COST,
    SLIPPAGE,
    REBALANCE_FREQUENCY,
)
from backtest.metrics import calculate_metrics, PerformanceMetrics


@dataclass
class BacktestResult:
    """백테스트 결과 컨테이너"""
    portfolio_values:  pd.Series            # 일별 포트폴리오 가치
    weights_history:   pd.DataFrame         # 리밸런싱 시점 목표 비중
    holdings_history:  pd.DataFrame         # 일별 보유 비중
    rebalance_log:     pd.DataFrame         # 리밸런싱 거래 기록
    metrics:           PerformanceMetrics   # 최종 성과 지표

    def summary(self) -> str:
        return self.metrics.__str__()


# ─────────────────────────────────────────────────────────────
# 메인 엔진
# ─────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    포트폴리오 백테스트 엔진

    전략 함수 시그니처:
        weights = strategy_fn(prices_window: pd.DataFrame) -> pd.Series
        - prices_window: 기준일 이전까지의 가격 DataFrame
        - 반환: ticker → 비중 (합산=1)

    사용법:
        engine = BacktestEngine(prices)
        result = engine.run(strategy_fn, start="2018-01-01", end="2023-12-31")
    """

    def __init__(
        self,
        prices: pd.DataFrame,
        initial_capital: float = INITIAL_CAPITAL,
        transaction_cost: float = TRANSACTION_COST,
        slippage: float = SLIPPAGE,
        rebalance_frequency: str = REBALANCE_FREQUENCY,
    ):
        self.prices = prices.sort_index().ffill().bfill()
        self.initial_capital   = initial_capital
        self.transaction_cost  = transaction_cost
        self.slippage          = slippage
        self.rebalance_freq    = rebalance_frequency

    def run(
        self,
        strategy_fn: Callable[[pd.DataFrame], pd.Series],
        start: str,
        end: str,
    ) -> BacktestResult:
        """
        백테스트 실행

        Args:
            strategy_fn: 비중 결정 함수 (prices_window → weights Series)
            start: 백테스트 시작일
            end:   백테스트 종료일
        """
        prices = self.prices.loc[start:end]
        if prices.empty:
            raise ValueError(f"가격 데이터가 없습니다: {start}~{end}")

        rebalance_dates = self._get_rebalance_dates(prices.index)
        logger.info(
            f"백테스트 시작: {start}~{end} | "
            f"리밸런싱 {len(rebalance_dates)}회 | "
            f"종목 {len(prices.columns)}개"
        )

        # ── 상태 초기화 ──────────────────────────────
        cash       = self.initial_capital
        holdings   = pd.Series(0.0, index=prices.columns)  # 주당 수량
        port_vals:   list[tuple] = []
        weights_log: list[tuple] = []
        rebal_log:   list[dict]  = []

        current_weights = pd.Series(0.0, index=prices.columns)

        for date, row in prices.iterrows():
            price_today = row

            # ── 포트폴리오 가치 계산 ─────────────────
            equity   = (holdings * price_today).sum()
            port_val = equity + cash
            port_vals.append((date, port_val))

            # 현재 비중 계산
            if port_val > 0:
                current_weights = (holdings * price_today) / port_val
            holdings_log_entry = current_weights.copy()

            # ── 리밸런싱 ─────────────────────────────
            if date in rebalance_dates:
                prices_window = self.prices.loc[:date]

                try:
                    target_weights = strategy_fn(prices_window)
                except Exception as e:
                    logger.warning(f"[{date}] 전략 오류: {e} - 이전 비중 유지")
                    target_weights = current_weights.copy()

                target_weights = self._normalize_weights(target_weights, prices.columns)

                # 거래 실행
                turnover, trade_cost = self._execute_rebalance(
                    holdings, cash, target_weights, price_today, port_val
                )

                # 거래 후 상태 업데이트
                holdings, cash = self._compute_new_holdings(
                    port_val, target_weights, price_today, trade_cost
                )

                weights_log.append((date, target_weights))
                rebal_log.append({
                    "date":       date,
                    "port_value": port_val,
                    "turnover":   turnover,
                    "trade_cost": trade_cost,
                })
                logger.debug(
                    f"[{date.date()}] 리밸런싱 | "
                    f"자산 {port_val:,.0f}원 | "
                    f"회전율 {turnover*100:.1f}% | "
                    f"비용 {trade_cost:,.0f}원"
                )

        # ── 결과 정리 ─────────────────────────────────
        portfolio_values = pd.Series(
            {d: v for d, v in port_vals}, name="portfolio_value"
        )
        portfolio_values.index = pd.to_datetime(portfolio_values.index)

        if weights_log:
            weights_df = pd.DataFrame(
                {d: w for d, w in weights_log}
            ).T
            weights_df.index = pd.to_datetime(weights_df.index)
        else:
            weights_df = pd.DataFrame()

        rebalance_df = pd.DataFrame(rebal_log)
        if not rebalance_df.empty:
            rebalance_df["date"] = pd.to_datetime(rebalance_df["date"])
            rebalance_df = rebalance_df.set_index("date")

        metrics = calculate_metrics(portfolio_values, rebalance_df)

        # holdings_history: 리밸런싱 시점 비중
        holdings_history = weights_df if not weights_df.empty else pd.DataFrame()

        return BacktestResult(
            portfolio_values = portfolio_values,
            weights_history  = weights_df,
            holdings_history = holdings_history,
            rebalance_log    = rebalance_df,
            metrics          = metrics,
        )

    # ── 내부 메서드 ────────────────────────────────────

    def _get_rebalance_dates(self, index: pd.DatetimeIndex) -> set:
        """리밸런싱 날짜 집합"""
        df = pd.DataFrame(index=index)
        df["year"]  = index.year
        df["month"] = index.month
        df["week"]  = index.isocalendar().week.values

        if self.rebalance_freq == "monthly":
            # 매월 첫 거래일
            first_days = df.groupby(["year", "month"]).apply(
                lambda g: g.index[0], include_groups=False
            )
            return set(first_days.values)
        elif self.rebalance_freq == "weekly":
            first_days = df.groupby(["year", "week"]).apply(
                lambda g: g.index[0], include_groups=False
            )
            return set(first_days.values)
        else:
            raise ValueError(f"지원하지 않는 리밸런싱 주기: {self.rebalance_freq}")

    def _normalize_weights(
        self,
        weights: pd.Series,
        all_tickers: pd.Index,
    ) -> pd.Series:
        """비중 정규화 및 유효성 보정"""
        w = weights.reindex(all_tickers).fillna(0.0)
        w = w.clip(lower=0)
        total = w.sum()
        if total > 0:
            w = w / total
        else:
            # 전략이 아무것도 선택 안 하면 현금 대용 ETF에 100%
            w.iloc[0] = 1.0
        return w

    def _execute_rebalance(
        self,
        holdings: pd.Series,
        cash: float,
        target_weights: pd.Series,
        prices: pd.Series,
        port_value: float,
    ) -> tuple[float, float]:
        """
        리밸런싱 회전율 및 거래 비용 계산
        Returns: (turnover, trade_cost)
        """
        current_val    = holdings * prices
        target_val     = target_weights * port_value
        trade_val      = (target_val - current_val).abs()
        turnover       = trade_val.sum() / (2 * port_value) if port_value > 0 else 0
        effective_cost = self.transaction_cost + self.slippage
        trade_cost     = trade_val.sum() * effective_cost
        return turnover, trade_cost

    def _compute_new_holdings(
        self,
        port_value: float,
        target_weights: pd.Series,
        prices: pd.Series,
        trade_cost: float,
    ) -> tuple[pd.Series, float]:
        """거래 비용 차감 후 신규 보유 수량 및 현금 계산"""
        net_value = port_value - trade_cost
        target_val = target_weights * net_value

        # 0 가격 종목 제외
        valid = prices > 0
        new_holdings = pd.Series(0.0, index=prices.index)
        new_holdings[valid] = target_val[valid] / prices[valid]

        # 현금: 현금성 ETF 포함 → 실제 현금은 0에 가깝게 유지
        cash = net_value * (1 - target_weights.sum())
        cash = max(cash, 0)

        return new_holdings, cash
