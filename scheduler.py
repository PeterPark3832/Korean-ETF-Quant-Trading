"""
APScheduler 자동 매매 스케줄러
────────────────────────────────────────────────────────────────
실행 흐름:
  ┌─────────────────────────────────────┐
  │  매일 09:05  장 시작 리스크 리셋    │
  │  매일 09:10  리스크 상태 점검       │
  │  매월 1영업일 09:30  월간 리밸런싱  │
  │  매일 15:35  장 마감 포트폴리오 집계│
  └─────────────────────────────────────┘

리밸런싱 절차:
  1. 리스크 체크 → 이상 시 중단
  2. 최신 가격 데이터 수집
  3. 전략 신호 계산 (목표 비중)
  4. 리밸런서 실행 (매도 → 매수)
  5. 결과 알림 전송
"""
from __future__ import annotations

import sys
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

KST = ZoneInfo("Asia/Seoul")


# ── 로거 설정 ──────────────────────────────────────────
def setup_logger():
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
        level="INFO",
        colorize=True,
    )
    logger.add(
        "logs/bot_{time:YYYY-MM}.log",
        rotation="1 month",
        retention="6 months",
        level="DEBUG",
        encoding="utf-8",
    )


class ETFQuantBot:
    """
    ETF 퀀트 자동매매 봇

    설정:
        .env 파일의 KIS_MODE에 따라 실전/모의 자동 전환
        config.py의 전략 파라미터로 전략 선택

    사용법:
        bot = ETFQuantBot()
        bot.run()               # 스케줄러 시작 (블로킹)
        bot.rebalance_now()     # 즉시 리밸런싱 (수동 실행)
    """

    def __init__(
        self,
        broker_mode: str  = None,    # None이면 .env KIS_MODE 사용
        strategy_name: str = "dual_momentum",
        dry_run: bool = False,
    ):
        from broker import create_broker
        from strategy import (
            DualMomentumStrategy, VAAStrategy, RiskParityStrategy,
            MultiStrategyPortfolio,
        )
        from risk.guard import RiskGuard
        from notifier import Notifier
        from config import INITIAL_CAPITAL

        self.dry_run       = dry_run
        self.strategy_name = strategy_name

        # 브로커 생성
        kis_mode   = broker_mode or os.getenv("KIS_MODE", "paper")
        self.broker_mode = kis_mode
        if kis_mode in ("real", "paper"):
            # .env에 KIS 키가 있으면 KIS, 없으면 로컬 모의
            app_key = os.getenv("KIS_APP_KEY", "")
            if app_key and app_key != "발급받은_앱키_여기에_입력":
                broker_type = f"kis_{kis_mode}"
            else:
                broker_type = "paper"
                logger.warning("KIS API 키 미설정 → 로컬 모의 브로커 사용")
        else:
            broker_type = kis_mode

        self.broker = create_broker(broker_type,
                                    initial_cash=INITIAL_CAPITAL if broker_type == "paper" else None)

        # 전략 선택
        strategies = {
            "dual_momentum": DualMomentumStrategy(lookback_months=12, skip_months=1),
            "vaa":           VAAStrategy(top_n_offensive=2, offensive_ratio=0.70, canary_threshold=1),
            "risk_parity":   RiskParityStrategy(vol_window=60, target_vol=0.10, momentum_filter=True),
            "multi":         MultiStrategyPortfolio(
                                 dm_kwargs  = {"lookback_months": 12, "skip_months": 1},
                                 vaa_kwargs = {"top_n_offensive": 2, "offensive_ratio": 0.70},
                                 rp_kwargs  = {"vol_window": 60, "target_vol": 0.10, "momentum_filter": True},
                             ),
        }
        if strategy_name not in strategies:
            raise ValueError(f"알 수 없는 전략: {strategy_name}. 선택: {list(strategies.keys())}")
        self.strategy = strategies[strategy_name]

        # 리스크 감시 / 알림
        self.guard    = RiskGuard()
        self.notifier = Notifier()

        # 성과 리포터
        from reports.reporter import PerformanceReporter
        self.reporter = PerformanceReporter(strategy_name)

        logger.info(
            f"ETF 퀀트봇 초기화 | 모드={broker_type.upper()} | "
            f"전략={strategy_name} | DryRun={dry_run}"
        )

    # ── 스케줄 작업 ────────────────────────────────────

    def job_morning_reset(self):
        """09:05 - 장 시작 일간 리스크 리셋"""
        logger.info("=== 장 시작 리스크 리셋 ===")
        try:
            balance = self.broker.get_balance()
            self.guard.reset_daily(balance.total_assets)
            logger.info(f"리스크 리셋 완료: 총자산 {balance.total_assets:,.0f}원")
        except Exception as e:
            logger.error(f"리스크 리셋 실패: {e}")
            self.notifier.send_error(str(e), "장 시작 리셋")

    def job_risk_check(self):
        """09:10 - 리스크 점검"""
        logger.info("=== 리스크 점검 ===")
        try:
            balance = self.broker.get_balance()
            result  = self.guard.check(balance)

            status = self.guard.get_status()
            logger.info(
                f"리스크 상태: MDD={status['current_mdd']*100:.2f}% | "
                f"연속손실={status['consecutive_loss_days']}일 | "
                f"중단={status['is_halted']}"
            )

            if result.action in ("warn", "reduce", "halt"):
                self.notifier.send_risk_alert(result, balance.total_assets)

        except Exception as e:
            logger.error(f"리스크 점검 실패: {e}")
            self.notifier.send_error(str(e), "리스크 점검")

    def job_monthly_rebalance(self):
        """매월 1영업일 09:30 - 월간 리밸런싱"""
        today = date.today()
        logger.info(f"=== 월간 리밸런싱 시작 ({today}) ===")

        try:
            # 1. 리스크 체크
            balance = self.broker.get_balance()
            risk_result = self.guard.check(balance)

            if risk_result.action == "halt":
                logger.error(f"거래 중단 상태 → 리밸런싱 스킵: {risk_result.reason}")
                self.notifier.send_risk_alert(risk_result, balance.total_assets)
                return

            # 2. 최신 가격 데이터 수집
            prices = self._load_latest_prices()
            if prices is None or prices.empty:
                logger.error("가격 데이터 수집 실패 → 리밸런싱 스킵")
                self.notifier.send_error("가격 데이터 수집 실패", "월간 리밸런싱")
                return

            # 3. 포지션 축소 모드: 공격 자산 비중 줄이기
            strategy_fn = self.strategy.get_weights
            if risk_result.action == "reduce":
                reduce_ratio = risk_result.detail.get("reduce_ratio", 0.3)
                strategy_fn  = self._make_reduced_strategy(reduce_ratio)
                logger.warning(f"포지션 축소 모드: {reduce_ratio*100:.0f}% 현금화")

            # 4. 리밸런싱 실행
            from portfolio.rebalancer import PortfolioRebalancer
            rebalancer = PortfolioRebalancer(
                broker              = self.broker,
                strategy_fn         = strategy_fn,
                price_data          = prices,
                rebalance_threshold = 0.03,
                min_order_amount    = 50_000,
                dry_run             = self.dry_run,
            )
            result = rebalancer.run(prices_window=prices)

            # 5. 결과 알림
            self.notifier.send_rebalance_report(result, self.strategy_name)
            logger.info(f"월간 리밸런싱 완료: 성공={result.success_count} 실패={result.fail_count}")

            # 6. 미체결 주문 확인 및 취소 (3분 후)
            if not self.dry_run:
                self._cancel_pending_orders_after(delay_sec=180)

        except Exception as e:
            logger.exception(f"월간 리밸런싱 오류: {e}")
            self.notifier.send_error(str(e), "월간 리밸런싱")

    def job_daily_close(self):
        """15:35 - 장 마감 포트폴리오 집계 + 하트비트 알림"""
        logger.info("=== 장 마감 집계 ===")
        try:
            balance = self.broker.get_balance()
            risk_st = self.guard.get_status()
            pnl_str = f"{balance.total_pnl:+,.0f}원({balance.total_pnl_rate:+.2f}%)"
            logger.info(
                f"마감 포트폴리오: "
                f"총자산={balance.total_assets:,.0f}원 | "
                f"MDD={risk_st['current_mdd']*100:.2f}% | "
                f"손익={pnl_str}"
            )

            # 일간 NAV 기록
            self.reporter.record_daily(balance.total_assets)

            # 일일 하트비트: 봇이 살아있음을 텔레그램으로 확인
            self.notifier.send_daily_report(
                total_assets   = balance.total_assets,
                total_pnl      = balance.total_pnl,
                total_pnl_rate = balance.total_pnl_rate,
                current_mdd    = risk_st["current_mdd"],
                strategy_name  = self.strategy_name,
                is_halted      = risk_st["is_halted"],
            )

            # 월말 마지막 영업일: 월간 성과 리포트 자동 전송
            if self._is_last_business_day():
                logger.info("월말 성과 리포트 전송")
                self.notifier.send_text(self.reporter.monthly_report_text())

        except Exception as e:
            logger.error(f"마감 집계 실패: {e}")

    # ── 수동 실행 ──────────────────────────────────────

    def rebalance_now(self, dry_run: bool = None) -> None:
        """즉시 리밸런싱 (수동 호출용)"""
        _dry = dry_run if dry_run is not None else self.dry_run
        logger.info(f"수동 리밸런싱 시작 (dry_run={_dry})")
        original = self.dry_run
        self.dry_run = _dry
        self.job_monthly_rebalance()
        self.dry_run = original

    def status(self) -> None:
        """현재 포트폴리오 상태 출력"""
        balance = self.broker.get_balance()
        risk_st = self.guard.get_status()
        print(balance)
        print(f"\nMDD: {risk_st['current_mdd']*100:.2f}% | "
              f"연속손실: {risk_st['consecutive_loss_days']}일 | "
              f"거래중단: {risk_st['is_halted']}")

    # ── 스케줄러 실행 ──────────────────────────────────

    def run(self) -> None:
        """스케줄러 시작 (블로킹)"""
        # 시작 알림 + 최초 실행 리밸런싱 체크
        try:
            balance = self.broker.get_balance()
            self.notifier.send_startup(
                self.broker_mode, self.strategy_name, balance.total_assets
            )
            # 보유 종목 없으면 즉시 리밸런싱 (최초 시작 또는 전액 현금 상태)
            if not balance.holdings:
                logger.info("보유 종목 없음 → 초기 리밸런싱 즉시 실행")
                self.job_monthly_rebalance()
        except Exception as e:
            logger.warning(f"시작 처리 실패: {e}")

        # 텔레그램 명령어 수신 시작
        from telegram_handler import TelegramCommandHandler
        cmd_handler = TelegramCommandHandler(self, self.notifier, self.reporter)
        cmd_handler.start()

        # 웹 대시보드 시작 (포트 8080)
        from dashboard import start_dashboard
        start_dashboard(self, port=8080)

        scheduler = BlockingScheduler(timezone=KST)

        # 장 시작 리셋: 매일 09:05 (월~금)
        scheduler.add_job(
            self.job_morning_reset,
            CronTrigger(day_of_week="mon-fri", hour=9, minute=5, timezone=KST),
            id="morning_reset", name="장 시작 리스크 리셋",
            misfire_grace_time=300,
        )

        # 리스크 점검: 매일 09:10 (월~금)
        scheduler.add_job(
            self.job_risk_check,
            CronTrigger(day_of_week="mon-fri", hour=9, minute=10, timezone=KST),
            id="risk_check", name="리스크 점검",
            misfire_grace_time=300,
        )

        # 월간 리밸런싱: 매월 1~7일 평일 15:15 (종가 기준 백테스트와 일치)
        # 황금연휴/설날/추석으로 첫 영업일이 6~7일로 밀리는 경우 대비
        # 내부 _rebalance_if_first_business_day가 실제 첫 영업일 여부를 판별
        for day in range(1, 8):
            scheduler.add_job(
                self._rebalance_if_first_business_day,
                CronTrigger(day=day, day_of_week="mon-fri", hour=15, minute=15, timezone=KST),
                id=f"monthly_rebalance_{day}",
                name=f"월간 리밸런싱 (매월 {day}일 체크)",
                misfire_grace_time=600,
                args=[day],
            )

        # 장 마감 집계: 매일 15:35 (월~금)
        scheduler.add_job(
            self.job_daily_close,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=35, timezone=KST),
            id="daily_close", name="장 마감 집계",
            misfire_grace_time=300,
        )

        logger.info("스케줄러 시작")
        logger.info("등록된 작업:")
        for job in scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None) or "미정"
            logger.info(f"  - {job.name} | 다음 실행: {next_run}")

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("스케줄러 종료")

    # ── 내부 헬퍼 ──────────────────────────────────────

    def _rebalance_if_first_business_day(self, day: int) -> None:
        """매월 첫 영업일에만 리밸런싱 실행 (KRX 휴장일 포함)"""
        today = date.today()
        try:
            from pykrx import stock as pykrx_stock
            bdays = pykrx_stock.get_business_days_of_month(today.year, today.month)
            # pykrx returns pandas DatetimeIndex — elements are Timestamp objects
            if len(bdays) > 0:
                first_bday = bdays[0].date()   # Timestamp → date
                if today == first_bday:
                    logger.info(f"첫 영업일 확인: {today} → 리밸런싱 실행")
                    self.job_monthly_rebalance()
                else:
                    logger.debug(f"{today}은 첫 영업일 아님 (첫 영업일: {first_bday}) → 스킵")
                return
        except Exception as e:
            logger.warning(f"pykrx 영업일 조회 실패, 주말 체크로 대체: {e}")

        # fallback: 이전 영업일이 지난달이면 첫 영업일
        prev_bday = today - timedelta(days=1)
        while prev_bday.weekday() >= 5:
            prev_bday -= timedelta(days=1)

        if prev_bday.month != today.month:
            logger.info(f"첫 영업일 확인(fallback): {today} → 리밸런싱 실행")
            self.job_monthly_rebalance()
        else:
            logger.debug(f"{today}은 첫 영업일 아님 (이전 영업일: {prev_bday}) → 스킵")

    def _load_latest_prices(self):
        """최신 가격 데이터 수집 (1년치)"""
        from data.fetcher import ETFDataFetcher
        from config import ALL_ETFS
        end_dt   = date.today().strftime("%Y-%m-%d")
        start_dt = (date.today() - timedelta(days=400)).strftime("%Y-%m-%d")
        try:
            fetcher = ETFDataFetcher()
            prices  = fetcher.get_prices(list(ALL_ETFS.keys()), start_dt, end_dt,
                                         force_refresh=True)
            logger.info(f"가격 수집 완료: {len(prices)}거래일 × {len(prices.columns)}종목")
            return prices
        except Exception as e:
            logger.error(f"가격 수집 실패: {e}")
            return None

    def _cancel_pending_orders_after(self, delay_sec: int = 180) -> None:
        """리밸런싱 후 미체결 주문 확인 및 취소 (KIS 브로커 전용)"""
        from broker.kis_order import KISOrderManager
        if not isinstance(self.broker, KISOrderManager):
            return
        import threading

        def _check():
            import time
            time.sleep(delay_sec)
            try:
                pending = self.broker.get_pending_orders()
                if not pending:
                    logger.info("미체결 주문 없음")
                    return
                logger.warning(f"미체결 주문 {len(pending)}건 발견 → 취소 시도")
                for o in pending:
                    self.broker.cancel_order(
                        order_no = o.get("odno", ""),
                        ticker   = o.get("pdno", ""),
                        qty      = int(o.get("ord_qty", 0)),
                        price    = int(o.get("ord_unpr", 0)),
                    )
                self.notifier.send_text(f":clock3: 미체결 {len(pending)}건 취소 처리 완료")
            except Exception as e:
                logger.error(f"미체결 취소 오류: {e}")

        threading.Thread(target=_check, daemon=True).start()
        logger.info(f"미체결 확인 예약: {delay_sec}초 후")

    def _is_last_business_day(self) -> bool:
        """오늘이 이번 달 마지막 영업일인지 확인"""
        today    = date.today()
        tomorrow = today + timedelta(days=1)
        while tomorrow.weekday() >= 5:   # 주말 건너뜀
            tomorrow += timedelta(days=1)
        return tomorrow.month != today.month

    def _make_reduced_strategy(self, reduce_ratio: float):
        """포지션 축소 전략: 원래 비중을 축소하고 나머지를 현금으로"""
        from config import ETF_UNIVERSE
        original_fn = self.strategy.get_weights

        def reduced_fn(prices):
            w = original_fn(prices)
            # 현금성 ETF 목록
            cash_tickers = list(ETF_UNIVERSE.get("CASH", {}).keys())
            avail_cash   = [t for t in cash_tickers if t in w.index]

            # 전체 비중을 축소
            w = w * (1 - reduce_ratio)
            # 축소분을 현금에 추가
            if avail_cash:
                best_cash = next(
                    (t for t in ["449170", "157450"] if t in avail_cash),
                    avail_cash[0]
                )
                w[best_cash] = w.get(best_cash, 0) + reduce_ratio
            total = w.sum()
            return w / total if total > 0 else w

        return reduced_fn
