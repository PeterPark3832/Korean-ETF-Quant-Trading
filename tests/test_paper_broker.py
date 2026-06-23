"""
PaperBroker 시뮬레이션 정확도(수수료·슬리피지·잔액 처리) 단위 테스트
"""
import json

import pytest

import broker.paper_broker as paper_broker_module
from broker.paper_broker import PaperBroker
from config import TRANSACTION_COST, SLIPPAGE


@pytest.fixture(autouse=True)
def _isolated_state_path(tmp_path, monkeypatch):
    """실제 paper_state.json을 건드리지 않도록 격리된 경로로 교체."""
    monkeypatch.setattr(paper_broker_module, "PAPER_STATE_PATH", tmp_path / "paper_state.json")


def _broker(initial_cash=10_000_000, prices: dict | None = None) -> PaperBroker:
    prices = prices or {}
    return PaperBroker(
        initial_cash=initial_cash,
        price_fetcher=lambda ticker: prices.get(ticker, 0),
    )


# ── order_buy ────────────────────────────────────────────────────

class TestOrderBuy:
    def test_applies_positive_slippage_and_commission(self):
        b = _broker(prices={"AAA": 10_000})
        result = b.order_buy("AAA", qty=10)
        expected_price = int(10_000 * (1 + SLIPPAGE))
        assert result.success
        assert result.price == expected_price
        expected_cost = expected_price * 10
        expected_commission = expected_cost * TRANSACTION_COST
        assert b._cash == pytest.approx(10_000_000 - expected_cost - expected_commission)

    def test_uses_explicit_price_over_fetcher(self):
        b = _broker(prices={"AAA": 99_999})
        result = b.order_buy("AAA", qty=1, price=10_000)
        assert result.price == int(10_000 * (1 + SLIPPAGE))

    def test_zero_qty_rejected(self):
        b = _broker(prices={"AAA": 10_000})
        result = b.order_buy("AAA", qty=0)
        assert not result.success

    def test_price_fetch_failure_rejected(self):
        b = _broker(prices={})  # fetcher returns 0
        result = b.order_buy("AAA", qty=1)
        assert not result.success
        assert "현재가" in result.message

    def test_insufficient_cash_caps_qty(self):
        b = _broker(initial_cash=100_000, prices={"AAA": 10_000})
        result = b.order_buy("AAA", qty=1_000)  # 훨씬 많은 수량 요청
        assert result.success
        exec_price = int(10_000 * (1 + SLIPPAGE))
        total_cost = exec_price * result.qty * (1 + TRANSACTION_COST)
        assert total_cost <= 100_000 + 1e-6
        assert b._cash >= 0

    def test_insufficient_cash_for_even_one_share_fails(self):
        b = _broker(initial_cash=100, prices={"AAA": 10_000})
        result = b.order_buy("AAA", qty=1)
        assert not result.success
        assert "잔액 부족" in result.message

    def test_weighted_average_price_after_multiple_buys(self):
        b = _broker(initial_cash=100_000_000, prices={"AAA": 10_000})
        b.order_buy("AAA", qty=10, price=10_000)
        b.order_buy("AAA", qty=10, price=20_000)
        p1 = int(10_000 * (1 + SLIPPAGE))
        p2 = int(20_000 * (1 + SLIPPAGE))
        expected_avg = (p1 * 10 + p2 * 10) / 20
        assert b._avg_price["AAA"] == pytest.approx(expected_avg)
        assert b._holdings["AAA"] == 20


# ── order_sell ───────────────────────────────────────────────────

