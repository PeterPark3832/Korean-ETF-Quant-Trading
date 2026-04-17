"""
백테스트 실행 메인 스크립트

실행 방법:
    # 전체 전략 비교 백테스트
    python run_backtest.py

    # 단일 전략 + Walk-Forward
    python run_backtest.py --strategy dual_momentum --walk_forward

    # 강제 데이터 갱신
    python run_backtest.py --refresh
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger
from tabulate import tabulate
import pandas as pd

from config import (
    BACKTEST_START, BACKTEST_END,
    INITIAL_CAPITAL, ETF_UNIVERSE, ALL_ETFS,
)
from data.fetcher import ETFDataFetcher
from backtest.engine import BacktestEngine
from backtest.walk_forward import WalkForwardValidator
from backtest.metrics import calculate_metrics
from strategy import DualMomentumStrategy, VAAStrategy, RiskParityStrategy
from reports.plotter import plot_backtest_result, plot_strategy_comparison


# ── 로거 설정 ──────────────────────────────────────────
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
)
logger.add("logs/backtest_{time}.log", rotation="1 week", level="DEBUG")


def load_data(
    tickers: list[str],
    start: str,
    end: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    logger.info(f"데이터 수집: {len(tickers)}개 종목 ({start}~{end})")
    fetcher = ETFDataFetcher()
    prices  = fetcher.get_prices(tickers, start, end, force_refresh=force_refresh)
    logger.info(
        f"수집 완료: {prices.shape[1]}개 종목 / {len(prices)}거래일 "
        f"(누락: {prices.isna().sum().sum()}개)"
    )
    return prices


def run_all_strategies(
    prices: pd.DataFrame,
    start: str,
    end: str,
) -> dict:
    """3개 전략 일괄 백테스트"""
    strategies = {
        "듀얼 모멘텀":   DualMomentumStrategy(lookback_months=12, skip_months=1),
        "VAA-KR":        VAAStrategy(top_n_offensive=2, offensive_ratio=0.70, canary_threshold=1),
        "리스크 패리티": RiskParityStrategy(vol_window=60, target_vol=0.10, momentum_filter=True),
    }

    engine  = BacktestEngine(prices, initial_capital=INITIAL_CAPITAL)
    results = {}
    metrics_rows = []

    for name, strategy in strategies.items():
        logger.info(f"[{name}] 백테스트 실행...")
        try:
            result = engine.run(strategy.signal_fn, start, end)
            results[name] = result

            m = result.metrics
            metrics_rows.append([
                name,
                f"{m.cagr*100:+.2f}%",
                f"{m.annual_volatility*100:.2f}%",
                f"{m.mdd*100:.2f}%",
                f"{m.mdd_duration_days}일",
                f"{m.sharpe_ratio:.3f}",
                f"{m.sortino_ratio:.3f}",
                f"{m.calmar_ratio:.3f}",
                f"{m.win_rate*100:.1f}%",
            ])

            # 개별 차트 저장
            chart_path = plot_backtest_result(
                result.portfolio_values,
                strategy_name=name,
                weights_history=result.weights_history,
            )
            logger.info(f"  → 차트 저장: {chart_path}")

        except Exception as e:
            logger.error(f"[{name}] 실패: {e}")
            import traceback; traceback.print_exc()

    # 비교 테이블 출력
    headers = [
        "전략", "CAGR", "연변동성", "MDD", "MDD기간",
        "Sharpe", "Sortino", "Calmar", "월간승률"
    ]
    print("\n" + "="*80)
    print("  전략 성과 비교")
    print("="*80)
    print(tabulate(metrics_rows, headers=headers, tablefmt="simple"))

    # 비교 차트 저장
    if len(results) > 1:
        pv_dict = {name: r.portfolio_values for name, r in results.items()}
        comp_path = plot_strategy_comparison(pv_dict)
        logger.info(f"비교 차트 저장: {comp_path}")

    return results


def run_walk_forward(
    prices: pd.DataFrame,
    strategy_name: str,
    start: str,
    end: str,
) -> None:
    """단일 전략 Walk-Forward 검증"""
    strategy_map = {
        "dual_momentum": DualMomentumStrategy(),
        "vaa":           VAAStrategy(top_n_offensive=2, offensive_ratio=0.70, canary_threshold=1),
        "risk_parity":   RiskParityStrategy(vol_window=60, target_vol=0.10, momentum_filter=True),
    }

    if strategy_name not in strategy_map:
        logger.error(f"알 수 없는 전략: {strategy_name}. 선택: {list(strategy_map.keys())}")
        return

    strategy  = strategy_map[strategy_name]
    validator = WalkForwardValidator(prices)

    logger.info(f"[{strategy}] Walk-Forward 검증 시작...")
    result = validator.run(strategy.signal_fn, start, end)
    print(result.summary_table())

    # OOS 차트 저장
    chart_path = plot_backtest_result(
        result.combined_oos,
        strategy_name=f"{strategy_name}_WF_OOS",
    )
    logger.info(f"WF 결과 차트: {chart_path}")


def main():
    parser = argparse.ArgumentParser(description="ETF 퀀트봇 백테스트")
    parser.add_argument("--strategy",     default="all",
                        help="전략: all | dual_momentum | vaa | risk_parity")
    parser.add_argument("--walk_forward", action="store_true",
                        help="Walk-Forward 검증 실행")
    parser.add_argument("--start",        default=BACKTEST_START)
    parser.add_argument("--end",          default=BACKTEST_END)
    parser.add_argument("--refresh",      action="store_true",
                        help="캐시 무시하고 데이터 재수집")
    args = parser.parse_args()

    # 로그 디렉토리
    Path("logs").mkdir(exist_ok=True)

    # 데이터 수집
    tickers = list(ALL_ETFS.keys())
    try:
        prices = load_data(tickers, args.start, args.end, args.refresh)
    except Exception as e:
        logger.error(f"데이터 수집 실패: {e}")
        logger.info("pykrx/FinanceDataReader 설치 확인: pip install pykrx finance-datareader")
        sys.exit(1)

    # 백테스트 실행
    if args.strategy == "all":
        run_all_strategies(prices, args.start, args.end)
    else:
        if args.walk_forward:
            run_walk_forward(prices, args.strategy, args.start, args.end)
        else:
            strategy_map = {
                "dual_momentum": DualMomentumStrategy(),
                "vaa":           VAAStrategy(top_n_offensive=2, offensive_ratio=0.70, canary_threshold=1),
                "risk_parity":   RiskParityStrategy(vol_window=60, target_vol=0.10, momentum_filter=True),
            }
            if args.strategy not in strategy_map:
                logger.error(f"알 수 없는 전략: {args.strategy}")
                sys.exit(1)

            strategy = strategy_map[args.strategy]
            engine   = BacktestEngine(prices, initial_capital=INITIAL_CAPITAL)
            result   = engine.run(strategy.signal_fn, args.start, args.end)
            print(result.metrics)

            chart_path = plot_backtest_result(
                result.portfolio_values,
                strategy_name=str(strategy),
                weights_history=result.weights_history,
            )
            logger.info(f"차트 저장: {chart_path}")


if __name__ == "__main__":
    main()
