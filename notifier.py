"""
알림 모듈 (Telegram)
────────────────────────────────────────────────────────────────
리밸런싱 결과, 리스크 경고, 오류, 일일 리포트를 텔레그램으로 전송합니다.

.env 설정:
    TELEGRAM_BOT_TOKEN=1234567890:ABCDEF...
    TELEGRAM_CHAT_ID=123456789

미설정 시 로컬 로그에만 기록됩니다.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING

import requests
from loguru import logger
from dotenv import load_dotenv

if TYPE_CHECKING:
    from portfolio.rebalancer import RebalanceResult
    from risk.guard import RiskCheckResult

load_dotenv()


class Notifier:
    """텔레그램 + 로컬 로그 알림"""

    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")

    EMOJI = {
        "normal":  "✅",
        "warn":    "⚠️",
        "reduce":  "🟠",
        "halt":    "🔴",
        "rebal":   "♻️",
        "error":   "❌",
        "start":   "🚀",
        "heart":   "🟢",
        "clock":   "🕒",
    }

    # ── 공개 메서드 ────────────────────────────────────

    def send_rebalance_report(
        self,
        result: "RebalanceResult",
        strategy_name: str = "",
    ) -> None:
        """리밸런싱 완료 보고"""
        emoji = self.EMOJI["rebal"]
        title = f"{emoji} <b>리밸런싱 완료</b>" + (f" — {strategy_name}" if strategy_name else "")

        if result.orders:
            lines = []
            for o in result.orders:
                side = "매수↑" if o.side == "buy" else "매도↓"
                lines.append(
                    f"  • {o.name[:14]} | {side} {o.qty}주 @{o.price:,}원 "
                    f"({o.current_weight*100:.1f}%→{o.target_weight*100:.1f}%)"
                )
            orders_text = "\n".join(lines)
        else:
            orders_text = "  변경 없음 (임계값 이내)"

        message = (
            f"{title}\n"
            f"<pre>"
            f"총 자산:  {result.total_assets:>14,.0f} 원\n"
            f"회전율:   {result.total_turnover*100:>13.1f} %\n"
            f"성공: {result.success_count}건 | 실패: {result.fail_count}건 | 스킵: {result.skipped_count}건\n"
            f"실행시각: {result.executed_at[:16]}"
            f"</pre>\n"
            f"<b>주문 내역</b>\n{orders_text}"
        )
        self._send(message, level="info")

    def send_risk_alert(
        self,
        result: "RiskCheckResult",
        total_assets: float = 0,
    ) -> None:
        """리스크 경고 알림"""
        emoji = self.EMOJI.get(result.action, "⚠️")
        level = "error" if result.action == "halt" else "warning"

        message = (
            f"<b>{emoji} 리스크 알림 [{result.action.upper()}]</b>\n"
            f"<pre>"
            f"사유:      {result.reason}\n"
            f"현재 MDD:  {result.current_mdd*100:.2f}%\n"
            f"일간 손실: {result.daily_loss*100:.2f}%\n"
            f"총 자산:   {total_assets:,.0f}원"
            f"</pre>"
        )
        self._send(message, level=level)

    def send_startup(
        self,
        mode: str,
        strategy_name: str,
        total_assets: float,
    ) -> None:
        """봇 시작 알림"""
        message = (
            f"<b>{self.EMOJI['start']} ETF 퀀트봇 시작</b>\n"
            f"<pre>"
            f"모드:      {mode.upper()}\n"
            f"전략:      {strategy_name}\n"
            f"총 자산:   {total_assets:,.0f}원\n"
            f"시작시각:  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            f"</pre>"
        )
        self._send(message, level="info")

    def send_daily_report(
        self,
        total_assets: float,
        total_pnl: float,
        total_pnl_rate: float,
        current_mdd: float,
        strategy_name: str,
        is_halted: bool,
    ) -> None:
        """일일 하트비트 리포트"""
        emoji  = self.EMOJI["halt"] if is_halted else self.EMOJI["heart"]
        halted = "YES ⚠️" if is_halted else "NO"
        message = (
            f"<b>{emoji} 일일 리포트</b> ({datetime.now().strftime('%Y-%m-%d')})\n"
            f"<pre>"
            f"총 자산:   {total_assets:>14,.0f} 원\n"
            f"일간 손익: {total_pnl:>+14,.0f} 원 ({total_pnl_rate:+.2f}%)\n"
            f"MDD:       {current_mdd*100:>12.2f} %\n"
            f"전략:      {strategy_name}\n"
            f"거래중단:  {halted}"
            f"</pre>"
        )
        self._send(message, level="info")

    def send_error(self, error: str, context: str = "") -> None:
        """오류 알림"""
        message = (
            f"<b>{self.EMOJI['error']} 오류 발생</b>\n"
            f"<pre>"
            f"{context + ': ' if context else ''}{error}\n"
            f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            f"</pre>"
        )
        self._send(message, level="error")

    def send_text(self, text: str) -> None:
        """단순 텍스트 메시지"""
        self._send(text, level="info")

    # ── 내부 전송 ──────────────────────────────────────

    def _send(self, message: str, level: str = "info") -> None:
        log_fn = {
            "info":    logger.info,
            "warning": logger.warning,
            "error":   logger.error,
        }.get(level, logger.info)
        log_fn(f"[알림] {message[:200]}")

        if not self.BOT_TOKEN or not self.CHAT_ID:
            return

        url     = f"https://api.telegram.org/bot{self.BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id":    self.CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
        }

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = requests.post(url, json=payload, timeout=5)
                if resp.status_code == 200:
                    return
                last_exc = Exception(f"HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                last_exc = e
            if attempt < 3:
                time.sleep(2 ** attempt)
        logger.warning(f"텔레그램 전송 최종 실패 (3회 시도): {last_exc}")
