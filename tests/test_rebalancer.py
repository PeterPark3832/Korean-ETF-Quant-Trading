"""
PortfolioRebalancer 주문 계획·실행 로직 단위 테스트
"""
import time

import pandas as pd
import pytest

from broker.kis_order import AccountBalance, HoldingItem, OrderResult
from portfolio.rebalancer import (
    PortfolioRebalancer,
    _BUY_CASH_RATIO,
    _KIS_AVAILABLE_RATIO,
    _DEFAULT_AVAILABLE_RATIO,
)


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _balance(cash: float, holdings: list[HoldingItem] | None = None) -> AccountBalance:
    holdings = holdings or []
    total_eval = sum(h.eval_amount for h in holdings)
    return AccountBalance(
        holdings=holdings,
        total_eval=total_eval,
        total_purchase=total_eval,
        cash=cash,
        total_assets=total_eval + cash,
        total_pnl=0.0,
        total_pnl_rate=0.0,
    )


def _holding(ticker: str, qty: int, price: float) -> HoldingItem:
    return HoldingItem(
        ticker=ticker, name=ticker, qty=qty, avg_price=price,
        current_price=price, eval_amount=qty * price, profit_loss=0.0, profit_rate=0.0,
    )


class FakeBroker:
    """KISOrderManager 유사 브로커 — get_available_cash 시퀀스로 체결 후 현금 반영을 흉내낸다."""

    def __init__(self, balance: AccountBalance, available_cash_seq: list[float] | None = None):
        self._balance = balance
        self._cash_seq = list(available_cash_seq) if available_cash_seq is not None else None
        self.buy_calls: list[tuple] = []
        self.sell_calls: list[tuple] = []

    def get_balance(self) -> AccountBalance:
        return self._balance

    def get_available_cash(self) -> float:
        if self._cash_seq is None:
            return self._balance.cash
        if len(self._cash_seq) > 1:
            return self._cash_seq.pop(0)
        return self._cash_seq[0]

    def get_max_buy_qty(self, ticker: str, price: int) -> int:
        cash = self.get_available_cash()
        return int(cash / price) if price > 0 else 0

    def order_buy(self, ticker, qty, price=0, order_type="01") -> OrderResult:
        self.buy_calls.append((ticker, qty, price))
        return OrderResult(True, ticker, "buy", qty, price, order_no="B1")

    def order_sell(self, ticker, qty, price=0) -> OrderResult:
        self.sell_calls.append((ticker, qty, price))
        return OrderResult(True, ticker, "sell", qty, price, order_no="S1")


class _NoCashApiBroker:
    """get_available_cash를 지원하지 않는 브로커 (페이퍼 트레이딩 등)"""

    def get_balance(self) -> AccountBalance:
        return _balance(0)


def _make_rebalancer(**kwargs) -> PortfolioRebalancer:
    defaults = dict(broker=FakeBroker(_balance(0)), strategy_fn=lambda p: pd.Series(dtype=float))
    defaults.update(kwargs)
    return PortfolioRebalancer(**defaults)


# ── _validate_weights ────────────────────────────────────────────

class TestValidateWeights:
    def test_normalizes_to_sum_one(self):
        rb = _make_rebalancer()
        w = pd.Series({"AAA": 2.0, "BBB": 2.0})
        result = rb._validate_weights(w, pd.Index(["AAA", "BBB"]))
        assert abs(result.sum() - 1.0) < 1e-9

    def test_clips_negative_to_zero(self):
        rb = _make_rebalancer()
        w = pd.Series({"AAA": -0.5, "BBB": 1.5})
        result = rb._validate_weights(w, pd.Index(["AAA", "BBB"]))
        assert (result >= 0).all()

    def test_clips_to_max_weight_per_ticker(self):
        # 클리핑 후 재정규화하므로, 클리핑된 합이 1.0 이상이어야 결과도 상한을 유지한다.
        rb = _make_rebalancer(max_weight_per_ticker=0.4)
        w = pd.Series({"AAA": 1.0, "BBB": 1.0, "CCC": 1.0})
        result = rb._validate_weights(w, pd.Index(["AAA", "BBB", "CCC"]))
        assert (result <= 0.4 + 1e-9).all()
        assert abs(result.sum() - 1.0) < 1e-9

    def test_unknown_tickers_dropped(self):
        rb = _make_rebalancer()
        w = pd.Series({"AAA": 0.5, "ZZZ": 0.5})
        result = rb._validate_weights(w, pd.Index(["AAA", "BBB"]))
        assert "ZZZ" not in result.index


