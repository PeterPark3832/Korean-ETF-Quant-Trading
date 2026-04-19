"""
웹 대시보드 (FastAPI)
────────────────────────────────────────────────────────────────
포트폴리오 현황을 웹 브라우저에서 실시간 확인합니다.

접속: http://서버IP:8080
API:  http://서버IP:8080/api/status       (JSON 잔고)
      http://서버IP:8080/api/performance   (NAV 이력)
      http://서버IP:8080/api/target-weights (목표 vs 현재 비중)

보안: Vultr 방화벽에서 8080 포트를 본인 IP로만 제한 권장
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from scheduler import ETFQuantBot

# ── HTML 템플릿 (%%PLACEHOLDER%% 방식으로 동적 주입) ──────────
_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETF 퀀트봇 대시보드</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; font-size: 14px; }

.hdr { background: #1e293b; padding: 14px 20px; border-bottom: 1px solid #334155; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.hdr h1 { font-size: 16px; color: #f1f5f9; white-space: nowrap; }
.hdr .strat { font-size: 12px; color: #64748b; }
.hdr .cnt { margin-left: auto; font-size: 12px; color: #475569; white-space: nowrap; }
.hdr .cnt span { color: #3b82f6; font-weight: 700; }

.wrap { max-width: 1200px; margin: 0 auto; padding: 18px 16px; }
.updated { font-size: 11px; color: #475569; margin-bottom: 14px; }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 18px; }
.card { background: #1e293b; border-radius: 10px; padding: 16px; border: 1px solid #334155; }
.lbl { font-size: 10px; color: #64748b; margin-bottom: 5px; text-transform: uppercase; letter-spacing: .05em; }
.val { font-size: 20px; font-weight: 700; }
.sub2 { font-size: 12px; color: #94a3b8; margin-top: 3px; }

.pos { color: #34d399; } .neg { color: #f87171; } .neu { color: #94a3b8; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 9999px; font-size: 11px; font-weight: 600; }
.b-green { background: #064e3b; color: #34d399; }
.b-red   { background: #450a0a; color: #f87171; }
.b-yellow{ background: #451a03; color: #fb923c; }

.box { background: #1e293b; border-radius: 10px; border: 1px solid #334155; overflow: hidden; margin-bottom: 18px; }
.box-hdr { padding: 13px 16px; font-size: 12px; color: #94a3b8; font-weight: 600; border-bottom: 1px solid #334155; }
.box-body { padding: 16px; }
.empty-msg { font-size: 12px; color: #475569; text-align: center; padding: 24px 0; }

table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 9px 14px; font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: .04em; }
td { padding: 11px 14px; font-size: 13px; border-top: 1px solid #0f172a; }
.ticker { font-size: 10px; color: #475569; display: block; margin-top: 2px; }

.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
@media (max-width: 760px) {
  .two-col { grid-template-columns: 1fr; }
  .hide-sm { display: none; }
  .val { font-size: 17px; }
  td, th { padding: 9px 10px; }
}
</style>
</head>
<body>

<div class="hdr">
  <h1>📈 ETF 퀀트봇</h1>
  <span class="strat">%%STRATEGY%%</span>
  <button onclick="location.reload()" style="margin-left:auto;background:#1e40af;color:#bfdbfe;border:none;border-radius:7px;padding:6px 14px;font-size:12px;cursor:pointer">🔄 새로고침</button>
</div>

<div class="wrap">
  <p class="updated">%%UPDATED%%</p>

  <div class="cards">%%CARDS%%</div>

  <div class="box">
    <div class="box-hdr">NAV 추이</div>
    <div class="box-body">
      <canvas id="navChart" height="90"></canvas>
      <p id="navEmpty" class="empty-msg" style="display:none">데이터 없음 — 장 마감(15:35) 후 기록됩니다</p>
    </div>
  </div>

  <div class="two-col">
    <div class="box" style="margin-bottom:0">
      <div class="box-hdr">보유 종목</div>
      <table>
        <thead><tr>
          <th>종목명</th>
          <th class="hide-sm">수량</th>
          <th class="hide-sm">평균단가</th>
          <th>평가금액</th>
          <th>비중</th>
          <th>수익률</th>
        </tr></thead>
        <tbody>%%ROWS%%</tbody>
      </table>
    </div>

    <div class="box" style="margin-bottom:0">
      <div class="box-hdr">목표 vs 현재 비중</div>
      <div class="box-body">
        <canvas id="weightChart"></canvas>
        <p id="weightEmpty" class="empty-msg" style="display:none">리밸런싱 실행 후 표시됩니다</p>
      </div>
    </div>
  </div>
</div>

<script>
// ── Chart.js 전역 기본값 ─────────────────────────────
Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = 'rgba(51,65,85,0.6)';

// ── NAV 추이 차트 ────────────────────────────────────
(async function() {
  try {
    var r = await fetch('/api/performance');
    var d = await r.json();
    if (!d.dates || d.dates.length < 2) {
      document.getElementById('navEmpty').style.display = 'block';
      return;
    }
    new Chart(document.getElementById('navChart'), {
      type: 'line',
      data: {
        labels: d.dates,
        datasets: [{
          label: 'NAV',
          data: d.values,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.07)',
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          borderWidth: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxTicksLimit: 7, maxRotation: 0 } },
          y: { ticks: { callback: function(v) { return (v / 10000).toFixed(0) + '만'; } } }
        }
      }
    });
  } catch(e) {
    document.getElementById('navEmpty').style.display = 'block';
  }
})();

// ── 목표 vs 현재 비중 차트 ───────────────────────────
(async function() {
  try {
    var r = await fetch('/api/target-weights');
    var d = await r.json();
    if (!d.labels || d.labels.length === 0) {
      document.getElementById('weightEmpty').style.display = 'block';
      return;
    }
    new Chart(document.getElementById('weightChart'), {
      type: 'bar',
      data: {
        labels: d.labels,
        datasets: [
          { label: '목표', data: d.target,  backgroundColor: 'rgba(59,130,246,0.75)', borderRadius: 3 },
          { label: '현재', data: d.current, backgroundColor: 'rgba(52,211,153,0.75)', borderRadius: 3 },
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { labels: { color: '#94a3b8', boxWidth: 11, font: { size: 11 } } } },
        scales: {
          x: { ticks: { callback: function(v) { return v + '%'; } } },
          y: { ticks: { font: { size: 11 } } }
        }
      }
    });
  } catch(e) {
    document.getElementById('weightEmpty').style.display = 'block';
  }
})();
</script>
</body>
</html>"""


