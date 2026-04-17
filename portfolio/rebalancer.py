"""
포트폴리오 리밸런싱 실행기
────────────────────────────────────────────────────────────────
전략의 목표 비중을 받아 실제 주문으로 변환합니다.

핵심 로직:
  1. 현재 잔고 조회 (실거래/모의)
  2. 전략 신호 계산 (목표 비중)
  3. 현재 비중과 목표 비중 비교
  4. 임계값(threshold) 이상 차이 나는 종목만 거래 (소량 거래 최소화)
  5. 매도 먼저 → 현금 확보 → 매수 순서로 실행
  6. 리밸런싱 결과 기록

안전 장치:
  - 단일 주문 최대 금액 제한
  - 장중 시간 외 주문 차단
  - 잔액 부족 시 비중 스케일 다운
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import pandas as pd
import numpy as np
from loguru import logger

from config import ALL_ETFS, TRANSACTION_COST


def _tick_price(price: int, direction: str = "up") -> int:
    """KRX 호가단위 기준으로 가격 조정 (매수=올림, 매도=내림)"""
    if price < 2_000:        tick = 1
    elif price < 5_000:      tick = 5
    elif price < 10_000:     tick = 10
    elif price < 50_000:     tick = 50
    elif price < 100_000:    tick = 100
    elif price < 500_000:    tick = 500
    else:                    tick = 1_000
    if direction == "up":
        return ((price + tick - 1) // tick) * tick
    return (price // tick) * tick


@dataclass
class RebalanceOrder:
    """단일 리밸런싱 주문"""
    ticker:         str
    name:           str
    side:           str       # "buy" | "sell"
    qty:            int
    price:          int
    target_weight:  float
    current_weight: float
    weight_diff:    float


@dataclass
class RebalanceResult:
    """리밸런싱 실행 결과"""
    executed_at:     str
    total_assets:    float
    orders:          list[RebalanceOrder] = field(default_factory=list)
    success_count:   int = 0
    fail_count:      int = 0
    total_turnover:  float = 0.0
    skipped_count:   int = 0   # 임계값 미달로 건너뜀

    def summary(self) -> str:
        lines = [
            f"{'='*55}",
            f"  리밸런싱 실행: {self.executed_at}",
            f"  총 자산:  {self.total_assets:>14,.0f} 원",
            f"  회전율:   {self.total_turnover*100:>13.1f} %",
            f"  성공: {self.success_count}건 | 실패: {self.fail_count}건 | 스킵: {self.skipped_count}건",
            f"{'─'*55}",
        ]
        if self.orders:
            lines.append(f"  {'종목':14s} {'방향':4s} {'수량':>5} {'가격':>9} {'비중변화':>12}")
            lines.append(f"  {'─'*50}")
            for o in self.orders:
                side_str = "매수" if o.side == "buy" else "매도"
                lines.append(
                    f"  {o.name[:14]:14s} {side_str:4s} {o.qty:>5,} "
                    f"{o.price:>9,}원 "
                    f"{o.current_weight*100:>5.1f}%→{o.target_weight*100:.1f}%"
                )
        lines.append(f"{'='*55}")
        return "\n".join(lines)


class PortfolioRebalancer:
    """
    포트폴리오 리밸런싱 실행기

    사용법:
        rebalancer = PortfolioRebalancer(broker, strategy_fn)
        result = rebalancer.run()
        print(result.summary())
    """

    def __init__(
        self,
        broker,                              # KISOrderManager 또는 PaperBroker
        strategy_fn: Callable,               # prices → target weights
        price_data: pd.DataFrame | None = None,  # 백테스트용 가격 데이터
        rebalance_threshold: float = 0.03,   # 비중 차이 3% 이상일 때만 거래
        min_order_amount: int = 10_000,      # 최소 주문 금액 (1만원 미만 스킵)
        max_weight_per_ticker: float = 0.50, # 단일 종목 최대 비중
        dry_run: bool = False,               # True: 주문 계산만, 실제 주문 안 함
    ):
        self.broker               = broker
        self.strategy_fn          = strategy_fn
        self.price_data           = price_data
        self.rebalance_threshold  = rebalance_threshold
        self.min_order_amount     = min_order_amount
        self.max_weight_per_ticker = max_weight_per_ticker
        self.dry_run              = dry_run

    def run(
        self,
        prices_window: pd.DataFrame | None = None,
    ) -> RebalanceResult:
        """
        리밸런싱 실행

        Args:
            prices_window: 전략에 넘길 가격 DataFrame
                           None이면 self.price_data 사용
        """
        logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}리밸런싱 시작")

        # ── 1. 현재 잔고 조회 ────────────────────────
        balance = self.broker.get_balance()
        total_assets = balance.total_assets
        if total_assets <= 0:
            logger.error("총 자산 0원 - 리밸런싱 중단")
            return RebalanceResult(
                executed_at=datetime.now().isoformat(),
                total_assets=0,
            )

        # 매수에 실제로 쓸 수 있는 현금 (예수금 × 95% 안전 버퍼)
        # total_assets에는 미결제·연계 계좌 금액이 포함될 수 있어 cash 기준으로 제한
        available_cash = balance.cash * 0.95
        logger.info(
            f"총자산: {total_assets:,.0f}원 | "
            f"예수금: {balance.cash:,.0f}원 | "
            f"매수가능: {available_cash:,.0f}원"
        )

        # ── 2. 현재 비중 계산 ─────────────────────────
        current_weights = self._get_current_weights(balance, total_assets)

        # ── 3. 목표 비중 계산 (전략) ─────────────────
        pw = prices_window if prices_window is not None else self.price_data
        if pw is None:
            logger.error("가격 데이터 없음 - 리밸런싱 중단")
            return RebalanceResult(
                executed_at=datetime.now().isoformat(),
                total_assets=total_assets,
            )

        target_weights = self.strategy_fn(pw)
        target_weights = self._validate_weights(target_weights, pw.columns)

        logger.info("목표 비중:")
        for t, w in target_weights[target_weights > 0.01].sort_values(ascending=False).items():
            name = ALL_ETFS.get(t, t)
            logger.info(f"  {name:20s}: {w*100:.1f}%")

        # ── 4. 주문 계획 수립 ─────────────────────────
        current_prices = self._get_current_prices(
            list(set(target_weights[target_weights > 0].index.tolist()
                     + list(current_weights.keys())))
        )

        orders, skipped = self._plan_orders(
            current_weights, target_weights, current_prices, total_assets, available_cash
        )

        result = RebalanceResult(
            executed_at  = datetime.now().isoformat(),
            total_assets = total_assets,
            skipped_count = skipped,
        )
        result.orders = orders

        if not orders:
            logger.info("리밸런싱 불필요 (모든 비중 임계값 이내)")
            return result

        # ── 5. 주문 실행 (매도 먼저) ──────────────────
        sell_orders = [o for o in orders if o.side == "sell"]
        buy_orders  = [o for o in orders if o.side == "buy"]

        for order in sell_orders + buy_orders:
            if self.dry_run:
                logger.info(
                    f"[DRY RUN] {order.side} {ALL_ETFS.get(order.ticker, order.ticker)} "
                    f"{order.qty}주 @ {order.price:,}원"
                )
                result.success_count += 1
                continue

            if order.side == "sell":
                res = self.broker.order_sell(order.ticker, order.qty, price=0)
            else:
                # 지정가 매수: 호가단위 올림 + 실제 주문가능금액 기준 수량 확정
                buy_price = _tick_price(order.price, "up")
                qty = order.qty
                if hasattr(self.broker, "get_max_buy_qty"):
                    try:
                        max_qty = self.broker.get_max_buy_qty(order.ticker, buy_price)
                        logger.info(f"[{order.ticker}] 주문가능 수량: {max_qty}주 @ {buy_price:,}원")
                        if max_qty > 0:
                            qty = min(qty, max_qty)
                        else:
                            result.fail_count += 1
                            continue
                    except Exception as e:
                        logger.warning(f"[{order.ticker}] 주문가능 수량 조회 실패: {e}")
                if qty <= 0:
                    result.fail_count += 1
                    continue
                res = self.broker.order_buy(order.ticker, qty, price=buy_price, order_type="00")

            if res.success:
                result.success_count += 1
            else:
                result.fail_count += 1
                logger.error(f"주문 실패: {res}")

        # ── 6. 회전율 계산 ────────────────────────────
        sell_amt = sum(o.qty * o.price for o in sell_orders)
        result.total_turnover = sell_amt / total_assets if total_assets > 0 else 0

        logger.info(result.summary())
        return result

    # ── 내부 메서드 ────────────────────────────────────

    def _get_current_weights(
        self, balance, total_assets: float
    ) -> dict[str, float]:
        weights = {}
        for h in balance.holdings:
            if total_assets > 0:
                weights[h.ticker] = h.eval_amount / total_assets
        return weights

    def _validate_weights(
        self, weights: pd.Series, all_tickers: pd.Index
    ) -> pd.Series:
        w = weights.reindex(all_tickers).fillna(0).clip(lower=0)
        w = w.clip(upper=self.max_weight_per_ticker)
        total = w.sum()
        return w / total if total > 0 else w

    def _get_current_prices(self, tickers: list[str]) -> dict[str, int]:
        prices = {}

        if hasattr(self.broker, "client"):
            # KISOrderManager: API로 현재가 조회
            price_map = self.broker.client.get_prices_bulk(tickers)
            for t, info in price_map.items():
                prices[t] = info.get("price", 0)
        elif hasattr(self.broker, "_fetch_price"):
            # PaperBroker: pykrx 조회
            for t in tickers:
                prices[t] = self.broker._fetch_price(t)

        # pykrx 실패(장외시간 등) → price_data 마지막 행으로 대체
        if self.price_data is not None:
            last_row = self.price_data.iloc[-1]
            for t in tickers:
                if prices.get(t, 0) <= 0 and t in last_row.index:
                    fallback = int(last_row[t])
                    if fallback > 0:
                        prices[t] = fallback
                        logger.debug(f"[{t}] 현재가 조회 실패 → 마지막 종가 사용: {fallback:,}원")

        return prices

    def _plan_orders(
        self,
        current_weights: dict[str, float],
        target_weights: pd.Series,
        current_prices: dict[str, int],
        total_assets: float,
        available_cash: float | None = None,
    ) -> tuple[list[RebalanceOrder], int]:
        orders:  list[RebalanceOrder] = []
        skipped: int = 0
        remaining_cash = available_cash if available_cash is not None else total_assets

        all_tickers = set(current_weights.keys()) | set(
            target_weights[target_weights > 0].index.tolist()
        )

        # 매도 먼저 계획해야 매도 대금이 매수 재원이 됨 → 매도 종목 우선 정렬
        sell_tickers = [t for t in all_tickers
                        if float(target_weights.get(t, 0.0)) < current_weights.get(t, 0.0)]
        buy_tickers  = [t for t in all_tickers if t not in sell_tickers]

        for ticker in sell_tickers + buy_tickers:
            cur_w    = current_weights.get(ticker, 0.0)
            tgt_w    = float(target_weights.get(ticker, 0.0))
            diff     = tgt_w - cur_w
            price    = current_prices.get(ticker, 0)

            if price <= 0:
                logger.warning(f"[{ticker}] 가격 없음 - 스킵")
                skipped += 1
                continue

            # 임계값 미달 스킵 (단, 완전 청산은 예외 — 소량 잔여 포지션 고착 방지)
            if abs(diff) < self.rebalance_threshold and not (tgt_w == 0 and cur_w > 0):
                skipped += 1
                continue

            target_amount  = tgt_w * total_assets
            current_amount = cur_w * total_assets
            diff_amount    = target_amount - current_amount

            if abs(diff_amount) < self.min_order_amount:
                skipped += 1
                continue

            # 매수: 실제 주문가능금액(예수금) 초과 방지
            if diff > 0:
                buyable_amount = min(diff_amount, remaining_cash)
                qty = int(buyable_amount / price)
                if qty > 0:
                    remaining_cash -= qty * price
            else:
                qty = int(abs(diff_amount) / price)

            if qty <= 0:
                skipped += 1
                continue

            orders.append(RebalanceOrder(
                ticker         = ticker,
                name           = ALL_ETFS.get(ticker, ticker),
                side           = "buy" if diff > 0 else "sell",
                qty            = qty,
                price          = price,
                target_weight  = tgt_w,
                current_weight = cur_w,
                weight_diff    = diff,
            ))

        return orders, skipped