# ── _get_current_weights ─────────────────────────────────────────

class TestGetCurrentWeights:
    def test_basic_calculation(self):
        rb = _make_rebalancer()
        balance = _balance(cash=0, holdings=[_holding("AAA", 10, 1_000), _holding("BBB", 5, 2_000)])
        weights = rb._get_current_weights(balance, total_assets=20_000)
        assert weights["AAA"] == pytest.approx(0.5)
        assert weights["BBB"] == pytest.approx(0.5)


# ── _plan_orders ──────────────────────────────────────────────────

class TestPlanOrders:
    def test_sell_orders_listed_before_buy_orders(self):
        rb = _make_rebalancer(rebalance_threshold=0.03, min_order_amount=1_000)
        current = {"AAA": 0.5, "BBB": 0.0}
        target = pd.Series({"AAA": 0.0, "BBB": 0.5})
        prices = {"AAA": 10_000, "BBB": 10_000}
        orders, _ = rb._plan_orders(current, target, prices, total_assets=1_000_000, available_cash=1_000_000)
        sides = [o.side for o in orders]
        assert sides.index("sell") < sides.index("buy")

    def test_threshold_skip_small_diff(self):
        rb = _make_rebalancer(rebalance_threshold=0.05, min_order_amount=1_000)
        current = {"AAA": 0.30}
        target = pd.Series({"AAA": 0.32})  # diff=2% < 5% threshold
        prices = {"AAA": 10_000}
        orders, skipped = rb._plan_orders(current, target, prices, total_assets=1_000_000, available_cash=1_000_000)
        assert orders == []
        assert skipped == 1

    def test_full_liquidation_bypasses_threshold(self):
        # threshold가 매우 커도 target=0·현재보유>0인 완전 청산은 예외적으로 거래되어야 함
        rb = _make_rebalancer(rebalance_threshold=0.50, min_order_amount=1_000)
        current = {"AAA": 0.10}
        target = pd.Series({"AAA": 0.0})
        prices = {"AAA": 10_000}
        orders, _ = rb._plan_orders(current, target, prices, total_assets=1_000_000, available_cash=1_000_000)
        assert len(orders) == 1
        assert orders[0].side == "sell"

    def test_min_order_amount_skip(self):
        rb = _make_rebalancer(rebalance_threshold=0.0, min_order_amount=100_000)
        current = {"AAA": 0.50}
        target = pd.Series({"AAA": 0.501})  # diff_amount = 1,000원 (소액)
        prices = {"AAA": 10_000}
        orders, skipped = rb._plan_orders(current, target, prices, total_assets=1_000_000, available_cash=1_000_000)
        assert orders == []
        assert skipped == 1

    def test_zero_price_ticker_skipped(self):
        rb = _make_rebalancer()
        target = pd.Series({"AAA": 1.0})
        orders, skipped = rb._plan_orders({}, target, {"AAA": 0}, total_assets=1_000_000, available_cash=1_000_000)
        assert orders == []
        assert skipped == 1

    def test_buy_capped_by_available_cash(self):
        rb = _make_rebalancer(rebalance_threshold=0.0, min_order_amount=1_000)
        target = pd.Series({"AAA": 1.0})
        prices = {"AAA": 10_000}
        # 총자산은 100만원이지만 실제 가용현금은 10만원뿐인 상황
        orders, _ = rb._plan_orders({}, target, prices, total_assets=1_000_000, available_cash=100_000)
        assert len(orders) == 1
        bought_amount = orders[0].qty * orders[0].price
        assert bought_amount <= 100_000 * _BUY_CASH_RATIO + 1e-6


# ── _wait_for_sell_settlement ─────────────────────────────────────

