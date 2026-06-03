"""
risk/guard.py 단위 테스트
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from risk.guard import RiskGuard, RiskState, RiskCheckResult


def make_balance(total_assets: float):
    """AccountBalance 유사 Mock 객체"""
    b = MagicMock()
    b.total_assets = total_assets
    return b


class TestRiskGuardCheck:
    def test_normal_state_returns_safe(self, tmp_path):
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard()
            guard._state.peak_value = 10_000_000
            guard._state.daily_start_value = 10_000_000
            guard._state.daily_start_date = "2024-01-01"
            result = guard.check(make_balance(10_000_000))
            assert result.is_safe is True
            assert result.action == "normal"

    def test_hard_stop_triggers_halt(self, tmp_path):
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard(hard_stop_mdd=0.18)
            guard._state.peak_value = 10_000_000
            # 20% 하락 → 하드스탑 초과
            result = guard.check(make_balance(8_000_000))
            assert result.action == "halt"
            assert result.is_safe is False
            assert guard._state.is_halted is True

    def test_daily_loss_limit_warns(self, tmp_path):
        from datetime import date
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard(daily_loss_limit=0.03)
            guard._state.peak_value = 10_000_000
            guard._state.daily_start_value = 10_000_000
            guard._state.daily_start_date = date.today().isoformat()
            # 4% 일간 손실
            result = guard.check(make_balance(9_600_000))
            assert result.action == "warn"
            assert result.is_safe is False

    def test_halted_state_blocks_trading(self, tmp_path):
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard()
            guard._state.is_halted = True
            guard._state.halt_reason = "테스트 중단"
            result = guard.check(make_balance(10_000_000))
            assert result.action == "halt"
            assert result.is_safe is False

    def test_zero_assets_halts(self, tmp_path):
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard()
            result = guard.check(make_balance(0))
            assert result.is_safe is False

    def test_resume_clears_halt(self, tmp_path):
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard()
            guard._state.is_halted = True
            guard.resume()
            assert guard._state.is_halted is False
            assert guard._state.halt_reason == ""

    def test_reset_peak_resets_mdd(self, tmp_path):
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard()
            guard._state.peak_value = 15_000_000
            guard._state.current_mdd = -0.20
            guard.reset_peak(10_000_000)
            assert guard._state.peak_value == 10_000_000
            assert guard._state.current_mdd == 0.0

    def test_get_status_returns_dict(self, tmp_path):
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard()
            guard._state.peak_value = 10_000_000
            status = guard.get_status()
            assert "peak_value" in status
            assert "current_mdd" in status
            assert "is_halted" in status

    def test_state_persists_and_loads(self, tmp_path):
        state_path = tmp_path / "risk_state.json"
        with patch("risk.guard.RISK_STATE_PATH", state_path):
            guard = RiskGuard()
            guard._state.peak_value = 12_345_678
            guard._save_state()
            # 새 인스턴스로 로드
            guard2 = RiskGuard()
            assert guard2._state.peak_value == 12_345_678

    def test_adjust_capital_modifies_peak(self, tmp_path):
        with patch("risk.guard.RISK_STATE_PATH", tmp_path / "risk_state.json"):
            guard = RiskGuard()
            guard._state.peak_value = 10_000_000
            guard._state.daily_start_value = 10_000_000
            guard.adjust_capital(1_000_000)
            assert guard._state.peak_value == 11_000_000
            assert guard._state.daily_start_value == 11_000_000
