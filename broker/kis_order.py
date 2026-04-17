"""
KIS 주문 / 잔고 / 계좌 조회 모듈
────────────────────────────────────────────────────────────────
ETF 매수·매도, 잔고 조회, 계좌 현황을 처리합니다.

TR_ID 구분:
  실전 매수:  TTTC0802U
  실전 매도:  TTTC0801U
  모의 매수:  VTTC0802U
  모의 매도:  VTTC0801U
  잔고 조회 실전: TTTC8434R
  잔고 조회 모의: VTTC8434R
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

if TYPE_CHECKING:
    from broker.kis_client import KISClient


# ── TR_ID 매핑 ────────────────────────────────────────
TR = {
    "real": {
        "buy":          "TTTC0802U",
        "sell":         "TTTC0801U",
        "balance":      "TTTC8434R",
        "order_list":   "TTTC8001R",
    },
    "paper": {
        "buy":          "VTTC0802U",
        "sell":         "VTTC0801U",
        "balance":      "VTTC8434R",
        "order_list":   "VTTC8001R",
    },
}


@dataclass
class OrderResult:
    """주문 결과"""
    success:    bool
    ticker:     str
    side:       str          # "buy" | "sell"
    qty:        int
    price:      int          # 0 = 시장가
    order_no:   str = ""
    message:    str = ""
    raw:        dict = field(default_factory=dict)

    def __str__(self) -> str:
        status = "성공" if self.success else "실패"
        side   = "매수" if self.side == "buy" else "매도"
        return (
            f"[{status}] {side} {self.ticker} "
            f"{self.qty}주 @ {'시장가' if self.price == 0 else f'{self.price:,}원'}"
            + (f" | 주문번호: {self.order_no}" if self.order_no else "")
            + (f" | {self.message}" if self.message else "")
        )


@dataclass
class HoldingItem:
    """보유 종목 단건"""
    ticker:      str
    name:        str
    qty:         int
    avg_price:   float
    current_price: float
    eval_amount: float
    profit_loss: float
    profit_rate: float


@dataclass
class AccountBalance:
    """계좌 잔고 전체"""
    holdings:       list[HoldingItem]
    total_eval:     float    # 총 평가금액
    total_purchase: float    # 총 매입금액
    cash:           float    # 예수금
    total_assets:   float    # 총 자산 (평가 + 현금)
    total_pnl:      float    # 총 손익
    total_pnl_rate: float    # 총 손익률 (%)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.holdings:
            return pd.DataFrame()
        return pd.DataFrame([{
            "ticker":       h.ticker,
            "name":         h.name,
            "qty":          h.qty,
            "avg_price":    h.avg_price,
            "current_price": h.current_price,
            "eval_amount":  h.eval_amount,
            "profit_loss":  h.profit_loss,
            "profit_rate":  h.profit_rate,
            "weight":       h.eval_amount / self.total_assets if self.total_assets > 0 else 0,
        } for h in self.holdings])

    def __str__(self) -> str:
        lines = [
            f"{'='*55}",
            f"  총 자산: {self.total_assets:>15,.0f} 원",
            f"  예수금:  {self.cash:>15,.0f} 원",
            f"  평가금액: {self.total_eval:>14,.0f} 원",
            f"  총 손익: {self.total_pnl:>+14,.0f} 원 ({self.total_pnl_rate:+.2f}%)",
            f"{'─'*55}",
        ]
        if self.holdings:
            lines.append(f"  {'종목':12s} {'수량':>5} {'평균단가':>9} {'현재가':>9} {'수익률':>8}")
            lines.append(f"  {'─'*50}")
            for h in sorted(self.holdings, key=lambda x: x.eval_amount, reverse=True):
                lines.append(
                    f"  {h.name[:12]:12s} {h.qty:>5,} "
                    f"{h.avg_price:>9,.0f} {h.current_price:>9,.0f} "
                    f"{h.profit_rate:>+7.1f}%"
                )
        lines.append(f"{'='*55}")
        return "\n".join(lines)


class KISOrderManager:
    """
    KIS 주문 / 잔고 관리

    사용법:
        om = KISOrderManager(client)
        balance = om.get_balance()
        result  = om.order_buy("069500", qty=5)
        result  = om.order_sell("069500", qty=5)
    """

    def __init__(self, client: "KISClient"):
        self.client = client
        self._tr    = TR[client.mode]

    # ── 잔고 조회 ──────────────────────────────────────

    def get_balance(self) -> AccountBalance:
        """계좌 잔고 전체 조회 (페이지네이션 자동 처리)"""
        path   = "/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id  = self._tr["balance"]

        all_output1 = []
        ctx_code    = ""
        output2     = [{}]
        MAX_PAGES   = 20   # 무한루프 방지

        for page in range(MAX_PAGES):
            params = {
                "CANO":           self.client.acct_num,
                "ACNT_PRDT_CD":   self.client.acct_prod,
                "AFHR_FLPR_YN":   "N",
                "OFL_YN":         "",
                "INQR_DVSN":      "02",
                "UNPR_DVSN":      "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN":      "01",
                "CTX_AREA_FK100": ctx_code,
                "CTX_AREA_NK100": "",
            }
            data = self.client._get(path, tr_id, params)

            output1 = data.get("output1", [])
            output2 = data.get("output2", [{}])
            all_output1.extend(output1)

            # KIS API 종료 조건:
            # 1) ctx_area_fk100 비어있음 (공식 마지막 페이지)
            # 2) 이번 페이지 output1 비어있음 (더 이상 데이터 없음)
            ctx_code = data.get("ctx_area_fk100", "").strip()
            if not ctx_code or not output1:
                break
        else:
            logger.warning(f"잔고 조회: 최대 페이지({MAX_PAGES}) 도달")

        # 보유 종목 파싱 (ticker 기준 중복 제거)
        # KIS API는 같은 종목을 매입 단위(lot)별로 분리 반환하나,
        # hldg_qty·evlu_amt·pchs_avg_pric 등 모든 집계값은 첫 record에 이미 전체 값이 담김
        # → ticker 첫 번째 record만 사용하고 이후 중복 record는 무시
        seen: set[str] = set()
        holdings = []
        for item in all_output1:
            qty = int(item.get("hldg_qty", 0))
            if qty <= 0:
                continue
            ticker = item.get("pdno", "")
            if ticker in seen:
                continue
            seen.add(ticker)

            avg_price   = float(item.get("pchs_avg_pric", 0))
            eval_amount = float(item.get("evlu_amt", 0))
            purchase    = avg_price * qty
            pnl         = eval_amount - purchase
            pnl_rate    = (pnl / purchase * 100) if purchase > 0 else float(item.get("evlu_pfls_rt", 0))

            holdings.append(HoldingItem(
                ticker        = ticker,
                name          = item.get("prdt_name", ""),
                qty           = qty,
                avg_price     = avg_price,
                current_price = float(item.get("prpr", 0)),
                eval_amount   = eval_amount,
                profit_loss   = pnl,
                profit_rate   = pnl_rate,
            ))

        # 요약 파싱
        summary = output2[0] if output2 else {}
        total_eval     = float(summary.get("tot_evlu_amt", 0))
        total_purchase = float(summary.get("pchs_amt_smtl_amt", 0))
        cash           = float(summary.get("dnca_tot_amt", 0))
        total_assets   = total_eval + cash
        total_pnl      = float(summary.get("evlu_pfls_smtl_amt", 0))
        total_pnl_rate = (total_pnl / total_purchase * 100) if total_purchase > 0 else 0

        bal = AccountBalance(
            holdings       = holdings,
            total_eval     = total_eval,
            total_purchase = total_purchase,
            cash           = cash,
            total_assets   = total_assets,
            total_pnl      = total_pnl,
            total_pnl_rate = total_pnl_rate,
        )
        logger.info(f"잔고 조회 완료: 총자산 {total_assets:,.0f}원 | 보유 {len(holdings)}종목")
        return bal

    # ── 매수 주문 ──────────────────────────────────────

    def order_buy(
        self,
        ticker: str,
        qty: int,
        price: int = 0,          # 0 = 시장가
        order_type: str = "01",  # "00"=지정가, "01"=시장가
    ) -> OrderResult:
        """
        ETF 매수 주문

        Args:
            ticker:     종목코드 (6자리)
            qty:        주문 수량
            price:      주문가격 (시장가=0)
            order_type: "01"=시장가(기본), "00"=지정가
        """
        if qty <= 0:
            return OrderResult(False, ticker, "buy", qty, price, message="수량 오류")

        path  = "/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = self._tr["buy"]
        body  = {
            "CANO":          self.client.acct_num,
            "ACNT_PRDT_CD":  self.client.acct_prod,
            "PDNO":          ticker,
            "ORD_DVSN":      order_type,
            "ORD_QTY":       str(qty),
            "ORD_UNPR":      str(price),
        }
        logger.info(f"매수 주문: {ticker} {qty}주 @ {'시장가' if price == 0 else f'{price:,}원'}")
        data     = self.client._post(path, tr_id, body)
        success  = data.get("rt_cd") == "0"
        output   = data.get("output", {})
        order_no = output.get("ODNO", "")
        message  = data.get("msg1", "")

        result = OrderResult(
            success=success, ticker=ticker, side="buy",
            qty=qty, price=price, order_no=order_no, message=message, raw=data,
        )
        (logger.info if success else logger.error)(str(result))
        return result

    # ── 매도 주문 ──────────────────────────────────────

    def order_sell(
        self,
        ticker: str,
        qty: int,
        price: int = 0,
        order_type: str = "01",
    ) -> OrderResult:
        """ETF 매도 주문"""
        if qty <= 0:
            return OrderResult(False, ticker, "sell", qty, price, message="수량 오류")

        path  = "/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = self._tr["sell"]
        body  = {
            "CANO":          self.client.acct_num,
            "ACNT_PRDT_CD":  self.client.acct_prod,
            "PDNO":          ticker,
            "ORD_DVSN":      order_type,
            "ORD_QTY":       str(qty),
            "ORD_UNPR":      str(price),
        }
        logger.info(f"매도 주문: {ticker} {qty}주 @ {'시장가' if price == 0 else f'{price:,}원'}")
        data     = self.client._post(path, tr_id, body)
        success  = data.get("rt_cd") == "0"
        output   = data.get("output", {})
        order_no = output.get("ODNO", "")
        message  = data.get("msg1", "")

        result = OrderResult(
            success=success, ticker=ticker, side="sell",
            qty=qty, price=price, order_no=order_no, message=message, raw=data,
        )
        (logger.info if success else logger.error)(str(result))
        return result

    # ── 미체결 주문 조회 / 취소 ───────────────────────────

    def get_pending_orders(self) -> list[dict]:
        """당일 미체결 주문 목록 조회"""
        path  = "/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
        tr_id = "TTTC8036R" if self.client.mode == "real" else "VTTC8036R"
        params = {
            "CANO":           self.client.acct_num,
            "ACNT_PRDT_CD":   self.client.acct_prod,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1":    "0",
            "INQR_DVSN_2":    "0",
        }
        try:
            data = self.client._get(path, tr_id, params)
            return data.get("output", []) or []
        except Exception as e:
            logger.warning(f"미체결 조회 실패: {e}")
            return []

    def cancel_order(self, order_no: str, ticker: str, qty: int, price: int) -> bool:
        """주문 취소 (미체결 주문 한정)"""
        path  = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
        tr_id = "TTTC0803U" if self.client.mode == "real" else "VTTC0803U"
        body  = {
            "CANO":          self.client.acct_num,
            "ACNT_PRDT_CD":  self.client.acct_prod,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO":     order_no,
            "ORD_DVSN":      "02",       # 취소
            "RVSE_CNCL_DVSN_CD": "02",  # 취소
            "ORD_QTY":       str(qty),
            "ORD_UNPR":      str(price),
            "QTY_ALL_ORD_YN": "Y",
        }
        try:
            data    = self.client._post(path, tr_id, body)
            success = data.get("rt_cd") == "0"
            if success:
                logger.info(f"주문 취소 완료: {order_no} {ticker}")
            else:
                logger.warning(f"주문 취소 실패: {order_no} | {data.get('msg1','')}")
            return success
        except Exception as e:
            logger.warning(f"주문 취소 오류: {e}")
            return False

    # ── 주문 가능 수량 조회 ────────────────────────────

    def get_max_buy_qty(self, ticker: str, price: int) -> int:
        """해당 가격에 살 수 있는 최대 수량"""
        path  = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        tr_id = "TTTC8908R" if self.client.mode == "real" else "VTTC8908R"
        params = {
            "CANO":          self.client.acct_num,
            "ACNT_PRDT_CD":  self.client.acct_prod,
            "PDNO":          ticker,
            "ORD_UNPR":      str(price),
            "ORD_DVSN":      "01",
            "CMA_EVLU_AMT_ICLD_YN": "Y",  # CMA 잔고 포함
            "OVRS_ICLD_YN":  "N",
        }
        data = self.client._get(path, tr_id, params)
        output = data.get("output", {})
        qty = int(output.get("ord_psbl_qty", 0))

        # ISA 중개형 등 일부 계좌는 ord_psbl_qty=0이지만 ord_psbl_cash에 가능금액이 있음
        if qty == 0 and price > 0:
            cash = int(output.get("ord_psbl_cash", 0))
            if cash > 0:
                qty = int(cash * 0.98 / price)  # 2% 수수료·슬리피지 버퍼

        logger.info(
            f"주문가능조회 [{ticker}]: {qty}주 | "
            f"주문가능금액={output.get('ord_psbl_cash','?')}원"
        )
        return qty
