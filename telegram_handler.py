"""
텔레그램 봇 명령어 처리기
────────────────────────────────────────────────────────────────
getUpdates 롱폴링 방식으로 명령어를 수신하고 즉시 처리합니다.

지원 명령어:
  /help           - 명령어 목록
  /status         - 현재 잔고 및 포트폴리오
  /rebalance      - 리밸런싱 계획 조회 (드라이런)
  /rebalance now  - 즉시 리밸런싱 실행
  /halt           - 거래 중단
  /resume         - 거래 재개
  /report         - 성과 리포트

보안: TELEGRAM_CHAT_ID 에 등록된 사용자만 응답합니다.
"""
from __future__ import annotations

import os
import threading
import time
from typing import TYPE_CHECKING

import requests
from loguru import logger
from dotenv import load_dotenv

if TYPE_CHECKING:
    from scheduler import ETFQuantBot
    from notifier import Notifier
    from reports.reporter import PerformanceReporter

load_dotenv()


class TelegramCommandHandler:
    """
    텔레그램 명령어 수신 + 실행

    사용법:
        handler = TelegramCommandHandler(bot, notifier, reporter)
        handler.start()
    """

    HELP_TEXT = (
        "<b>📋 ETF 퀀트봇 명령어</b>\n\n"
        "  <code>/status</code>          — 잔고·포트폴리오 조회\n"
        "  <code>/rebalance</code>        — 리밸런싱 계획 (드라이런)\n"
        "  <code>/rebalance now</code>    — 즉시 리밸런싱 실행\n"
        "  <code>/report</code>           — 성과 리포트\n"
        "  <code>/halt</code>             — 거래 중단\n"
        "  <code>/resume</code>           — 거래 재개\n"
        "  <code>/resetmdd</code>         — MDD 최고점 재설정\n"
        "  <code>/help</code>             — 이 목록"
    )

    def __init__(
        self,
        bot:      "ETFQuantBot",
        notifier: "Notifier",
        reporter: "PerformanceReporter | None" = None,
    ):
        self.bot      = bot
        self.notifier = notifier
        self.reporter = reporter

        self._token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self._offset  = 0
        self._running = False

    # ── 시작 / 종료 ────────────────────────────────────

    def start(self) -> None:
        if not self._token or not self._chat_id:
            logger.warning("[TelegramCmd] 봇 토큰/채팅 ID 미설정 → 명령어 수신 비활성")
            return
        self._running = True
        t = threading.Thread(target=self._poll_loop, daemon=True, name="tg-cmd")
        t.start()
        logger.info("[TelegramCmd] 명령어 수신 시작")

    def stop(self) -> None:
        self._running = False

    # ── 롱폴링 루프 ────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = self._get_updates(timeout=25)
                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    msg     = upd.get("message", {})
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    text    = (msg.get("text") or "").strip()

                    if not text.startswith("/"):
                        continue
                    if chat_id != self._chat_id:
                        logger.warning(f"[TelegramCmd] 미등록 chat_id 차단: {chat_id}")
                        continue

                    self._dispatch(text)

            except Exception as e:
                logger.warning(f"[TelegramCmd] 폴링 오류: {e}")
                time.sleep(5)

    def _get_updates(self, timeout: int = 25) -> list[dict]:
        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        try:
            resp = requests.get(
                url,
                params={"offset": self._offset, "timeout": timeout},
                timeout=timeout + 5,
            )
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
        except Exception:
            pass
        return []

    # ── 명령어 디스패치 ────────────────────────────────

    def _dispatch(self, text: str) -> None:
        cmd = text.lower().split("@")[0]   # /rebalance@botname → /rebalance
        logger.info(f"[TelegramCmd] 수신: {cmd}")

        try:
            if cmd == "/help":
                self.notifier.send_text(self.HELP_TEXT)

            elif cmd == "/status":
                self._cmd_status()

            elif cmd == "/rebalance":
                self._cmd_rebalance(dry_run=True)

            elif cmd == "/rebalance now":
                self._cmd_rebalance(dry_run=False)

            elif cmd == "/halt":
                self._cmd_halt()

            elif cmd == "/resume":
                self._cmd_resume()

            elif cmd == "/resetmdd":
                self._cmd_reset_mdd()

            elif cmd == "/report":
                self._cmd_report()

            else:
                self.notifier.send_text(
                    f"❓ 알 수 없는 명령어: <code>{text}</code>\n"
                    "/help 로 목록 확인"
                )
        except Exception as e:
            logger.error(f"[TelegramCmd] 명령 처리 오류 ({cmd}): {e}")
            self.notifier.send_error(str(e), f"명령어: {cmd}")

    # ── 명령어 핸들러 ──────────────────────────────────

    def _cmd_status(self) -> None:
        self.notifier.send_text("🔍 잔고 조회 중...")
        balance = self.bot.broker.get_balance()
        risk_st = self.bot.guard.get_status()

        total = balance.total_assets
        if balance.holdings:
            rows = []
            for h in sorted(balance.holdings, key=lambda x: x.eval_amount, reverse=True):
                w   = h.eval_amount / total * 100 if total > 0 else 0
                rows.append(
                    f"  {h.ticker} {h.name[:10]:10s} "
                    f"{w:>5.1f}% {h.profit_rate:>+6.1f}%"
                )
            holdings_text = "\n".join(rows)
        else:
            holdings_text = "  보유 종목 없음"

        halted = "🔴 거래중단" if risk_st["is_halted"] else "🟢 정상"
        msg = (
            f"<b>📊 포트폴리오 현황</b>\n"
            f"<pre>"
            f"총 자산:  {total:>14,.0f} 원\n"
            f"예수금:   {balance.cash:>14,.0f} 원\n"
            f"손  익:   {balance.total_pnl:>+13,.0f} 원  ({balance.total_pnl_rate:+.2f}%)\n"
            f"MDD:      {risk_st['current_mdd']*100:>13.2f} %\n"
            f"상  태:   {halted}\n"
            f"{'─'*38}\n"
            f"  코드   종목명       비중  수익률\n"
            f"{holdings_text}"
            f"</pre>"
        )
        self.notifier.send_text(msg)

    def _cmd_rebalance(self, dry_run: bool) -> None:
        if dry_run:
            self.notifier.send_text(
                "🔍 리밸런싱 계획 조회 중...\n"
                "실제 실행: <code>/rebalance now</code>"
            )
        else:
            self.notifier.send_text("⚙️ 즉시 리밸런싱 실행 중...")

        orig = self.bot.dry_run
        self.bot.dry_run = dry_run
        try:
            self.bot.job_monthly_rebalance()
        finally:
            self.bot.dry_run = orig

    def _cmd_halt(self) -> None:
        self.bot.guard._halt("텔레그램 수동 중단")
        self.bot.guard._save_state()
        self.notifier.send_text(
            "🔴 거래가 <b>중단</b>되었습니다.\n"
            "재개하려면 <code>/resume</code>"
        )

    def _cmd_resume(self) -> None:
        self.bot.guard.resume()
        self.notifier.send_text("🟢 거래가 <b>재개</b>되었습니다.")

    def _cmd_reset_mdd(self) -> None:
        balance = self.bot.broker.get_balance()
        self.bot.guard.reset_peak(balance.total_assets)
        self.notifier.send_text(
            f"✅ MDD 최고점이 현재 총자산 기준으로 재설정되었습니다.\n"
            f"새 기준: <b>{balance.total_assets:,.0f}원</b> (MDD 0.00%)"
        )

    def _cmd_report(self) -> None:
        if self.reporter:
            self.notifier.send_text(self.reporter.monthly_report_text())
        else:
            self.notifier.send_text("⚠️ 성과 리포터가 초기화되지 않았습니다.")