class TestOrderSell:
    def test_applies_negative_slippage_and_commission(self):
        b = _broker(initial_cash=0, prices={"AAA": 10_000})
        b._holdings["AAA"] = 10
        b._avg_price["AAA"] = 10_000
        result = b.order_sell("AAA", qty=10, price=10_000)
        expected_price = int(10_000 * (1 - SLIPPAGE))
        assert result.success
        assert result.price == expected_price
        proceeds = expected_price * 10
        commission = proceeds * TRANSACTION_COST
        assert b._cash == pytest.approx(proceeds - commission)

    def test_no_holdings_rejected(self):
        b = _broker(prices={"AAA": 10_000})
        result = b.order_sell("AAA", qty=5)
        assert not result.success
        assert "보유 수량 없음" in result.message

    def test_oversell_caps_to_held_qty(self):
        b = _broker(prices={"AAA": 10_000})
        b._holdings["AAA"] = 5
        b._avg_price["AAA"] = 10_000
        result = b.order_sell("AAA", qty=999)
        assert result.success
        assert result.qty == 5

    def test_full_liquidation_removes_holding(self):
        b = _broker(prices={"AAA": 10_000})
        b._holdings["AAA"] = 5
        b._avg_price["AAA"] = 10_000
        b.order_sell("AAA", qty=5)
        assert "AAA" not in b._holdings
        assert "AAA" not in b._avg_price

    def test_price_fetch_failure_rejected(self):
        b = _broker(prices={})
        b._holdings["AAA"] = 5
        b._avg_price["AAA"] = 10_000
        result = b.order_sell("AAA", qty=1)
        assert not result.success


# ── get_balance ──────────────────────────────────────────────────

class TestGetBalance:
    def test_pnl_calculation(self):
        b = _broker(initial_cash=0, prices={"AAA": 12_000})
        b._holdings["AAA"] = 10
        b._avg_price["AAA"] = 10_000
        balance = b.get_balance()
        assert balance.total_eval == pytest.approx(120_000)
        assert balance.total_purchase == pytest.approx(100_000)
        assert balance.total_pnl == pytest.approx(20_000)
        assert balance.total_pnl_rate == pytest.approx(20.0)

    def test_total_assets_includes_cash_and_holdings(self):
        b = _broker(initial_cash=50_000, prices={"AAA": 10_000})
        b._holdings["AAA"] = 5
        b._avg_price["AAA"] = 10_000
        balance = b.get_balance()
        assert balance.total_assets == pytest.approx(50_000 + 50_000)

    def test_empty_portfolio(self):
        b = _broker(initial_cash=1_000_000)
        balance = b.get_balance()
        assert balance.holdings == []
        assert balance.total_assets == pytest.approx(1_000_000)


# ── get_max_buy_qty ──────────────────────────────────────────────

class TestGetMaxBuyQty:
    def test_accounts_for_cost_and_slippage(self):
        b = _broker(initial_cash=1_000_000)
        qty = b.get_max_buy_qty("AAA", price=10_000)
        effective_price = int(10_000 * (1 + TRANSACTION_COST + SLIPPAGE))
        assert qty == int(1_000_000 / effective_price)

    def test_zero_price_returns_zero(self):
        b = _broker(initial_cash=1_000_000)
        assert b.get_max_buy_qty("AAA", price=0) == 0


# ── 상태 영속화 ───────────────────────────────────────────────────

class TestStatePersistence:
    def test_save_and_reload_round_trip(self, tmp_path, monkeypatch):
        path = tmp_path / "paper_state.json"
        monkeypatch.setattr(paper_broker_module, "PAPER_STATE_PATH", path)

        b1 = _broker(initial_cash=1_000_000, prices={"AAA": 10_000})
        b1.order_buy("AAA", qty=10, price=10_000)
        assert path.exists()

        b2 = PaperBroker(price_fetcher=lambda t: 10_000)
        assert b2._cash == pytest.approx(b1._cash)
        assert b2._holdings == b1._holdings

    def test_reset_clears_state_and_deletes_file(self, tmp_path, monkeypatch):
        path = tmp_path / "paper_state.json"
        monkeypatch.setattr(paper_broker_module, "PAPER_STATE_PATH", path)

        b = _broker(initial_cash=1_000_000, prices={"AAA": 10_000})
        b.order_buy("AAA", qty=10, price=10_000)
        assert path.exists()

        b.reset(initial_cash=5_000_000)
        assert b._cash == 5_000_000
        assert b._holdings == {}
        assert not path.exists()
