"""
Walk-Forward 검증 모듈
────────────────────────────────────────────────────────────────
과최적화 방지를 위한 시계열 교차검증

방법:
  1. 전체 기간을 슬라이딩 윈도우로 분할
  2. In-sample(훈련): 파라미터 최적화 / 전략 선택
  3. Out-of-sample(검증): 실제 성과 측정
  4. OOS 성과를 이어붙여 전체 WF 성과 계산

기간 분할 예시 (train=3년, test=1년, step=6개월):
  Window 1: Train [2015-2018], Test [2018-2019]
  Window 2: Train [2015.7-2018.7], Test [2018.7-2019.7]
  ...

WF Efficiency = OOS CAGR / IS CAGR (1에 가까울수록 과최적화 없음)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Callable

import pandas as pd
import numpy as np
from loguru import logger
from tabulate import tabulate

from backtest.engine import BacktestEngine, BacktestResult
from backtest.metrics import calculate_metrics, PerformanceMetrics
from config import (
    WF_TRAIN_YEARS,
    WF_TEST_YEARS,
    WF_STEP_MONTHS,
    INITIAL_CAPITAL,
)


@dataclass
class WFWindow:
    """단일 Walk-Forward 윈도우"""
    index:         int
    train_start:   str
    train_end:     str
    test_start:    str
    test_end:      str
    is_result:     BacktestResult | None = None   # In-sample 결과
    oos_result:    BacktestResult | None = None   # Out-of-sample 결과


@dataclass
class WalkForwardResult:
    """전체 Walk-Forward 분석 결과"""
    windows:           list[WFWindow]
    combined_oos:      pd.Series        # OOS 기간 이어붙인 포트폴리오 가치
    oos_metrics:       PerformanceMetrics
    is_metrics_list:   list[PerformanceMetrics] = field(default_factory=list)
    oos_metrics_list:  list[PerformanceMetrics] = field(default_factory=list)

    @property
    def wf_efficiency(self) -> float:
        """WF 효율성 (OOS CAGR / IS CAGR 평균)"""
        is_cagrs  = [m.cagr for m in self.is_metrics_list  if m.cagr != 0]
        oos_cagrs = [m.cagr for m in self.oos_metrics_list if m.cagr != 0]
        if not is_cagrs or not oos_cagrs:
            return 0.0
        return np.mean(oos_cagrs) / np.mean(is_cagrs)

    def summary_table(self) -> str:
        rows = []
        for i, (w, is_m, oos_m) in enumerate(
            zip(self.windows, self.is_metrics_list, self.oos_metrics_list)
        ):
            rows.append([
                i + 1,
                f"{w.train_start[:7]}~{w.train_end[:7]}",
                f"{w.test_start[:7]}~{w.test_end[:7]}",
                f"{is_m.cagr*100:+.1f}%",
                f"{oos_m.cagr*100:+.1f}%",
                f"{is_m.mdd*100:.1f}%",
                f"{oos_m.mdd*100:.1f}%",
                f"{is_m.sharpe_ratio:.2f}",
                f"{oos_m.sharpe_ratio:.2f}",
            ])

        headers = [
            "윈도우", "훈련기간", "검증기간",
            "IS CAGR", "OOS CAGR",
            "IS MDD",  "OOS MDD",
            "IS Sharpe", "OOS Sharpe",
        ]
        table = tabulate(rows, headers=headers, tablefmt="rounded_outline")

        summary = (
            f"\n{'='*60}\n"
            f"  Walk-Forward 종합 결과\n"
            f"{'='*60}\n"
            f"{table}\n"
            f"{'─'*60}\n"
            f"  OOS 전체 CAGR:    {self.oos_metrics.cagr*100:+.2f}%\n"
            f"  OOS 전체 MDD:     {self.oos_metrics.mdd*100:.2f}%\n"
            f"  OOS Sharpe:       {self.oos_metrics.sharpe_ratio:.3f}\n"
            f"  WF 효율성:        {self.wf_efficiency:.2f}  "
            f"(1.0 = 완벽, <0.5 = 과최적화 의심)\n"
            f"{'='*60}"
        )
        return summary


class WalkForwardValidator:
    """
    Walk-Forward 검증 실행기

    사용법:
        validator = WalkForwardValidator(prices)
        result = validator.run(
            strategy_fn=DualMomentumStrategy().signal_fn,
            start="2015-01-01",
            end="2024-12-31",
        )
        print(result.summary_table())
    """

    def __init__(
        self,
        prices: pd.DataFrame,
        train_years: int   = WF_TRAIN_YEARS,
        test_years: int    = WF_TEST_YEARS,
        step_months: int   = WF_STEP_MONTHS,
        initial_capital: float = INITIAL_CAPITAL,
    ):
        self.prices          = prices.sort_index()
        self.train_years     = train_years
        self.test_years      = test_years
        self.step_months     = step_months
        self.initial_capital = initial_capital

    def run(
        self,
        strategy_fn: Callable[[pd.DataFrame], pd.Series],
        start: str,
        end: str,
    ) -> WalkForwardResult:
        windows = self._create_windows(start, end)
        if not windows:
            raise ValueError("유효한 Walk-Forward 윈도우가 없습니다. 기간을 늘려주세요.")

        logger.info(
            f"Walk-Forward 시작 | "
            f"윈도우 {len(windows)}개 | "
            f"훈련={self.train_years}년, 검증={self.test_years}년"
        )

        oos_series_list: list[pd.Series] = []
        is_metrics_list:  list[PerformanceMetrics] = []
        oos_metrics_list: list[PerformanceMetrics] = []

        engine = BacktestEngine(self.prices, initial_capital=self.initial_capital)

        for w in windows:
            logger.info(
                f"[윈도우 {w.index}] "
                f"IS: {w.train_start}~{w.train_end} | "
                f"OOS: {w.test_start}~{w.test_end}"
            )

            # IS 백테스트
            try:
                is_result = engine.run(strategy_fn, w.train_start, w.train_end)
                w.is_result = is_result
                is_metrics_list.append(is_result.metrics)
            except Exception as e:
                logger.error(f"IS 백테스트 실패: {e}")
                continue

            # OOS 백테스트 (IS에서 학습한 전략을 그대로 OOS에 적용)
            try:
                oos_result = engine.run(strategy_fn, w.test_start, w.test_end)
                w.oos_result = oos_result
                oos_metrics_list.append(oos_result.metrics)
                oos_series_list.append(oos_result.portfolio_values)
            except Exception as e:
                logger.error(f"OOS 백테스트 실패: {e}")
                continue

        if not oos_series_list:
            raise RuntimeError("모든 윈도우 실패. 데이터 기간을 확인하세요.")

        # OOS 시리즈 이어붙이기 (연속 수익률로 체인)
        combined_oos = self._chain_series(oos_series_list)
        oos_metrics  = calculate_metrics(combined_oos)

        return WalkForwardResult(
            windows          = windows,
            combined_oos     = combined_oos,
            oos_metrics      = oos_metrics,
            is_metrics_list  = is_metrics_list,
            oos_metrics_list = oos_metrics_list,
        )

    def _create_windows(self, start: str, end: str) -> list[WFWindow]:
        """슬라이딩 윈도우 생성"""
        windows  = []
        dt_start = datetime.strptime(start, "%Y-%m-%d")
        dt_end   = datetime.strptime(end,   "%Y-%m-%d")

        idx      = 1
        cursor   = dt_start

        while True:
            train_start = cursor
            train_end   = cursor + relativedelta(years=self.train_years)
            test_start  = train_end
            test_end    = test_start + relativedelta(years=self.test_years)

            if test_end > dt_end:
                break

            windows.append(WFWindow(
                index       = idx,
                train_start = train_start.strftime("%Y-%m-%d"),
                train_end   = train_end.strftime("%Y-%m-%d"),
                test_start  = test_start.strftime("%Y-%m-%d"),
                test_end    = test_end.strftime("%Y-%m-%d"),
            ))
            idx    += 1
            cursor += relativedelta(months=self.step_months)

        return windows

    @staticmethod
    def _chain_series(series_list: list[pd.Series]) -> pd.Series:
        """
        OOS 시리즈 체인 연결
        각 구간을 이전 구간 종료 가치에서 이어 붙임
        """
        if not series_list:
            return pd.Series(dtype=float)

        chained   = series_list[0].copy()
        prev_last = chained.iloc[-1]

        for s in series_list[1:]:
            # 기간이 겹치면 제거
            s = s[s.index > chained.index[-1]]
            if s.empty:
                continue
            # 연결: 이전 종료 가치 기준으로 스케일 조정
            scale = prev_last / s.iloc[0]
            chained = pd.concat([chained, s * scale])
            prev_last = chained.iloc[-1]

        return chained.sort_index()
