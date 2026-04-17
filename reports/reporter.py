"""
성과 분석 리포터
────────────────────────────────────────────────────────────────
일간 NAV를 data/cache/performance.json 에 누적 기록하고
CAGR, MDD, 샤프지수, 월간 수익률 등을 계산합니다.

job_daily_close 에서 record_daily() 를 호출하면
/report 명령어와 월말 자동 리포트에 데이터가 공급됩니다.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import numpy as np
from loguru import logger

PERF_PATH = Path(__file__).parent.parent / "data" / "cache" / "performance.json"


class PerformanceReporter:
    """
    일간 NAV 누적 기록 + 성과 지표 계산 + 텔레그램 리포트 생성

    Args:
        strategy_name: 리포트에 표시할 전략명
    """

    def __init__(self, strategy_name: str = ""):
        self.strategy_name = strategy_name

    # ── 일간 NAV 기록 ──────────────────────────────────

    def record_daily(self, total_assets: float) -> None:
        """장 마감 후 호출 — 오늘 NAV를 history에 추가/갱신"""
        history = self._load()
        today   = date.today().isoformat()

        if history and history[-1]["date"] == today:
            history[-1]["nav"] = total_assets        # 당일 재기록
        else:
            history.append({"date": today, "nav": total_assets})

        if len(history) > 504:                       # 최근 2년치만 유지
            history = history[-504:]

        self._save(history)
        logger.debug(f"[Reporter] NAV 기록: {today} = {total_assets:,.0f}원 (총 {len(history)}일)")

    # ── 성과 지표 계산 ─────────────────────────────────

    def compute_metrics(self) -> dict:
        history = self._load()
        if len(history) < 2:
            return {}

        navs  = [h["nav"]  for h in history]
        dates = [h["date"] for h in history]
        rets  = np.diff(navs) / np.array(navs[:-1], dtype=float)

        # 운용 기간
        total_days   = (
            datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])
        ).days or 1

        # 누적 수익률 / CAGR
        total_return = navs[-1] / navs[0] - 1 if navs[0] > 0 else 0
        cagr = (1 + total_return) ** (365 / total_days) - 1

        # MDD
        peak, mdd = navs[0], 0.0
        for v in navs:
            if v > peak:
                peak = v
            dd = (v - peak) / peak
            if dd < mdd:
                mdd = dd

        # 샤프지수 (무위험 연 2.5% 가정)
        rf_daily = 0.025 / 252
        excess   = rets - rf_daily
        sharpe   = (
            excess.mean() / excess.std() * math.sqrt(252)
            if excess.std() > 0 else 0.0
        )

        # 이번 달 수익률
        this_month = date.today().strftime("%Y-%m")
        m_navs     = [h["nav"] for h in history if h["date"].startswith(this_month)]
        month_ret  = (m_navs[-1] / m_navs[0] - 1) if len(m_navs) >= 2 else 0.0

        # 최근 1개월(약 22거래일) 수익률
        recent     = navs[-22:]
        recent_ret = (recent[-1] / recent[0] - 1) if len(recent) >= 2 else 0.0

        return {
            "total_days":    total_days,
            "total_return":  total_return,
            "cagr":          cagr,
            "mdd":           mdd,
            "sharpe":        sharpe,
            "month_return":  month_ret,
            "recent_return": recent_ret,
            "start_nav":     navs[0],
            "current_nav":   navs[-1],
            "start_date":    dates[0],
        }

    # ── 리포트 텍스트 생성 ─────────────────────────────

    def monthly_report_text(self) -> str:
        m = self.compute_metrics()
        if not m:
            return "⚠️ 성과 데이터 부족 (최소 2거래일 이상 필요)"

        strat = f"\n전략:       {self.strategy_name}" if self.strategy_name else ""
        return (
            f"<b>📈 성과 리포트</b> ({date.today().strftime('%Y-%m-%d')}){strat}\n"
            f"<pre>"
            f"운용 기간:  {m['total_days']:>9}일  ({m['start_date']} ~)\n"
            f"{'─'*34}\n"
            f"누적 수익:  {m['total_return']*100:>+10.2f} %\n"
            f"CAGR:       {m['cagr']*100:>+10.2f} %\n"
            f"이번 달:    {m['month_return']*100:>+10.2f} %\n"
            f"최근 1개월: {m['recent_return']*100:>+10.2f} %\n"
            f"{'─'*34}\n"
            f"MDD:        {m['mdd']*100:>+10.2f} %\n"
            f"샤프지수:   {m['sharpe']:>+11.2f}\n"
            f"{'─'*34}\n"
            f"시작 자산:  {m['start_nav']:>12,.0f} 원\n"
            f"현재 자산:  {m['current_nav']:>12,.0f} 원"
            f"</pre>"
        )

    # ── 내부 ───────────────────────────────────────────

    def _load(self) -> list[dict]:
        try:
            if PERF_PATH.exists():
                return json.loads(PERF_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save(self, history: list[dict]) -> None:
        try:
            PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
            PERF_PATH.write_text(
                json.dumps(history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[Reporter] 성과 이력 저장 실패: {e}")