class TestWaitForSellSettlement:
    def test_no_cash_api_returns_immediately(self):
        rb = _make_rebalancer()
        rb.broker = _NoCashApiBroker()
        result_cash = rb._wait_for_sell_settlement(pre_sell_raw_cash=1_000_000, expected_proceeds=500_000)
        assert result_cash == int((1_000_000 + 500_000) * _DEFAULT_AVAILABLE_RATIO)

    def test_immediate_success_no_sleep(self, monkeypatch):
        rb = _make_rebalancer()
        rb.broker = FakeBroker(_balance(0), available_cash_seq=[5_000_000])
        sleep_calls = []
        monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

        result_cash = rb._wait_for_sell_settlement(pre_sell_raw_cash=1_000_000, expected_proceeds=1_000_000)

        assert sleep_calls == []  # 목표 즉시 충족 → 대기 없음
        assert result_cash == int(5_000_000 * _KIS_AVAILABLE_RATIO)

    def test_timeout_returns_latest_available_cash(self, monkeypatch):
        rb = _make_rebalancer()
        rb.broker = FakeBroker(_balance(0), available_cash_seq=[100])  # 목표에 끝까지 못 미침

        fake_now = [0.0]
        monkeypatch.setattr(time, "time", lambda: fake_now[0])
        monkeypatch.setattr(time, "sleep", lambda s: fake_now.__setitem__(0, fake_now[0] + s))

        result_cash = rb._wait_for_sell_settlement(pre_sell_raw_cash=100, expected_proceeds=1_000_000)

        assert result_cash == int(100 * _KIS_AVAILABLE_RATIO)
        assert fake_now[0] >= 30.0  # 타임아웃(30s)까지 대기했는지 확인


# ── run() 통합 테스트 ──────────────────────────────────────────────

class TestRunIntegration:
    def test_zero_total_assets_returns_early(self):
        rb = _make_rebalancer(broker=FakeBroker(_balance(cash=0)))
        result = rb.run()
        assert result.total_assets == 0
        assert result.orders == []

    def test_missing_price_data_returns_early(self):
        rb = _make_rebalancer(broker=FakeBroker(_balance(cash=1_000_000)), price_data=None)
        result = rb.run()
        assert result.orders == []

    def test_dry_run_does_not_call_broker_orders(self):
        balance = _balance(cash=500_000, holdings=[_holding("AAA", 50, 10_000)])
        broker = FakeBroker(balance)
        prices = pd.DataFrame({"AAA": [10_000] * 3, "BBB": [10_000] * 3})

        rb = PortfolioRebalancer(
            broker=broker,
            strategy_fn=lambda p: pd.Series({"AAA": 0.0, "BBB": 1.0}),
            price_data=prices,
            rebalance_threshold=0.01,
            min_order_amount=1_000,
            dry_run=True,
        )
        result = rb.run()

        assert broker.buy_calls == []
        assert broker.sell_calls == []
        assert result.success_count > 0

    def test_real_run_sells_then_buys_after_settlement(self, monkeypatch):
        balance = _balance(cash=100_000, holdings=[_holding("AAA", 50, 10_000)])
        # 매도 전 가용현금은 낮고, 매도 체결 후 충분히 올라가는 상황을 시뮬레이션
        broker = FakeBroker(balance, available_cash_seq=[100_000, 600_000])
        prices = pd.DataFrame({"AAA": [10_000] * 3, "BBB": [10_000] * 3})
        monkeypatch.setattr(time, "sleep", lambda s: None)

        rb = PortfolioRebalancer(
            broker=broker,
            strategy_fn=lambda p: pd.Series({"AAA": 0.0, "BBB": 1.0}),
            price_data=prices,
            rebalance_threshold=0.01,
            min_order_amount=1_000,
            dry_run=False,
        )
        result = rb.run()

        assert len(broker.sell_calls) == 1
        assert broker.sell_calls[0][0] == "AAA"
        assert len(broker.buy_calls) == 1
        assert broker.buy_calls[0][0] == "BBB"
        assert result.success_count == 2
        assert result.fail_count == 0
