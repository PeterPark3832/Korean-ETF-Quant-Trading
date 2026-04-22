"""
KIS 주문 / 잔고 / 계좌 조회 모듈
────────────────────────────────────────────────────────────────
[개선] 예수금 조회 필드를 D+0(dnca_tot_amt)에서 D+2(prvs_rcdl_excc_amt)로 변경하여
실제 주식 매도 대금이 포함된 '주문 가능 금액'을 포트폴리오 자산에 정확히 반영합니다.
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
    cash:           float    # 예수금 (D+2 기준)
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
            f"  예수금:  {self.cash:>15,.0f} 원 (D+2 기준)",
            f"  평가금액: {self.total_eval:>14,.0f} 원",
            f"  총 손익: {self.total_pnl:>+14,.0f} 원 ({self.total_pnl_rate:+.2f}%)",
            f"  상태:    🟢 정상",
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
        MAX_PAGES   = 20

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

            ctx_code = data.get("ctx_area_fk100", "").strip()
            if not ctx_code or not output1:
                break
        else:
            logger.warning(f"잔고 조회: 최대 페이지({MAX_PAGES}) 도달")

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

        # ── [핵심 수정 구간] ──
        summary = output2[0] if output2 else {}
        
        # 주식매도 대금이 반영된 D+2 예상 예수금 필드 사용
        # 1순위: prvs_rcdl_excc_amt (D+2 미수제외 예수금)
        # 2순위: nass_amt (순자산금액 - 평가액) 또는 dnca_tot_amt
        cash_d2 = float(summary.get("prvs_rcdl_excc_amt", 0))
        if cash_d2 <= 0:
            # D+2 데이터가 0으로 오면 D+0(dnca_tot_amt)이라도 가져옴
            cash_d2 = float(summary.get("dnca_tot_amt", 0))
            
        total_eval     = float(summary.get("tot_evlu_amt", 0))
        total_purchase = float(summary.get("pchs_amt_smtl_amt", 0))
        
        # 총 자산도 D+2 현금 기준으로 다시 계산
        total_assets   = total_eval + cash_d2 
        total_pnl      = float(summary.get("evlu_pfls_smtl_amt", 0))
        total_pnl_rate = (total_pnl / total_purchase * 100) if total_purchase > 0 else 0

        bal = AccountBalance(
            holdings       = holdings,
            total_eval     = total_eval,
            total_purchase = total_purchase,
            cash           = cash_d2,
            total_assets   = total_assets,
            total_pnl      = total_pnl,
            total_pnl_rate = total_pnl_rate,
        )
        logger.info(f"잔고 조회 완료: 총자산 {total_assets:,.0f}원 | 예수금(D+2) {cash_d2:,.0f}원")
        return bal

    # ── 매수 / 매도 주문 (기존과 동일) ──────────────────────────

    def order_buy(self, ticker: str, qty: int, price: int = 0, order_type: str = "01") -> OrderResult:
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
        data     = self.client._post(path, tr_id, body)
        success  = data.get("rt_cd") == "0"
        output   = data.get("output", {})
        result = OrderResult(
            success=success, ticker=ticker, side="buy",
            qty=qty, price=price, order_no=output.get("ODNO", ""), 
            message=data.get("msg1", ""), raw=data,
        )
        (logger.info if success else logger.error)(str(result))
        return result

    def order_sell(self, ticker: str, qty: int, price: int = 0, order_type: str = "01") -> OrderResult:
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
        data     = self.client._post(path, tr_id, body)
        success  = data.get("rt_cd") == "0"
        output   = data.get("output", {})
        result = OrderResult(
            success=success, ticker=ticker, side="sell",
            qty=qty, price=price, order_no=output.get("ODNO", ""), 
            message=data.get("msg1", ""), raw=data,
        )
        (logger.info if success else logger.error)(str(result))
        return result

    # ── 미체결 / 가능금액 조회 (기존과 동일) ──────────────────────────

    def get_available_cash(self) -> int:
        """실제 주문가능금액 조회 (T+2 정산 반영)"""
        ref_ticker = "157450"
        ref_price  = 112000
        try:
            path   = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
            tr_id  = "TTTC8908R" if self.client.mode == "real" else "VTTC8908R"
            params = {
                "CANO":                  self.client.acct_num,
                "ACNT_PRDT_CD":          self.client.acct_prod,
                "PDNO":                  ref_ticker,
                "ORD_UNPR":              str(ref_price),
                "ORD_DVSN":              "01",
                "CMA_EVLU_AMT_ICLD_YN": "Y",
                "OVRS_ICLD_YN":          "N",
            }
            data   = self.client._get(path, tr_id, params)
            output = data.get("output", {})
            cash   = int(output.get("ord_psbl_cash", 0))
            logger.info(f"실제 주문가능금액: {cash:,}원")
            return cash
        except Exception as e:
            logger.warning(f"주문가능금액 조회 실패: {e}")
            return 0

    def get_max_buy_qty(self, ticker: str, price: int) -> int:
        """최대 매수가능 수량 조회"""
        path  = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        tr_id = "TTTC8908R" if self.client.mode == "real" else "VTTC8908R"
        params = {
            "CANO":          self.client.acct_num,
            "ACNT_PRDT_CD":  self.client.acct_prod,
            "PDNO":          ticker,
            "ORD_UNPR":      str(price),
            "ORD_DVSN":      "01",
            "CMA_EVLU_AMT_ICLD_YN": "Y",
            "OVRS_ICLD_YN":  "N",
        }
        data = self.client._get(path, tr_id, params)
        output = data.get("output", {})
        qty = int(output.get("ord_psbl_qty", 0))
        if qty == 0 and price > 0:
            cash = int(output.get("ord_psbl_cash", 0))
            if cash > 0:
                qty = int(cash * 0.98 / price)
        logger.info(f"주문가능조회 [{ticker}]: {qty}주")
        return qty
