"""
모의 브로커 (Paper Broker)
────────────────────────────────────────────────────────────────
KIS API 없이 로컬에서 실거래 환경을 완전히 시뮬레이션합니다.
실거래 전환 시 KISOrderManager로 인터페이스가 동일합니다.

용도:
  - API 키 없이 포트폴리오 리밸런싱 로직 테스트
  - 전략 변경 시 실거래 전 검증
  - CI/CD 자동 테스트

특징:
  - 수수료 / 슬리피지 반영
  - 실제 ETF 현재가는 pykrx로 조회 (또는 캐시 활용)
  - 거래 히스토리 로컬 JSON 저장
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any

import pandas as pd
from loguru import logger

from broker.kis_order import OrderResult, AccountBalance, HoldingItem
from config import TRANSACTION_COST, SLIPPAGE, ALL_ETFS

PAPER_STATE_PATH = Path(__file__).parent.parent / "data" / "cache" / "paper_state.json"


class PaperBroker:
    """
    모의 브로커

    KISOrderManager와 동일한 인터페이스를 제공하므로
    broker 변수만 교체하면 실거래로 전환됩니다.

    사용법:
        broker = PaperBroker(initial_cash=10_000_000)
        broker.order_buy("069500", qty=5, price=35000)
        print(broker.get_balance())
    """

    def __init__(
        self,
        initial_cash: float = 10_000_000,
        transaction_cost: float = TRANSACTION_COST,
        slippage: float = SLIPPAGE,
        price_fetcher=None,    # 현재가 조회 callable (ticker → int)
    ):
        self._cost     = transaction_cost
        self._slippage = slippage
        self._fetch_price = price_fetcher or self._default_price_fetch

        # 상태 로드 또는 초기화
        state = self._load_state()
        if state:
            self._cash:     float          = state["cash"]
            self._holdings: dict[str, int] = state["holdings"]
            self._avg_price: dict[str, float] = state["avg_price"]
            self._history:  list[dict]     = state["history"]
            logger.info(f"[모의] 저장된 상태 로드: 현금 {self._cash:,.0f}원")
        else:
            self._cash       = initial_cash
            self._holdings   = {}       # ticker → 수량
            self._avg_price  = {}       # ticker → 평균단가
            self._history    = []       # 거래 히스토리
            logger.info(f"[모의] 새 포트폴리오 시작: {initial_cash:,.0f}원")

    # ── 공개 인터페이스 (KISOrderManager 동일) ─────────

    def get_balance(self) -> AccountBalance:
        prices = self._get_all_current_prices()
        holdings = []
        total_eval     = 0.0
        total_purchase = 0.0

        for ticker, qty in self._holdings.items():
            if qty <= 0:
                continue
            cur_price  = prices.get(ticker, self._avg_price.get(ticker, 0))
            avg        = self._avg_price.get(ticker, cur_price)
            eval_amt   = cur_price * qty
            purch_amt  = avg * qty
            pnl        = eval_amt - purch_amt
            pnl_rate   = (pnl / purch_amt * 100) if purch_amt > 0 else 0

            holdings.append(HoldingItem(
                ticker        = ticker,
                name          = ALL_ETFS.get(ticker, ticker),
                qty           = qty,
                avg_price     = avg,
                current_price = cur_price,
                eval_amount   = eval_amt,
                profit_loss   = pnl,
                profit_rate   = pnl_rate,
            ))
            total_eval     += eval_amt
            total_purchase += purch_amt

        total_assets   = total_eval + self._cash
        total_pnl      = total_eval - total_purchase
        total_pnl_rate = (total_pnl / total_purchase * 100) if total_purchase > 0 else 0

        return AccountBalance(
            holdings       = holdings,
            total_eval     = total_eval,
            total_purchase = total_purchase,
            cash           = self._cash,
            total_assets   = total_assets,
            total_pnl      = total_pnl,
            total_pnl_rate = total_pnl_rate,
        )

    def order_buy(
        self,
        ticker: str,
        qty: int,
        price: int = 0,
        order_type: str = "01",
    ) -> OrderResult:
        if qty <= 0:
            return OrderResult(False, ticker, "buy", qty, price, message="수량 오류")

        exec_price = price if price > 0 else self._fetch_price(ticker)
        if exec_price <= 0:
            return OrderResult(False, ticker, "buy", qty, 0, message="현재가 조회 실패")

        # 슬리피지 반영 (매수는 약간 높게)
        exec_price_with_slip = int(exec_price * (1 + self._slippage))
        cost_total  = exec_price_with_slip * qty
        commission  = cost_total * self._cost
        total_cost  = cost_total + commission

        if total_cost > self._cash:
            max_qty = int(self._cash / (exec_price_with_slip * (1 + self._cost)))
            if max_qty <= 0:
                return OrderResult(False, ticker, "buy", qty, exec_price,
                                   message=f"잔액 부족 (필요: {total_cost:,.0f}원, 보유: {self._cash:,.0f}원)")
            qty        = max_qty
            cost_total  = exec_price_with_slip * qty
            commission  = cost_total * self._cost
            total_cost  = cost_total + commission
            logger.warning(f"[모의] 잔액 부족 → 수량 조정: {qty}주")

        # 평균 단가 업데이트
        prev_qty   = self._holdings.get(ticker, 0)
        prev_avg   = self._avg_price.get(ticker, 0)
        new_qty    = prev_qty + qty
        self._avg_price[ticker] = (
            (prev_avg * prev_qty + exec_price_with_slip * qty) / new_qty
            if new_qty > 0 else exec_price_with_slip
        )
        self._holdings[ticker] = new_qty
        self._cash            -= total_cost

        self._record(ticker, "buy", qty, exec_price_with_slip, commission)
        self._save_state()

        logger.info(
            f"[모의] 매수: {ALL_ETFS.get(ticker, ticker)} {qty}주 "
            f"@ {exec_price_with_slip:,}원 | 수수료 {commission:,.0f}원 | "
            f"잔금 {self._cash:,.0f}원"
        )
        return OrderResult(True, ticker, "buy", qty, exec_price_with_slip,
                           order_no=f"P{len(self._history):06d}")

    def order_sell(
        self,
        ticker: str,
        qty: int,
        price: int = 0,
        order_type: str = "01",
    ) -> OrderResult:
        held = self._holdings.get(ticker, 0)
        if held <= 0:
            return OrderResult(False, ticker, "sell", qty, price, message="보유 수량 없음")
        if qty > held:
            qty = held
            logger.warning(f"[모의] 매도 수량 조정: {held}주 (보유량 초과)")
        if qty <= 0:
            return OrderResult(False, ticker, "sell", qty, price, message="수량 오류")

        exec_price = price if price > 0 else self._fetch_price(ticker)
        if exec_price <= 0:
            return OrderResult(False, ticker, "sell", qty, 0, message="현재가 조회 실패")

        # 슬리피지 반영 (매도는 약간 낮게)
        exec_price_with_slip = int(exec_price * (1 - self._slippage))
        proceeds   = exec_price_with_slip * qty
        commission = proceeds * self._cost
        net        = proceeds - commission

        self._holdings[ticker] = held - qty
        if self._holdings[ticker] == 0:
            del self._holdings[ticker]
            del self._avg_price[ticker]
        self._cash += net

        self._record(ticker, "sell", qty, exec_price_with_slip, commission)
        self._save_state()

        logger.info(
            f"[모의] 매도: {ALL_ETFS.get(ticker, ticker)} {qty}주 "
            f"@ {exec_price_with_slip:,}원 | 수수료 {commission:,.0f}원 | "
            f"잔금 {self._cash:,.0f}원"
        )
        return OrderResult(True, ticker, "sell", qty, exec_price_with_slip,
                           order_no=f"P{len(self._history):06d}")

    def get_max_buy_qty(self, ticker: str, price: int) -> int:
        effective_price = int(price * (1 + self._cost + self._slippage))
        return int(self._cash / effective_price) if effective_price > 0 else 0

    # ── 히스토리 조회 ──────────────────────────────────

    def get_history(self) -> pd.DataFrame:
        if not self._history:
            return pd.DataFrame()
        return pd.DataFrame(self._history)

    def reset(self, initial_cash: float = 10_000_000) -> None:
        """포트폴리오 초기화 (테스트용)"""
        self._cash      = initial_cash
        self._holdings  = {}
        self._avg_price = {}
        self._history   = []
        PAPER_STATE_PATH.unlink(missing_ok=True)
        logger.info(f"[모의] 포트폴리오 초기화: {initial_cash:,.0f}원")

    # ── 내부 메서드 ────────────────────────────────────

    def _get_all_current_prices(self) -> dict[str, float]:
        prices = {}
        for ticker in list(self._holdings.keys()):
            try:
                prices[ticker] = float(self._fetch_price(ticker))
            except Exception as e:
                logger.warning(f"[{ticker}] 현재가 조회 실패: {e}")
                prices[ticker] = self._avg_price.get(ticker, 0)
        return prices

    def _default_price_fetch(self, ticker: str) -> int:
        """pykrx로 최근 종가 조회 (기본 가격 조회기)"""
        try:
            from pykrx import stock
            from datetime import date, timedelta
            today = date.today().strftime("%Y%m%d")
            week_ago = (date.today() - timedelta(days=7)).strftime("%Y%m%d")
            df = stock.get_market_ohlcv_by_date(week_ago, today, ticker)
            if df is not None and not df.empty:
                return int(df.iloc[-1, 3])  # Close 컬럼
        except Exception as e:
            logger.warning(f"pykrx 가격 조회 실패 [{ticker}]: {e}")
        return 0

    def _record(
        self, ticker: str, side: str, qty: int, price: int, commission: float
    ) -> None:
        self._history.append({
            "datetime":  datetime.now().isoformat(),
            "ticker":    ticker,
            "name":      ALL_ETFS.get(ticker, ticker),
            "side":      side,
            "qty":       qty,
            "price":     price,
            "commission": commission,
            "amount":    price * qty,
        })

    def _save_state(self) -> None:
        try:
            PAPER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            PAPER_STATE_PATH.write_text(json.dumps({
                "cash":      self._cash,
                "holdings":  self._holdings,
                "avg_price": self._avg_price,
                "history":   self._history,
                "saved_at":  datetime.now().isoformat(),
            }, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"상태 저장 실패: {e}")

    def _load_state(self) -> dict | None:
        try:
            if PAPER_STATE_PATH.exists():
                return json.loads(PAPER_STATE_PATH.read_text())
        except Exception:
            pass
        return None
