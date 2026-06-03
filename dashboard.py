"""
웹 대시보드 (FastAPI)
────────────────────────────────────────────────────────────────
포트폴리오 현황을 웹 브라우저에서 실시간 확인합니다.

접속: http://서버IP:8080
API:  http://서버IP:8080/api/status       (JSON 잔고)
      http://서버IP:8080/api/performance   (NAV 이력)
      http://서버IP:8080/api/target-weights (목표 vs 현재 비중)
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


# ── HTML 대시보드 템플릿 ────────────────────────────────────────
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETF 퀀트봇 대시보드</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ── 리셋 & 기반 ─────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --indigo:   #4338CA;
  --indigo-d: #312E81;
  --indigo-l: #6366F1;
  --bg:       #EEF2F7;
  --card:     #FFFFFF;
  --card-alt: #F8FAFC;
  --text-1:   #1E293B;
  --text-2:   #64748B;
  --text-3:   #94A3B8;
  --border:   #E2E8F0;
  --green:    #10B981;
  --red:      #EF4444;
  --amber:    #F59E0B;
  --shadow:   0 2px 12px rgba(0,0,0,.07);
  --shadow-lg:0 8px 32px rgba(67,56,202,.13);
}
body {
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text-1);
  min-height: 100vh;
  font-size: 14px;
}

/* ── 레이아웃 ────────────────────────────────── */
.layout { display: flex; min-height: 100vh; }

/* ── 사이드바 ────────────────────────────────── */
.sidebar {
  width: 240px; flex-shrink: 0;
  background: var(--indigo-d);
  color: #C7D2FE;
  display: flex; flex-direction: column;
  padding: 28px 0;
}
.sidebar-logo {
  padding: 0 24px 28px;
  border-bottom: 1px solid rgba(255,255,255,.08);
}
.sidebar-logo .brand {
  font-size: 18px; font-weight: 800; color: #fff;
  letter-spacing: -.3px; display: flex; align-items: center; gap: 8px;
}
.sidebar-logo .brand .dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--green); box-shadow: 0 0 6px var(--green);
  flex-shrink: 0;
}
.sidebar-logo .sub { font-size: 11px; color: #818CF8; margin-top: 4px; }

.nav { padding: 20px 12px; flex: 1; }
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; border-radius: 10px; cursor: pointer;
  font-size: 13px; font-weight: 500; color: #A5B4FC;
  transition: all .15s;
}
.nav-item.active,
.nav-item:hover { background: rgba(255,255,255,.1); color: #fff; }
.nav-item svg { width: 16px; height: 16px; }

.sidebar-bot {
  margin: 0 12px 0;
  padding: 16px;
  background: rgba(255,255,255,.06);
  border-radius: 12px;
}
.sidebar-bot .label { font-size: 10px; color: #818CF8; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 8px; }
.strategy-name { font-size: 13px; font-weight: 600; color: #fff; }
.mode-badge {
  display: inline-block; margin-top: 6px;
  padding: 3px 10px; border-radius: 99px;
  font-size: 10px; font-weight: 600;
}
.mode-live   { background: rgba(16,185,129,.2); color: #34D399; }
.mode-paper  { background: rgba(249,115,22,.2);  color: #FB923C; }

/* ── 메인 영역 ───────────────────────────────── */
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* 상단 헤더 */
.topbar {
  background: var(--card);
  border-bottom: 1px solid var(--border);
  padding: 16px 28px;
  display: flex; align-items: center; gap: 14px;
}
.topbar-greeting { flex: 1; }
.topbar-greeting h2 { font-size: 20px; font-weight: 800; color: var(--text-1); }
.topbar-greeting p  { font-size: 12px; color: var(--text-2); margin-top: 2px; }
.topbar-right { display: flex; align-items: center; gap: 12px; }
.refresh-btn {
  background: var(--indigo); color: #fff;
  border: none; border-radius: 10px;
  padding: 8px 18px; font-size: 12px; font-weight: 600;
  cursor: pointer; transition: opacity .15s;
}
.refresh-btn:hover { opacity: .85; }
.time-chip {
  background: var(--card-alt); border: 1px solid var(--border);
  border-radius: 8px; padding: 7px 14px;
  font-size: 11px; color: var(--text-2);
}

/* 스크롤 영역 */
.content { flex: 1; overflow-y: auto; padding: 24px 28px; }

/* ── KPI 카드 ────────────────────────────────── */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px; margin-bottom: 24px;
}
.kpi-card {
  background: var(--card);
  border-radius: 16px; padding: 20px;
  box-shadow: var(--shadow);
  position: relative; overflow: hidden;
}
.kpi-card.accent {
  background: linear-gradient(135deg, var(--indigo-d), var(--indigo));
  color: #fff;
}
.kpi-card.accent .kpi-label { color: #A5B4FC; }
.kpi-label { font-size: 11px; font-weight: 600; color: var(--text-2); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 8px; }
.kpi-value { font-size: 24px; font-weight: 800; letter-spacing: -.5px; }
.kpi-sub   { font-size: 12px; color: var(--text-2); margin-top: 4px; }
.kpi-card.accent .kpi-sub { color: #C7D2FE; }
.kpi-icon {
  position: absolute; right: 16px; top: 16px;
  width: 36px; height: 36px; border-radius: 10px;
  background: rgba(0,0,0,.06);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
}
.kpi-card.accent .kpi-icon { background: rgba(255,255,255,.15); }
.pos { color: var(--green); }
.neg { color: var(--red);   }
.neu { color: var(--text-1);}

/* 상태 뱃지 */
.status-badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 12px; border-radius: 99px;
  font-size: 12px; font-weight: 600;
}
.s-ok   { background: rgba(16,185,129,.12); color: #059669; }
.s-warn { background: rgba(245,158,11,.12);  color: #D97706; }
.s-halt { background: rgba(239,68,68,.12);   color: #DC2626; }
.s-dot  { width: 6px; height: 6px; border-radius: 50%; }
.s-ok   .s-dot { background: #10B981; }
.s-warn .s-dot { background: #F59E0B; }
.s-halt .s-dot { background: #EF4444; }

/* ── 2열 그리드 ──────────────────────────────── */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.grid-3 { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 20px; }

/* ── 공통 패널 ───────────────────────────────── */
.panel {
  background: var(--card);
  border-radius: 16px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.panel-hdr {
  padding: 18px 20px 14px;
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border);
}
.panel-title { font-size: 14px; font-weight: 700; color: var(--text-1); }
.panel-sub   { font-size: 11px; color: var(--text-2); }
.panel-body  { padding: 20px; }

/* ── 테이블 ──────────────────────────────────── */
.tbl { width: 100%; border-collapse: collapse; }
.tbl th {
  text-align: left; padding: 10px 16px;
  font-size: 10px; font-weight: 600; color: var(--text-3);
  text-transform: uppercase; letter-spacing: .06em;
  background: var(--card-alt);
}
.tbl td { padding: 13px 16px; border-top: 1px solid var(--border); font-size: 13px; }
.tbl tr:hover td { background: var(--card-alt); }
.ticker-name   { font-weight: 600; color: var(--text-1); }
.ticker-code   { font-size: 10px; color: var(--text-3); margin-top: 2px; }
.prog-bar-wrap { background: #E2E8F0; border-radius: 99px; height: 5px; margin-top: 4px; }
.prog-bar      { background: var(--indigo-l); border-radius: 99px; height: 5px; }

/* ── 차트 컨테이너 ───────────────────────────── */
.chart-wrap { position: relative; }

/* ── 리밸런싱 로그 ───────────────────────────── */
.log-item {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 12px 0; border-bottom: 1px solid var(--border);
}
.log-item:last-child { border-bottom: none; }
.log-dot {
  width: 8px; height: 8px; border-radius: 50%;
  margin-top: 5px; flex-shrink: 0;
}
.log-dot.buy  { background: var(--green); }
.log-dot.sell { background: var(--red); }
.log-dot.info { background: var(--indigo-l); }
.log-text  { font-size: 13px; font-weight: 500; color: var(--text-1); }
.log-meta  { font-size: 11px; color: var(--text-2); margin-top: 2px; }

/* ── 반응형 ──────────────────────────────────── */
@media (max-width: 1100px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .grid-3   { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .sidebar  { display: none; }
  .grid-2   { grid-template-columns: 1fr; }
  .content  { padding: 16px; }
  .topbar   { padding: 14px 16px; }
}
@media (max-width: 600px) {
  .kpi-grid { grid-template-columns: 1fr 1fr; }
  .hide-sm  { display: none; }
}
</style>
</head>
<body>
<div class="layout">

  <!-- ── 사이드바 ── -->
  <aside class="sidebar">
    <div class="sidebar-logo">
      <div class="brand">
        <span class="dot"></span>
        ETF 퀀트봇
      </div>
      <div class="sub">Automated Portfolio System</div>
    </div>

    <nav class="nav">
      <div class="nav-item active">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
          <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
        </svg>
        대시보드
      </div>
      <div class="nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
        </svg>
        NAV 추이
      </div>
      <div class="nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
        </svg>
        전략 관리
      </div>
      <div class="nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 20V10M12 20V4M6 20v-6"/>
        </svg>
        백테스트
      </div>
      <div class="nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
        </svg>
        리스크 설정
      </div>
    </nav>

    <div class="sidebar-bot">
      <div class="label">현재 전략</div>
      <div class="strategy-name">%%STRATEGY%%</div>
      <span class="mode-badge %%MODE_CLASS%%">%%MODE_LABEL%%</span>
    </div>
  </aside>

  <!-- ── 메인 ── -->
  <div class="main">
    <!-- 상단 바 -->
    <div class="topbar">
      <div class="topbar-greeting">
        <h2>%%GREETING%%</h2>
        <p>%%UPDATED%%</p>
      </div>
      <div class="topbar-right">
        <div class="time-chip" id="live-time">--:--:--</div>
        <button class="refresh-btn" onclick="location.reload()">↻ 새로고침</button>
      </div>
    </div>

    <!-- 콘텐츠 -->
    <div class="content">

      <!-- KPI 카드 4개 -->
      <div class="kpi-grid">%%KPIS%%</div>

      <!-- NAV 차트 + 리밸런싱 로그 -->
      <div class="grid-3">
        <div class="panel">
          <div class="panel-hdr">
            <div>
              <div class="panel-title">NAV 추이</div>
              <div class="panel-sub">일별 포트폴리오 순자산가치</div>
            </div>
            <span id="nav-cagr" style="font-size:12px;font-weight:700;color:var(--indigo)"></span>
          </div>
          <div class="panel-body">
            <div class="chart-wrap"><canvas id="navChart" height="100"></canvas></div>
            <p id="navEmpty" style="display:none;color:var(--text-3);text-align:center;padding:40px 0;font-size:13px">
              장 마감(15:35) 후 기록됩니다
            </p>
          </div>
        </div>

        <div class="panel">
          <div class="panel-hdr">
            <div>
              <div class="panel-title">리밸런싱 기록</div>
              <div class="panel-sub">최근 활동</div>
            </div>
          </div>
          <div class="panel-body" id="rebal-log">
            <div class="log-item">
              <div class="log-dot info"></div>
              <div>
                <div class="log-text">대기 중</div>
                <div class="log-meta">다음 리밸런싱: 매월 첫 영업일 15:15</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 보유종목 + 비중 차트 -->
      <div class="grid-2">
        <div class="panel">
          <div class="panel-hdr">
            <div>
              <div class="panel-title">보유 종목</div>
              <div class="panel-sub">%%HOLDING_COUNT%%</div>
            </div>
          </div>
          <table class="tbl">
            <thead>
              <tr>
                <th>종목</th>
                <th class="hide-sm">수량</th>
                <th>평가금액</th>
                <th>비중</th>
                <th>수익률</th>
              </tr>
            </thead>
            <tbody>%%ROWS%%</tbody>
          </table>
        </div>

        <div class="panel">
          <div class="panel-hdr">
            <div>
              <div class="panel-title">목표 vs 현재 비중</div>
              <div class="panel-sub">전략 목표 대비 실제 배분</div>
            </div>
          </div>
          <div class="panel-body">
            <div class="chart-wrap"><canvas id="weightChart" height="200"></canvas></div>
            <p id="weightEmpty" style="display:none;color:var(--text-3);text-align:center;padding:40px 0;font-size:13px">
              리밸런싱 실행 후 표시됩니다
            </p>
          </div>
        </div>
      </div>

    </div><!-- /content -->
  </div><!-- /main -->
</div><!-- /layout -->

<script>
// ── 실시간 시계 ───────────────────────────────────────────
(function tick() {
  var d = new Date();
  document.getElementById('live-time').textContent =
    d.toLocaleTimeString('ko-KR', {hour12: false});
  setTimeout(tick, 1000);
})();

// ── 공통 Chart.js 기본값 ──────────────────────────────────
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.color = '#94A3B8';
Chart.defaults.borderColor = 'rgba(226,232,240,.6)';

// ── NAV 추이 ─────────────────────────────────────────────
(async function() {
  try {
    var r = await fetch('/api/performance');
    var d = await r.json();
    if (!d.dates || d.dates.length < 2) {
      document.getElementById('navEmpty').style.display = 'block';
      return;
    }
    // CAGR 표시
    var first = d.values[0], last = d.values[d.values.length-1];
    if (first > 0) {
      var ret = (last / first - 1) * 100;
      var el = document.getElementById('nav-cagr');
      el.textContent = (ret >= 0 ? '+' : '') + ret.toFixed(2) + '%';
      el.style.color = ret >= 0 ? 'var(--green)' : 'var(--red)';
    }
    new Chart(document.getElementById('navChart'), {
      type: 'line',
      data: {
        labels: d.dates,
        datasets: [{
          label: 'NAV',
          data: d.values,
          borderColor: '#4338CA',
          backgroundColor: 'rgba(99,102,241,.08)',
          fill: true,
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 4,
          borderWidth: 2.5,
        }]
      },
      options: {
        responsive: true,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1E293B',
            titleColor: '#94A3B8',
            bodyColor: '#F1F5F9',
            padding: 10,
            callbacks: {
              label: function(ctx) {
                return ' ' + ctx.parsed.y.toLocaleString('ko-KR') + '원';
              }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } },
          y: {
            grid: { color: 'rgba(226,232,240,.5)' },
            ticks: {
              callback: function(v) {
                return (v >= 10000000 ? (v/10000000).toFixed(1)+'천만' : (v/10000).toFixed(0)+'만') + '원';
              }
            }
          }
        }
      }
    });
  } catch(e) {
    document.getElementById('navEmpty').style.display = 'block';
  }
})();

// ── 목표 vs 현재 비중 ─────────────────────────────────────
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
          {
            label: '목표',
            data: d.target,
            backgroundColor: 'rgba(67,56,202,.8)',
            borderRadius: 4, borderSkipped: false,
          },
          {
            label: '현재',
            data: d.current,
            backgroundColor: 'rgba(16,185,129,.7)',
            borderRadius: 4, borderSkipped: false,
          }
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: {
          legend: {
            position: 'top',
            labels: { color: '#64748B', boxWidth: 10, font: { size: 11 } }
          },
          tooltip: {
            backgroundColor: '#1E293B',
            callbacks: { label: function(ctx) { return ' ' + ctx.parsed.x + '%'; } }
          }
        },
        scales: {
          x: {
            grid: { color: 'rgba(226,232,240,.5)' },
            ticks: { callback: function(v) { return v + '%'; } }
          },
          y: { grid: { display: false }, ticks: { font: { size: 11 } } }
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


# ── 헬퍼 ──────────────────────────────────────────────────

def _pct_color(v: float) -> str:
    return "pos" if v > 0 else ("neg" if v < 0 else "neu")


def _fmt_won(v: float) -> str:
    return f"{v:+,.0f}원" if v != 0 else "0원"


def _greeting() -> str:
    h = datetime.now().hour
    if h < 6:   return "안녕하세요 👋"
    if h < 12:  return "좋은 아침입니다 ☀️"
    if h < 18:  return "좋은 오후입니다 📈"
    return "좋은 저녁입니다 🌙"


def _build_html(bot: "ETFQuantBot") -> str:
    try:
        balance = bot.broker.get_balance()
        risk_st = bot.guard.get_status()
    except Exception as e:
        return (
            f"<div style='font-family:Inter,sans-serif;padding:48px;background:#EEF2F7;min-height:100vh'>"
            f"<div style='background:#fff;border-radius:16px;padding:32px;max-width:400px;margin:0 auto;"
            f"box-shadow:0 2px 12px rgba(0,0,0,.07)'>"
            f"<h2 style='color:#EF4444;margin-bottom:12px'>연결 오류</h2>"
            f"<p style='color:#64748B;font-size:13px'>{e}</p>"
            f"</div></div>"
        )

    total     = balance.total_assets
    mdd       = risk_st["current_mdd"]
    is_halted = risk_st["is_halted"]
    pnl       = balance.total_pnl
    pnl_rate  = balance.total_pnl_rate

    # ── 상태 뱃지 ──────────────────────────────────────────
    if is_halted:
        badge = "<span class='status-badge s-halt'><span class='s-dot'></span> 거래 중단</span>"
    elif mdd <= -0.08:
        badge = "<span class='status-badge s-warn'><span class='s-dot'></span> 경고</span>"
    else:
        badge = "<span class='status-badge s-ok'><span class='s-dot'></span> 정상 운용 중</span>"

    # ── KPI 카드 ───────────────────────────────────────────
    kpi = (
        # 총 자산 (인디고 강조)
        f"<div class='kpi-card accent'>"
        f"  <div class='kpi-icon'>💰</div>"
        f"  <div class='kpi-label'>총 자산</div>"
        f"  <div class='kpi-value'>{total/10000:.0f}만원</div>"
        f"  <div class='kpi-sub'>예수금 {balance.cash/10000:.0f}만원</div>"
        f"</div>"

        # 평가 손익
        f"<div class='kpi-card'>"
        f"  <div class='kpi-icon'>📊</div>"
        f"  <div class='kpi-label'>평가 손익</div>"
        f"  <div class='kpi-value {_pct_color(pnl)}'>{pnl:+,.0f}원</div>"
        f"  <div class='kpi-sub {_pct_color(pnl_rate)}'>{pnl_rate:+.2f}%</div>"
        f"</div>"

        # MDD
        f"<div class='kpi-card'>"
        f"  <div class='kpi-icon'>🛡️</div>"
        f"  <div class='kpi-label'>현재 MDD</div>"
        f"  <div class='kpi-value {'neg' if mdd <= -0.08 else 'neu'}'>{mdd*100:+.2f}%</div>"
        f"  <div class='kpi-sub' style='color:var(--text-3)'>한도 -18% (하드스탑)</div>"
        f"</div>"

        # 봇 상태
        f"<div class='kpi-card'>"
        f"  <div class='kpi-icon'>🤖</div>"
        f"  <div class='kpi-label'>봇 상태</div>"
        f"  <div class='kpi-value' style='font-size:16px;margin-top:6px'>{badge}</div>"
        f"  <div class='kpi-sub'>{risk_st.get('halt_reason') or '자동 매매 활성'}</div>"
        f"</div>"
    )

    # ── 보유종목 행 ────────────────────────────────────────
    rows = []
    sorted_holdings = sorted(balance.holdings, key=lambda x: x.eval_amount, reverse=True)
    for h in sorted_holdings:
        w   = h.eval_amount / total * 100 if total > 0 else 0
        cls = _pct_color(h.profit_rate)
        rows.append(
            f"<tr>"
            f"<td>"
            f"  <div class='ticker-name'>{h.name}</div>"
            f"  <div class='ticker-code'>{h.ticker}</div>"
            f"</td>"
            f"<td class='hide-sm'>{h.qty:,}주</td>"
            f"<td>{h.eval_amount/10000:.0f}만원</td>"
            f"<td>"
            f"  <div style='font-size:12px;font-weight:600'>{w:.1f}%</div>"
            f"  <div class='prog-bar-wrap'><div class='prog-bar' style='width:{min(w,100):.1f}%'></div></div>"
            f"</td>"
            f"<td class='{cls}' style='font-weight:600'>{h.profit_rate:+.1f}%</td>"
            f"</tr>"
        )
    if not rows:
        rows = [
            "<tr><td colspan='5' style='text-align:center;padding:40px 16px;"
            "color:var(--text-3);font-size:13px'>보유 종목 없음</td></tr>"
        ]

    holding_count = f"{len(sorted_holdings)}개 종목 보유 중"

    # ── 전략·모드 설정 ────────────────────────────────────
    strategy_name = getattr(bot, "strategy_name", "MultiStrategy")
    mode          = getattr(bot, "mode", "paper")
    mode_cls   = "mode-live"  if mode == "kis_real"  else "mode-paper"
    mode_label = "LIVE"       if mode == "kis_real"  else "PAPER"

    # ── 템플릿 치환 ───────────────────────────────────────
    html = _TEMPLATE
    html = html.replace("%%GREETING%%",      _greeting())
    html = html.replace("%%STRATEGY%%",      strategy_name)
    html = html.replace("%%MODE_CLASS%%",    mode_cls)
    html = html.replace("%%MODE_LABEL%%",    mode_label)
    html = html.replace("%%UPDATED%%",       f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    html = html.replace("%%KPIS%%",          kpi)
    html = html.replace("%%ROWS%%",          "".join(rows))
    html = html.replace("%%HOLDING_COUNT%%", holding_count)
    return html


def start_dashboard(bot: "ETFQuantBot", port: int = 8080) -> None:
    """대시보드 웹서버를 데몬 스레드로 시작"""
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, JSONResponse
        import uvicorn
    except ImportError:
        logger.warning("[Dashboard] fastapi/uvicorn 미설치 → pip install fastapi uvicorn")
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
                "strategy":       getattr(bot, "strategy_name", ""),
                "mode":           getattr(bot, "mode", "paper"),
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
                "dates":  [h["date"][5:] for h in history],
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

            labels  = [ALL_ETFS.get(t, t)[:12] for t in all_tickers]
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
    logger.info(f"[Dashboard] 대시보드 시작 → http://0.0.0.0:{port}")