def _cls(v: float) -> str:
    return "pos" if v > 0 else ("neg" if v < 0 else "neu")


def _build_html(bot: "ETFQuantBot") -> str:
    try:
        balance = bot.broker.get_balance()
        risk_st = bot.guard.get_status()
    except Exception as e:
        return f"<pre style='color:#f87171;padding:32px'>잔고 조회 실패: {e}</pre>"

    total     = balance.total_assets
    mdd       = risk_st["current_mdd"]
    is_halted = risk_st["is_halted"]
    pnl_cls   = _cls(balance.total_pnl)

    if is_halted:
        badge = "<span class='badge b-red'>🔴 거래 중단</span>"
    elif mdd <= -0.08:
        badge = "<span class='badge b-yellow'>🟠 경고</span>"
    else:
        badge = "<span class='badge b-green'>🟢 정상</span>"

    cards_html = (
        f"<div class='card'>"
        f"<div class='lbl'>총 자산</div>"
        f"<div class='val neu'>{total:,.0f}원</div>"
        f"<div class='sub2'>예수금 {balance.cash:,.0f}원</div>"
        f"</div>"

        f"<div class='card'>"
        f"<div class='lbl'>평가 손익</div>"
        f"<div class='val {pnl_cls}'>{balance.total_pnl:+,.0f}원</div>"
        f"<div class='sub2 {pnl_cls}'>{balance.total_pnl_rate:+.2f}%</div>"
        f"</div>"

        f"<div class='card'>"
        f"<div class='lbl'>현재 MDD</div>"
        f"<div class='val {'neg' if mdd <= -0.08 else 'neu'}'>{mdd*100:+.2f}%</div>"
        f"<div class='sub2'>하드스탑 -18%</div>"
        f"</div>"

        f"<div class='card'>"
        f"<div class='lbl'>봇 상태</div>"
        f"<div class='val' style='font-size:15px;margin-top:4px'>{badge}</div>"
        f"<div class='sub2'>{risk_st.get('halt_reason') or ''}</div>"
        f"</div>"
    )

    rows = []
    for h in sorted(balance.holdings, key=lambda x: x.eval_amount, reverse=True):
        w   = h.eval_amount / total * 100 if total > 0 else 0
        cls = _cls(h.profit_rate)
        rows.append(
            f"<tr>"
            f"<td>{h.name}<span class='ticker'>{h.ticker}</span></td>"
            f"<td class='hide-sm'>{h.qty:,}</td>"
            f"<td class='hide-sm'>{h.avg_price:,.0f}</td>"
            f"<td>{h.eval_amount:,.0f}원</td>"
            f"<td>{w:.1f}%</td>"
            f"<td class='{cls}'>{h.profit_rate:+.1f}%</td>"
            f"</tr>"
        )
    if not rows:
        rows = ["<tr><td colspan='6' style='color:#475569;text-align:center;padding:24px'>보유 종목 없음</td></tr>"]

    html = _TEMPLATE
    html = html.replace("%%STRATEGY%%", f"전략: {bot.strategy_name}")
    html = html.replace("%%UPDATED%%",  f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    html = html.replace("%%CARDS%%",    cards_html)
    html = html.replace("%%ROWS%%",     "".join(rows))
    return html


def start_dashboard(bot: "ETFQuantBot", port: int = 8080) -> None:
    """대시보드 웹서버를 데몬 스레드로 시작"""
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, JSONResponse
        import uvicorn
    except ImportError:
        logger.warning("[Dashboard] fastapi/uvicorn 미설치 → 대시보드 비활성 (pip install fastapi uvicorn)")
        return

    app = FastAPI(title="ETF 퀀트봇", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _build_html(bot)

    @app.get("/api/status")
    async def api_status():
        try:
            balance = bot.broker.get_balance()
            risk_st = bot.guard.get_status()
            return {
                "total_assets":   balance.total_assets,
                "cash":           balance.cash,
                "total_pnl":      balance.total_pnl,
                "total_pnl_rate": balance.total_pnl_rate,
                "risk":           risk_st,
                "strategy":       bot.strategy_name,
                "holdings": [
                    {
                        "ticker":      h.ticker,
                        "name":        h.name,
                        "qty":         h.qty,
                        "eval_amount": h.eval_amount,
                        "profit_rate": h.profit_rate,
                    }
                    for h in balance.holdings
                ],
            }
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/performance")
    async def api_performance():
        try:
            path = Path("data/cache/performance.json")
            if not path.exists():
                return {"dates": [], "values": []}
            history = json.loads(path.read_text(encoding="utf-8"))
            return {
                "dates":  [h["date"][5:] for h in history],   # MM-DD
                "values": [h["nav"] for h in history],
            }
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/target-weights")
    async def api_target_weights():
        try:
            tw_path = Path("data/cache/last_target_weights.json")
            if not tw_path.exists():
                return {"labels": [], "target": [], "current": []}

            data           = json.loads(tw_path.read_text(encoding="utf-8"))
            target_weights = data.get("weights", {})

            try:
                balance = bot.broker.get_balance()
                total   = balance.total_assets
                current_weights = {
                    h.ticker: h.eval_amount / total * 100
                    for h in balance.holdings if total > 0
                }
            except Exception:
                current_weights = {}

            all_tickers = sorted(
                set(target_weights) | set(current_weights),
                key=lambda t: target_weights.get(t, 0),
                reverse=True,
            )

            try:
                from config import ALL_ETFS
            except ImportError:
                ALL_ETFS = {}

            labels  = [ALL_ETFS.get(t, t)[:10] for t in all_tickers]
            target  = [round(target_weights.get(t, 0.0) * 100, 1) for t in all_tickers]
            current = [round(current_weights.get(t, 0.0), 1)       for t in all_tickers]

            return {"labels": labels, "target": target, "current": current}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    def _run():
        config = uvicorn.Config(
            app, host="0.0.0.0", port=port,
            log_level="warning", access_log=False,
        )
        uvicorn.Server(config).run()

    t = threading.Thread(target=_run, daemon=True, name="dashboard")
    t.start()
    logger.info(f"[Dashboard] 웹 대시보드 시작 → http://0.0.0.0:{port}")
