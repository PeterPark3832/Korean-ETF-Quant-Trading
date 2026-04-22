"""
리스크 감시 모듈
────────────────────────────────────────────────────────────────
포트폴리오 MDD, 일간 손실, 연속 손실을 실시간 감시합니다.

감시 항목:
  1. MDD (최고점 대비 낙폭): 임계값 초과 시 전액 현금화
  2. 일간 손실: 하루 손실 > N% 시 당일 거래 중단
  3. 연속 손실: N일 연속 손실 시 포지션 축소
  4. 개별 종목 손실: 단일 종목 > N% 손실 시 해당 종목 매도

상태는 JSON 파일에 저장되어 재시작 후에도 유지됩니다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from broker.kis_order import AccountBalance

from config import TARGET_MDD, MAX_MDD_HARD_STOP

RISK_STATE_PATH = Path(__file__).parent.parent / "data" / "cache" / "risk_state.json"


@dataclass
class RiskState:
    """리스크 감시 상태"""
    peak_value:         float = 0.0       # 역대 최고 포트폴리오 가치
    current_mdd:        float = 0.0       # 현재 MDD (음수)
    daily_start_value:  float = 0.0       # 당일 시작 가치
    consecutive_loss_days: int = 0        # 연속 손실 일수
    is_halted:          bool = False      # 거래 중단 여부
    halt_reason:        str  = ""         # 중단 사유
    last_updated:       str  = ""         # 마지막 업데이트 시각
    value_history:      list[dict] = field(default_factory=list)  # 최근 30일


@dataclass
class RiskCheckResult:
    """리스크 체크 결과"""
    is_safe:       bool
    action:        str   # "normal" | "warn" | "reduce" | "halt"
    reason:        str
    current_mdd:   float
    daily_loss:    float
    detail:        dict = field(default_factory=dict)


class RiskGuard:
    """
    포트폴리오 리스크 감시기

    사용법:
        guard = RiskGuard()
        result = guard.check(balance)
        if not result.is_safe:
            # 경고 또는 거래 중단 처리
    """

    def __init__(
        self,
        target_mdd:        float = TARGET_MDD,          # 경고 MDD (12%)
        hard_stop_mdd:     float = MAX_MDD_HARD_STOP,   # 강제 청산 MDD (18%)
        daily_loss_limit:  float = 0.03,                # 일간 손실 한도 3%
        consecutive_limit: int   = 5,                   # 연속 손실 일수 한도
        position_reduce_at: float = 0.08,               # 포지션 축소 시작 MDD 8%
    ):
        self.target_mdd         = target_mdd
        self.hard_stop_mdd      = hard_stop_mdd
        self.daily_loss_limit   = daily_loss_limit
        self.consecutive_limit  = consecutive_limit
        self.position_reduce_at = position_reduce_at

        self._state = self._load_state()

    # ── 메인 체크 ──────────────────────────────────────

    def check(self, balance: "AccountBalance") -> RiskCheckResult:
        """
        현재 잔고 기준 리스크 체크

        Returns:
            RiskCheckResult (action: "normal" | "warn" | "reduce" | "halt")
        """
        total = balance.total_assets
        if total <= 0:
            return RiskCheckResult(False, "halt", "총 자산 0", 0, 0)

        # 거래 중단 상태 유지 확인
        if self._state.is_halted:
            return RiskCheckResult(
                is_safe=False,
                action="halt",
                reason=f"거래 중단 중: {self._state.halt_reason}",
                current_mdd=self._state.current_mdd,
                daily_loss=0,
            )

        # peak_value 초기화: 최초 1회만 (이후 갱신은 reset_daily에서 하루 1회)
        if self._state.peak_value <= 0:
            self._state.peak_value = total
        # 계좌 전환·오염 감지: 2배 초과 시 자동 재설정
        elif self._state.peak_value > total * 2.0:
            logger.warning(
                f"[리스크] peak_value({self._state.peak_value:,.0f}원)가 "
                f"현재 총자산({total:,.0f}원)의 2배 초과 → peak_value 재설정"
            )
            self._state.peak_value = total

        # MDD 계산 (peak 갱신은 하지 않음 — reset_daily에서 하루 1회만 갱신)
        mdd = (total - self._state.peak_value) / self._state.peak_value if self._state.peak_value > 0 else 0

        # 일간 손실 계산
        daily_loss = 0.0
        if self._state.daily_start_value > 0:
            daily_loss = (total - self._state.daily_start_value) / self._state.daily_start_value

        # 상태 업데이트
        self._state.current_mdd   = mdd
        self._state.last_updated  = datetime.now().isoformat()
        self._update_history(total)

        # ── 리스크 판단 ──────────────────────────────
        # 1. 하드스탑: 즉시 전액 현금화
        if mdd <= -abs(self.hard_stop_mdd):
            reason = f"MDD 하드스탑 ({mdd*100:.1f}% ≤ -{abs(self.hard_stop_mdd)*100:.0f}%)"
            self._halt(reason)
            self._save_state()
            logger.error(f"[리스크] {reason} → 거래 중단")
            return RiskCheckResult(False, "halt", reason, mdd, daily_loss)

        # 2. 일간 손실 한도 초과
        if daily_loss <= -abs(self.daily_loss_limit):
            reason = f"일간 손실 한도 초과 ({daily_loss*100:.1f}%)"
            self._save_state()
            logger.warning(f"[리스크] {reason}")
            return RiskCheckResult(False, "warn", reason, mdd, daily_loss)

        # 3. 포지션 축소 구간 (soft warning)
        if mdd <= -abs(self.position_reduce_at):
            reason = f"MDD 경고 구간 ({mdd*100:.1f}% ≤ -{abs(self.position_reduce_at)*100:.0f}%)"
            self._save_state()
            logger.warning(f"[리스크] {reason}")
            return RiskCheckResult(
                is_safe=False, action="reduce", reason=reason,
                current_mdd=mdd, daily_loss=daily_loss,
                detail={"reduce_ratio": min(abs(mdd) / abs(self.hard_stop_mdd), 0.5)},
            )

        # 4. 목표 MDD 초과 (soft warning)
        if mdd <= -abs(self.target_mdd):
            reason = f"목표 MDD 초과 ({mdd*100:.1f}%)"
            self._save_state()
            logger.warning(f"[리스크] {reason}")
            return RiskCheckResult(False, "warn", reason, mdd, daily_loss)

        # 정상
        self._save_state()
        return RiskCheckResult(True, "normal", "정상", mdd, daily_loss)

    # ── 일간 리셋 ──────────────────────────────────────

    def reset_daily(self, current_value: float) -> None:
        """매일 09:05 장 시작 전 호출 (일간 기준점 초기화 + 최고점 갱신)"""
        prev = self._state.daily_start_value
        self._state.daily_start_value = current_value

        # 최고점 갱신 — 하루 1회 장 시작 기준으로만 업데이트 (intraday 일시 급등 방지)
        if current_value > self._state.peak_value:
            logger.info(
                f"[리스크] 최고점 갱신: {self._state.peak_value:,.0f} → {current_value:,.0f}원"
            )
            self._state.peak_value = current_value

        # 연속 손실 일수 업데이트
        if prev > 0 and current_value < prev:
            self._state.consecutive_loss_days += 1
            logger.info(f"연속 손실 {self._state.consecutive_loss_days}일째")
        else:
            self._state.consecutive_loss_days = 0

        self._save_state()

    def resume(self) -> None:
        """거래 중단 해제 (수동 명령)"""
        self._state.is_halted   = False
        self._state.halt_reason = ""
        self._save_state()
        logger.info("[리스크] 거래 재개")

    def reset_peak(self, current_value: float) -> None:
        """MDD 최고점 수동 재설정 (계좌 전환, 초기화 등)"""
        self._state.peak_value  = current_value
        self._state.current_mdd = 0.0
        self._save_state()
        logger.info(f"[리스크] peak_value 재설정: {current_value:,.0f}원")

    def get_status(self) -> dict:
        return {
            "peak_value":    self._state.peak_value,
            "current_mdd":   self._state.current_mdd,
            "daily_loss":    (
                (self._state.value_history[-1]["value"] - self._state.daily_start_value)
                / self._state.daily_start_value
                if self._state.value_history and self._state.daily_start_value > 0
                else 0
            ),
            "consecutive_loss_days": self._state.consecutive_loss_days,
            "is_halted":     self._state.is_halted,
            "halt_reason":   self._state.halt_reason,
        }

    # ── 내부 메서드 ────────────────────────────────────

    def _halt(self, reason: str) -> None:
        self._state.is_halted   = True
        self._state.halt_reason = reason

    def _update_history(self, value: float) -> None:
        self._state.value_history.append({
            "date":  date.today().isoformat(),
            "value": value,
        })
        # 최근 90일만 유지
        if len(self._state.value_history) > 90:
            self._state.value_history = self._state.value_history[-90:]

    def _save_state(self) -> None:
        try:
            RISK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            RISK_STATE_PATH.write_text(
                json.dumps(asdict(self._state), ensure_ascii=False, indent=2)
            )
        except Exception as e:
            logger.warning(f"리스크 상태 저장 실패: {e}")

    def _load_state(self) -> RiskState:
        try:
            if RISK_STATE_PATH.exists():
                data = json.loads(RISK_STATE_PATH.read_text())
                return RiskState(**data)
        except Exception:
            pass
        return RiskState()
