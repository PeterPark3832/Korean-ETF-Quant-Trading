"""
웹 대시보드 (FastAPI)
────────────────────────────────────────────────────────────────
포트폴리오 현황을 웹 브라우저에서 실시간 확인합니다.

접속: http://서버IP:8080
API:  http://서버IP:8080/api/status  (JSON)

보안: Vultr 방화벽에서 8080 포트를 본인 IP로만 제한 권장
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from scheduler import ETFQuantBot

# ── HTML 템플릿 ────────────────────────────────────────
_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETF 퀀트봇</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}}
.hdr{{background:#1e293b;padding:18px 32px;border-bottom:1px solid #334155;display:flex;align-items:center;gap:16px}}
.hdr h1{{font-size:18px;color:#f1f5f9}}
.hdr .sub{{font-size:12px;color:#64748b}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 32px}}
.refresh{{text-align:right;font-size:12px;color:#475569;margin-bottom:16px}}
.refresh a{{color:#3b82f6;text-decoration:none}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin-bottom:24px}}
.card{{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}}
.lbl{{font-size:11px;color:#64748b;margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em}}
.val{{font-size:22px;font-weight:700}}
.sub2{{font-size:12px;margin-top:4px;color:#94a3b8}}
.pos{{color:#34d399}}.neg{{color:#f87171}}.neu{{color:#94a3b8}}
.tbl-wrap{{background:#1e293b;border-radius:12px;border:1px solid #334155;overflow:hidden;margin-bottom:24px}}
.tbl-hdr{{padding:16px 20px;font-size:13px;color:#94a3b8;font-weight:600;border-bottom:1px solid #334155}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;padding:10px 16px;font-size:11px;color:#64748b;background:#1e293b;border-bottom:1px solid #334155;text-transform:uppercase}}
td{{padding:12px 16px;font-size:13px;border-bottom:1px solid #0f172a}}
tr:last-child td{{border-bottom:none}}
.badge{{display:inline-block;padding:3px 10px;border-radius:9999px;font-size:11px;font-weight:600}}
.b-green{{background:#064e3b;color:#34d399}}
.b-red{{background:#450a0a;color:#f87171}}
.b-yellow{{background:#451a03;color:#fb923c}}
</style>
</head>
<body>
<div class="hdr">
  <h1>📈 ETF 퀀트봇 대시보드</h1>
  <span class="sub">전략: {strategy}</span>
</div>
<div class="wrap">
  <div class="refresh">
    {updated} &nbsp; <a href="/">새로고침</a>
  </div>
  <div class="grid">
    <div class="card">
      <div class="lbl">총 자산</div>
      <div class="val neu">{total_assets}</div>
      <div class="sub2">예수금 {cash}</div>
    </div>
    <div class="card">
      <div class="lbl">평가 손익</div>
      <div class="val {pnl_cls}">{total_pnl}</div>
      <div class="sub2 {pnl_cls}">{total_pnl_rate}</div>
    </div>
    <div class="card">
      <div class="lbl">현재 MDD</div>
      <div class="val {mdd_cls}">{mdd}</div>
      <div class="sub2">하드스탑: -18%</div>
    </div>
    <div class="card">
      <div class="lbl">봇 상태</div>
      <div class="val" style="font-size:16px;margin-top:4px">{status_badge}</div>
      <div class="sub2">{halt_reason}</div>
    </div>
  </div>

  <div class="tbl-wrap">
    <div class="tbl-hdr">보유 종목</div>
    <table>
      <thead>
        <tr>
          <th>종목명</th><th>수량</th><th>평균단가</th>
          <th>현재가</th><th>평가금액</th><th>비중</th><th>수익률</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
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

    total = balance.total_assets
    rows  = []
    for h in sorted(balance.holdings, key=lambda x: x.eval_amount, reverse=True):
        w   = h.eval_amount / total * 100 if total > 0 else 0
        cls = _cls(h.profit_rate)
        rows.append(
            f"<tr>"
            f"<td>{h.name}</td>"
            f"<td>{h.qty:,}</td>"
            f"<td>{h.avg_price:,.0f}</td>"
            f"<td>{h.current_price:,.0f}</td>"
            f"<td>{h.eval_amount:,.0f}원</td>"
            f"<td>{w:.1f}%</td>"
            f"<td class='{cls}'>{h.profit_rate:+.1f}%</td>"
            f"</tr>"
        )
    if not rows:
        rows = ["<tr><td colspan='7' style='color:#64748b;text-align:center;padding:24px'>보유 종목 없음</td></tr>"]

    mdd       = risk_st["current_mdd"]
    is_halted = risk_st["is_halted"]

    if is_halted:
        badge = "<span class='badge b-red'>🔴 거래 중단</span>"
    elif mdd <= -0.08:
        badge = "<span class='badge b-yellow'>🟠 경고</span>"
    else:
        badge = "<span class='badge b-green'>🟢 정상</span>"

    return _HTML.format(
        strategy       = bot.strategy_name,
        updated        = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_assets   = f"{total:,.0f}원",
        cash           = f"{balance.cash:,.0f}원",
        total_pnl      = f"{balance.total_pnl:+,.0f}원",
        total_pnl_rate = f"{balance.total_pnl_rate:+.2f}%",
        pnl_cls        = _cls(balance.total_pnl),
        mdd            = f"{mdd*100:+.2f}%",
        mdd_cls        = "neg" if mdd <= -0.08 else "neu",
        status_badge   = badge,
        halt_reason    = risk_st.get("halt_reason") or "",
        rows           = "".join(rows),
    )


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
                "total_assets":    balance.total_assets,
                "cash":            balance.cash,
                "total_pnl":       balance.total_pnl,
                "total_pnl_rate":  balance.total_pnl_rate,
                "risk":            risk_st,
                "strategy":        bot.strategy_name,
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

    def _run():
        config = uvicorn.Config(
            app, host="0.0.0.0", port=port,
            log_level="warning", access_log=False,
        )
        uvicorn.Server(config).run()

    t = threading.Thread(target=_run, daemon=True, name="dashboard")
    t.start()
    logger.info(f"[Dashboard] 웹 대시보드 시작 → http://0.0.0.0:{port}")
