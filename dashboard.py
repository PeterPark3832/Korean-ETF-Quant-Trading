"""
웹 대시보드 (FastAPI) — 반응형 3-tier 레이아웃
────────────────────────────────────────────────────────────────
breakpoints:
  mobile  : max-width  639px  → 하단 탭바 + 풀스크린 카드
  tablet  : 640-1023px        → 상단 탭 + 2열 그리드
  desktop : min-width 1024px  → 사이드바 + 다열 패널

접속: http://서버IP:8080
API:  /api/status  /api/performance  /api/target-weights
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from scheduler import ETFQuantBot


# ─────────────────────────────────────────────────────────────
# HTML 템플릿
# ─────────────────────────────────────────────────────────────
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>ETF 퀀트봇 | Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ════════════════════════════════════════════════════════════
   0. Reset + Variables
════════════════════════════════════════════════════════════ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --navy:    #0B1628;
  --navy-2:  #122038;
  --navy-3:  #1A2D4A;

  --bg:      #EEF2F9;
  --bg-2:    #E4EBF5;
  --card:    #FFFFFF;
  --card-2:  #F8FAFD;

  --border:   rgba(15,23,42,.08);
  --border-2: rgba(15,23,42,.15);

  --indigo:    #4F46E5;
  --indigo-d:  #3730A3;
  --indigo-l:  #818CF8;
  --indigo-bg: #EEF2FF;

  --green:    #059669;
  --green-l:  #34D399;
  --green-bg: #ECFDF5;
  --red:      #DC2626;
  --red-l:    #FCA5A5;
  --red-bg:   #FEF2F2;
  --amber:    #D97706;
  --amber-l:  #FCD34D;
  --amber-bg: #FFFBEB;
  --cyan:     #0891B2;
  --cyan-bg:  #ECFEFF;

  --text-1: #0F172A;
  --text-2: #475569;
  --text-3: #94A3B8;
  --text-4: #CBD5E1;

  --shadow-xs: 0 1px 2px rgba(0,0,0,.04);
  --shadow-sm: 0 1px 4px rgba(0,0,0,.05), 0 2px 12px rgba(0,0,0,.04);
  --shadow:    0 2px 8px rgba(0,0,0,.06), 0 8px 32px rgba(0,0,0,.05);

  --radius:    12px;
  --radius-sm: 8px;
  --radius-xs: 6px;
  --tab-h:     64px;
}
html { -webkit-tap-highlight-color: transparent; }
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text-1);
  font-size: 14px;
  line-height: 1.5;
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}
button { font-family: inherit; cursor: pointer; border: none; outline: none; }

/* ════════════════════════════════════════════════════════════
   1. Common Components
════════════════════════════════════════════════════════════ */
.pos { color: var(--green); }
.neg { color: var(--red);   }
.neu { color: var(--text-1);}

.panel-title { font-size: 13px; font-weight: 700; letter-spacing: -.02em; }
.panel-sub   { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: 99px;
  font-size: 11px; font-weight: 600; white-space: nowrap;
}
.badge-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.b-ok   { background: var(--green-bg); color: #065F46; }
.b-ok   .badge-dot { background: var(--green); box-shadow: 0 0 6px var(--green); }
.b-warn { background: var(--amber-bg); color: #92400E; }
.b-warn .badge-dot { background: var(--amber); }
.b-halt { background: var(--red-bg);   color: #991B1B; }
.b-halt .badge-dot { background: var(--red); }

.mode-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: 99px;
  font-size: 11px; font-weight: 600;
}
.mode-live  { background: rgba(5,150,105,.12);  color: #059669; }
.mode-paper { background: rgba(217,119,6,.12);  color: #D97706; }

.prog-wrap { background: var(--border); border-radius: 99px; height: 5px; overflow: hidden; }
.prog-bar  { background: linear-gradient(90deg, var(--indigo-l), var(--indigo));
             border-radius: 99px; height: 5px; transition: width .5s ease; }

.divider { border: none; border-top: 1px solid var(--border); }

.log-list { display: flex; flex-direction: column; }
.log-item { display: flex; align-items: flex-start; gap: 12px;
            padding: 12px 0; border-bottom: 1px solid var(--border); }
.log-item:last-child { border-bottom: none; }
.log-dot  { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
.ld-buy   { background: var(--green); }
.ld-sell  { background: var(--red); }
.ld-info  { background: var(--indigo-l); }
.log-text { font-size: 13px; font-weight: 500; }
.log-meta { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 48px 20px; color: var(--text-3); font-size: 12px; gap: 10px; text-align: center;
}
.empty-state svg { width: 36px; height: 36px; opacity: .3; }

/* ════════════════════════════════════════════════════════════
   2. ██ DESKTOP  (min-width: 1024px)
════════════════════════════════════════════════════════════ */
@media (min-width: 1024px) {

  .app-mobile, .app-tablet { display: none !important; }
  .app-desktop { display: flex; min-height: 100vh; }

  /* ── Sidebar ── */
  .sidebar {
    width: 256px; flex-shrink: 0;
    background: linear-gradient(180deg, var(--navy) 0%, var(--navy-2) 100%);
    display: flex; flex-direction: column;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
    border-right: 1px solid rgba(255,255,255,.04);
  }
  .sb-logo {
    padding: 26px 20px 20px;
    border-bottom: 1px solid rgba(255,255,255,.06);
  }
  .sb-brand { display: flex; align-items: center; gap: 10px; }
  .sb-brand-icon {
    width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
    background: linear-gradient(135deg, var(--indigo), var(--indigo-l));
    display: flex; align-items: center; justify-content: center; font-size: 17px;
    box-shadow: 0 4px 14px rgba(79,70,229,.4);
  }
  .sb-brand-text { flex: 1; min-width: 0; }
  .sb-brand-name { font-size: 15px; font-weight: 800; color: #fff; letter-spacing: -.03em; }
  .sb-brand-sub  { font-size: 10px; color: rgba(165,180,252,.6); margin-top: 1px; }
  .pulse-dot {
    width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
    background: var(--green-l);
    animation: pulse-anim 2.4s ease infinite;
  }
  @keyframes pulse-anim {
    0%,100% { box-shadow: 0 0 0 0 rgba(52,211,153,.5); }
    50%      { box-shadow: 0 0 0 6px rgba(52,211,153,0); }
  }

  .sb-nav { padding: 12px 10px; flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .sb-sec-lbl {
    font-size: 9px; font-weight: 700; color: rgba(148,163,184,.45);
    text-transform: uppercase; letter-spacing: .1em;
    padding: 12px 12px 5px;
  }
  .sb-nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; border-radius: var(--radius-sm);
    font-size: 13px; font-weight: 500; color: rgba(165,180,252,.7);
    transition: all .15s; cursor: pointer; user-select: none;
    border-left: 2px solid transparent;
  }
  .sb-nav-item svg { width: 15px; height: 15px; flex-shrink: 0; }
  .sb-nav-item:hover { background: rgba(255,255,255,.07); color: rgba(255,255,255,.9); }
  .sb-nav-item.active {
    background: rgba(99,102,241,.18); color: #fff; font-weight: 600;
    border-left-color: var(--indigo-l);
  }
  .sb-nav-sep { height: 1px; background: rgba(255,255,255,.06); margin: 8px 2px; }

  .sb-footer {
    margin: 12px 10px 16px; padding: 14px 16px;
    background: rgba(255,255,255,.05);
    border: 1px solid rgba(255,255,255,.07);
    border-radius: var(--radius-sm);
  }
  .sf-label { font-size: 9px; color: rgba(165,180,252,.6); text-transform: uppercase;
    letter-spacing: .08em; margin-bottom: 6px; font-weight: 700; }
  .sf-strat { font-size: 12px; font-weight: 700; color: #fff; margin-bottom: 8px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* ── Main ── */
  .dt-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }

  .dt-topbar {
    background: var(--card);
    border-bottom: 1px solid var(--border);
    box-shadow: 0 1px 0 var(--border), 0 4px 16px rgba(0,0,0,.04);
    padding: 15px 28px;
    display: flex; align-items: center; gap: 10px;
    position: sticky; top: 0; z-index: 20;
  }
  .dt-topbar-left { flex: 1; min-width: 0; }
  .dt-topbar-left h2 {
    font-size: 19px; font-weight: 800; letter-spacing: -.04em; color: var(--text-1);
  }
  .dt-topbar-left p { font-size: 11px; color: var(--text-3); margin-top: 2px; }
  .dt-topbar-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

  .time-pill {
    background: var(--card-2); border: 1px solid var(--border);
    border-radius: var(--radius-xs); padding: 6px 12px;
    font-size: 12px; font-weight: 600; color: var(--text-2);
    font-variant-numeric: tabular-nums; letter-spacing: .02em;
  }
  .tb-btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 7px 14px; border-radius: var(--radius-xs);
    font-size: 12px; font-weight: 600; transition: all .15s; white-space: nowrap;
  }
  .btn-refresh   { background: var(--indigo); color: #fff; }
  .btn-refresh:hover { background: var(--indigo-d); }
  .btn-dryrun    { background: var(--card-2); border: 1px solid var(--border); color: var(--text-2); }
  .btn-dryrun:hover { background: var(--bg); border-color: var(--border-2); color: var(--text-1); }
  .btn-rebalance { background: var(--green); color: #fff; }
  .btn-rebalance:hover { background: #047857; }

  /* ── Rebalance panel ── */
  .rb-panel {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow-sm); border: 1px solid var(--border);
    margin-bottom: 20px; overflow: hidden;
    border-top: 3px solid var(--indigo);
    animation: slideDown .2s ease;
  }
  @keyframes slideDown {
    from { opacity: 0; transform: translateY(-6px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .rb-panel.rb-dry { border-top-color: var(--amber); }
  .rb-panel.rb-err { border-top-color: var(--red); }
  .rb-panel.rb-run { border-top-color: var(--text-4); }

  .rb-header {
    padding: 14px 20px;
    display: flex; align-items: center; justify-content: space-between;
    background: var(--card-2); border-bottom: 1px solid var(--border);
  }
  .rb-title { font-size: 13px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
  .rb-meta  { font-size: 11px; color: var(--text-3); margin-top: 3px; }

  .rb-stats {
    display: flex; padding: 16px 20px;
    border-bottom: 1px solid var(--border);
  }
  .rb-stat { flex: 1; display: flex; flex-direction: column; gap: 3px; padding-right: 16px; }
  .rb-stat + .rb-stat { padding-left: 16px; border-left: 1px solid var(--border); }
  .rb-stat-val { font-size: 20px; font-weight: 800; letter-spacing: -.03em; }
  .rb-stat-lbl { font-size: 10px; color: var(--text-3); text-transform: uppercase;
    letter-spacing: .06em; font-weight: 600; }

  .rb-tbl { width: 100%; border-collapse: collapse; }
  .rb-tbl th {
    text-align: left; padding: 8px 20px;
    font-size: 10px; font-weight: 700; color: var(--text-3);
    text-transform: uppercase; letter-spacing: .06em;
    background: var(--card-2); border-bottom: 1px solid var(--border);
  }
  .rb-tbl td { padding: 11px 20px; border-top: 1px solid var(--border); font-size: 13px; }
  .rb-tbl tr:hover td { background: var(--bg); }
  .side-buy  { color: var(--green); font-weight: 700; }
  .side-sell { color: var(--red);   font-weight: 700; }
  .spin { display: inline-block; animation: spin360 .8s linear infinite; }
  @keyframes spin360 { to { transform: rotate(360deg); } }

  /* ── Content ── */
  .dt-content { flex: 1; padding: 24px 28px; overflow-y: auto; }

  /* KPI grid */
  .dt-kpi-grid {
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 16px; margin-bottom: 20px;
  }
  .dt-kpi {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow-sm); border: 1px solid var(--border);
    padding: 20px; position: relative; overflow: hidden;
  }
  .dt-kpi::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
    background: var(--indigo-l);
  }
  .dt-kpi.kpi-green::before { background: linear-gradient(90deg, var(--green-l), var(--green)); }
  .dt-kpi.kpi-amber::before { background: linear-gradient(90deg, var(--amber-l), var(--amber)); }
  .dt-kpi.kpi-cyan::before  { background: linear-gradient(90deg, #22D3EE, var(--cyan)); }
  .dt-kpi.accent {
    background: linear-gradient(135deg, var(--navy) 0%, var(--navy-3) 100%);
    color: #fff; border-color: transparent;
  }
  .dt-kpi.accent::before { background: rgba(255,255,255,.2); }

  .kpi-ico {
    position: absolute; right: 16px; top: 18px;
    width: 36px; height: 36px; border-radius: 9px;
    background: var(--bg-2);
    display: flex; align-items: center; justify-content: center; font-size: 17px;
  }
  .dt-kpi.accent .kpi-ico { background: rgba(255,255,255,.12); }
  .kpi-lbl {
    font-size: 10px; font-weight: 700; color: var(--text-3);
    text-transform: uppercase; letter-spacing: .08em; margin-bottom: 10px;
  }
  .dt-kpi.accent .kpi-lbl { color: rgba(165,180,252,.8); }
  .kpi-val  { font-size: 22px; font-weight: 800; letter-spacing: -.04em; }
  .kpi-note { font-size: 11px; color: var(--text-3); margin-top: 5px; }
  .dt-kpi.accent .kpi-note { color: rgba(199,210,254,.8); }

  /* Panels */
  .dt-row { display: grid; gap: 16px; margin-bottom: 16px; }
  .dt-row.col-3-1 { grid-template-columns: 3fr 1.5fr; }
  .dt-row.col-2   { grid-template-columns: 1fr 1fr; }
  .dt-row.col-3   { grid-template-columns: 1fr 1fr 1fr; }

  .dt-panel {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow-sm); border: 1px solid var(--border);
    overflow: hidden; display: flex; flex-direction: column;
  }
  .dt-ph {
    padding: 15px 20px 13px;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid var(--border);
    background: var(--card-2);
  }
  .dt-pb { padding: 18px 20px; flex: 1; }

  /* Table */
  .dt-tbl { width: 100%; border-collapse: collapse; }
  .dt-tbl thead tr { background: var(--card-2); }
  .dt-tbl th {
    text-align: left; padding: 9px 16px;
    font-size: 10px; font-weight: 700; color: var(--text-3);
    text-transform: uppercase; letter-spacing: .06em;
    border-bottom: 1px solid var(--border);
  }
  .dt-tbl td { padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 13px; }
  .dt-tbl tbody tr:last-child td { border-bottom: none; }
  .dt-tbl tbody tr:hover td { background: var(--bg); }
  .t-name { font-weight: 600; }
  .t-code { font-size: 10px; color: var(--text-4); margin-top: 1px; }

  /* Risk meters */
  .risk-meter { display: flex; flex-direction: column; gap: 16px; }
  .rm-item    { display: flex; flex-direction: column; gap: 6px; }
  .rm-row     { display: flex; justify-content: space-between; align-items: baseline; }
  .rm-label   { font-size: 12px; color: var(--text-2); font-weight: 500; }
  .rm-value   { font-size: 12px; font-weight: 700; }
  .rm-track   { height: 6px; background: var(--border); border-radius: 99px; overflow: hidden; }
  .rm-fill    { height: 6px; border-radius: 99px; transition: width .6s cubic-bezier(.4,0,.2,1); }
  .rm-ok   .rm-fill { background: linear-gradient(90deg, #34D399, #059669); }
  .rm-warn .rm-fill { background: linear-gradient(90deg, #FCD34D, #D97706); }
  .rm-bad  .rm-fill { background: linear-gradient(90deg, #FCA5A5, #DC2626); }
}

/* ════════════════════════════════════════════════════════════
   3. ██ TABLET  (640px ~ 1023px)
════════════════════════════════════════════════════════════ */
@media (min-width: 640px) and (max-width: 1023px) {

  .app-mobile, .app-desktop { display: none !important; }
  .app-tablet { display: flex; flex-direction: column; min-height: 100vh; }

  .tb-header {
    background: linear-gradient(170deg, var(--navy) 0%, var(--navy-2) 100%);
    padding: 20px 24px 0;
    display: flex; flex-direction: column; gap: 16px;
  }
  .tb-top-row { display: flex; align-items: center; justify-content: space-between; }
  .tb-brand {
    font-size: 15px; font-weight: 800; color: #fff;
    display: flex; align-items: center; gap: 10px; letter-spacing: -.03em;
  }
  .tb-brand-icon {
    width: 30px; height: 30px; border-radius: 8px;
    background: linear-gradient(135deg, var(--indigo), var(--indigo-l));
    display: flex; align-items: center; justify-content: center; font-size: 14px;
  }
  .tb-pulse { width: 7px; height: 7px; border-radius: 50%;
    background: var(--green-l); box-shadow: 0 0 8px rgba(52,211,153,.5); }
  .tb-badge-row { display: flex; align-items: center; gap: 8px; }

  .tb-tabs { display: flex; }
  .tb-tab {
    flex: 1; padding: 12px 8px;
    text-align: center; font-size: 12px; font-weight: 600;
    color: rgba(255,255,255,.45); border-bottom: 2px solid transparent;
    cursor: pointer; transition: all .15s; user-select: none;
  }
  .tb-tab.active { color: #fff; border-bottom-color: var(--indigo-l); }

  .tb-content { flex: 1; padding: 20px 24px; }
  .tb-section { display: none; }
  .tb-section.active { display: block; }

  .tb-kpi-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 18px;
  }
  .tb-kpi {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow-sm); border: 1px solid var(--border);
    padding: 16px; position: relative; overflow: hidden;
  }
  .tb-kpi::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
    background: var(--indigo-l);
  }
  .tb-kpi.accent {
    background: linear-gradient(135deg, var(--navy), var(--navy-3)); color: #fff; border-color: transparent;
  }
  .tb-kpi.accent::before { background: rgba(255,255,255,.2); }
  .tb-kpi .kpi-lbl { font-size: 10px; font-weight: 700; color: var(--text-3);
    text-transform: uppercase; letter-spacing: .07em; margin-bottom: 6px; }
  .tb-kpi.accent .kpi-lbl { color: rgba(165,180,252,.75); }
  .tb-kpi .kpi-val { font-size: 18px; font-weight: 800; letter-spacing: -.03em; }
  .tb-kpi .kpi-note { font-size: 11px; color: var(--text-3); margin-top: 4px; }
  .tb-kpi.accent .kpi-note { color: rgba(199,210,254,.8); }

  .tb-panel {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow-sm); border: 1px solid var(--border);
    overflow: hidden; margin-bottom: 16px;
  }
  .tb-ph {
    padding: 14px 18px 12px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    background: var(--card-2);
  }
  .tb-pb { padding: 16px 18px; }
  .tb-row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }

  .tb-tbl { width: 100%; border-collapse: collapse; }
  .tb-tbl thead tr { background: var(--card-2); }
  .tb-tbl th { text-align: left; padding: 8px 14px; font-size: 10px; font-weight: 700;
    color: var(--text-3); text-transform: uppercase; border-bottom: 1px solid var(--border); }
  .tb-tbl td { padding: 11px 14px; border-bottom: 1px solid var(--border); font-size: 13px; }
  .tb-tbl tbody tr:last-child td { border-bottom: none; }
  .tb-tbl tbody tr:hover td { background: var(--bg); }
}

/* ════════════════════════════════════════════════════════════
   4. ██ MOBILE  (max-width: 639px)
════════════════════════════════════════════════════════════ */
@media (max-width: 639px) {

  .app-desktop, .app-tablet { display: none !important; }
  .app-mobile {
    display: flex; flex-direction: column;
    min-height: 100vh; background: var(--bg);
    padding-bottom: var(--tab-h);
  }

  .mb-hero {
    background: linear-gradient(160deg, var(--navy) 0%, #1a3260 60%, var(--navy-3) 100%);
    padding: 24px 20px 28px; color: #fff; position: relative; overflow: hidden;
  }
  .mb-hero::after {
    content: ''; position: absolute; top: -60px; right: -60px;
    width: 200px; height: 200px;
    background: radial-gradient(circle, rgba(79,70,229,.2) 0%, transparent 70%);
    pointer-events: none;
  }
  .mb-hero-top {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px; position: relative; z-index: 1;
  }
  .mb-brand { font-size: 13px; font-weight: 700; color: rgba(255,255,255,.6);
    display: flex; align-items: center; gap: 6px; }
  .mb-brand-dot { width: 6px; height: 6px; border-radius: 50%;
    background: var(--green-l); box-shadow: 0 0 8px rgba(52,211,153,.6); }
  .mb-time { font-size: 12px; color: rgba(255,255,255,.4); font-variant-numeric: tabular-nums; }
  .mb-greeting { font-size: 20px; font-weight: 800; letter-spacing: -.04em; margin-bottom: 4px; position: relative; z-index: 1; }
  .mb-sub { font-size: 12px; color: rgba(255,255,255,.5); position: relative; z-index: 1; }

  .mb-asset-card {
    background: rgba(255,255,255,.1); border-radius: var(--radius);
    border: 1px solid rgba(255,255,255,.12);
    padding: 16px 18px; margin-top: 18px;
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    position: relative; z-index: 1;
  }
  .mb-asset-lbl { font-size: 10px; color: rgba(255,255,255,.55); margin-bottom: 5px;
    text-transform: uppercase; letter-spacing: .08em; font-weight: 700; }
  .mb-asset-val { font-size: 28px; font-weight: 800; letter-spacing: -.05em; }
  .mb-asset-sub { font-size: 12px; color: rgba(255,255,255,.6); margin-top: 5px;
    display: flex; align-items: center; gap: 8px; }
  .mb-asset-sub .sep { width: 1px; height: 12px; background: rgba(255,255,255,.25); }

  .mb-metrics-scroll {
    display: flex; gap: 10px; padding: 14px 16px;
    overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none;
  }
  .mb-metrics-scroll::-webkit-scrollbar { display: none; }
  .mb-metric {
    flex-shrink: 0; background: var(--card); border-radius: var(--radius);
    border: 1px solid var(--border); box-shadow: var(--shadow-xs);
    padding: 12px 16px; min-width: 120px;
  }
  .mb-metric .kpi-lbl { font-size: 9px; font-weight: 700; color: var(--text-3);
    text-transform: uppercase; letter-spacing: .07em; margin-bottom: 5px; }
  .mb-metric .kpi-val  { font-size: 16px; font-weight: 700; letter-spacing: -.02em; }
  .mb-metric .kpi-note { font-size: 10px; color: var(--text-3); margin-top: 2px; }

  .mb-section { display: none; padding: 0 14px 14px; }
  .mb-section.active { display: block; }
  .mb-section-title {
    font-size: 15px; font-weight: 700; padding: 18px 14px 10px;
    position: sticky; top: 0; background: var(--bg); z-index: 5;
    letter-spacing: -.02em;
  }

  .mb-card {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow-xs); border: 1px solid var(--border);
    overflow: hidden; margin-bottom: 12px;
  }
  .mb-card-hdr {
    padding: 12px 16px 10px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    background: var(--card-2);
  }
  .mb-card-body { padding: 14px 16px; }

  .mb-holding {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 0; border-bottom: 1px solid var(--border);
  }
  .mb-holding:last-child { border-bottom: none; }
  .mb-h-icon {
    width: 36px; height: 36px; border-radius: 9px;
    background: var(--indigo-bg); display: flex; align-items: center; justify-content: center;
    font-size: 14px; flex-shrink: 0; font-weight: 800; color: var(--indigo);
  }
  .mb-h-info   { flex: 1; min-width: 0; }
  .mb-h-name   { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .mb-h-sub    { font-size: 10px; color: var(--text-3); margin-top: 1px; }
  .mb-h-prog   { margin-top: 4px; }
  .mb-h-right  { text-align: right; flex-shrink: 0; }
  .mb-h-pct    { font-size: 13px; font-weight: 700; }
  .mb-h-amount { font-size: 10px; color: var(--text-3); margin-top: 2px; }

  .mb-risk-row { padding: 12px 0; border-bottom: 1px solid var(--border); }
  .mb-risk-row:last-child { border-bottom: none; }
  .mb-risk-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .mb-risk-label { font-size: 13px; font-weight: 500; color: var(--text-1); }
  .mb-risk-value { font-size: 13px; font-weight: 700; }

  .mb-tabbar {
    position: fixed; bottom: 0; left: 0; right: 0;
    height: var(--tab-h);
    background: rgba(255,255,255,.92);
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
    border-top: 1px solid var(--border);
    display: flex; align-items: center;
    z-index: 100;
    padding-bottom: env(safe-area-inset-bottom, 0);
  }
  .mb-tab {
    flex: 1; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 4px; padding: 8px 0;
    color: var(--text-4); cursor: pointer; transition: color .15s; user-select: none;
    -webkit-tap-highlight-color: transparent;
  }
  .mb-tab svg  { width: 22px; height: 22px; }
  .mb-tab span { font-size: 10px; font-weight: 600; }
  .mb-tab.active       { color: var(--indigo); }
  .mb-tab.active svg   { stroke: var(--indigo); }
}

/* ════════════════════════════════════════════════════════════
   Login Overlay
════════════════════════════════════════════════════════════ */
#login-overlay {
  position: fixed; inset: 0; z-index: 9999;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at 50% 40%,
    rgba(79,70,229,.20) 0%, rgba(11,22,40,.97) 68%);
}
.login-box {
  width: 360px; max-width: calc(100vw - 32px);
  background: rgba(18,32,56,.90);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(129,140,248,.20);
  border-radius: 20px;
  padding: 40px 36px;
  box-shadow: 0 32px 80px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.04);
}
.login-logo { text-align: center; margin-bottom: 28px; }
.login-logo-icon {
  width: 52px; height: 52px;
  background: var(--indigo);
  border-radius: 14px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 26px; margin-bottom: 12px;
}
.login-title { font-size: 20px; font-weight: 700; color: #fff; margin-bottom: 4px; }
.login-sub   { font-size: 13px; color: var(--text-3); }
.login-field { margin-bottom: 10px; }
.login-field label {
  display: block; font-size: 12px; font-weight: 500;
  color: var(--text-3); margin-bottom: 6px; letter-spacing: .03em;
}
.login-input {
  width: 100%; padding: 13px 16px;
  background: rgba(255,255,255,.06);
  border: 1px solid rgba(255,255,255,.10);
  border-radius: 12px;
  color: #fff; font-family: inherit; font-size: 15px;
  outline: none; transition: border-color .2s, box-shadow .2s;
}
.login-input::placeholder { color: rgba(148,163,184,.5); }
.login-input:focus {
  border-color: rgba(79,70,229,.60);
  box-shadow: 0 0 0 3px rgba(79,70,229,.18);
}
.login-err {
  color: #FF453A; font-size: 12px; min-height: 18px;
  margin-bottom: 10px; text-align: center;
}
.login-btn {
  width: 100%; padding: 13px;
  background: var(--indigo); color: #fff;
  border-radius: 12px; font-size: 15px; font-weight: 600;
  letter-spacing: .01em;
  transition: opacity .15s, transform .1s;
}
.login-btn:hover  { opacity: .88; }
.login-btn:active { transform: scale(.98); }
</style>
</head>
<body>

<!-- Login Overlay -->
<div id="login-overlay">
  <div class="login-box">
    <div class="login-logo">
      <div class="login-logo-icon">⚡</div>
      <div class="login-title">ETF 퀀트봇</div>
      <div class="login-sub">대시보드에 로그인하세요</div>
    </div>
    <div class="login-field">
      <label>비밀번호</label>
      <input id="pw-input" class="login-input" type="password"
             placeholder="비밀번호 입력" autocomplete="current-password">
    </div>
    <div id="login-err" class="login-err"></div>
    <button class="login-btn" onclick="doLogin()">대시보드 접속 →</button>
  </div>
</div>

<!-- ════════════════════════════════════════════════════════
     DESKTOP  (≥ 1024px)
════════════════════════════════════════════════════════ -->
<div class="app-desktop">

  <aside class="sidebar">
    <div class="sb-logo">
      <div class="sb-brand">
        <div class="sb-brand-icon">⚡</div>
        <div class="sb-brand-text">
          <div class="sb-brand-name">ETF 퀀트봇</div>
          <div class="sb-brand-sub">Auto Portfolio System</div>
        </div>
        <div class="pulse-dot"></div>
      </div>
    </div>
    <nav class="sb-nav">
      <div class="sb-sec-lbl">메인</div>
      <div class="sb-nav-item active" data-view="all">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
        대시보드
      </div>
      <div class="sb-nav-item" data-view="nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        NAV 추이
      </div>
      <div class="sb-nav-item" data-view="holdings">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        전략 관리
      </div>
      <div class="sb-nav-sep"></div>
      <div class="sb-sec-lbl">분석</div>
      <div class="sb-nav-item" data-view="backtest">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>
        백테스트
      </div>
      <div class="sb-nav-item" data-view="risk">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        리스크
      </div>
    </nav>
    <div class="sb-footer">
      <div class="sf-label">현재 전략</div>
      <div class="sf-strat">%%STRATEGY%%</div>
      <span class="mode-badge %%MODE_CLASS%%">%%MODE_LABEL%%</span>
    </div>
  </aside>

  <div class="dt-main">
    <div class="dt-topbar">
      <div class="dt-topbar-left">
        <h2>%%GREETING%%</h2>
        <p>%%UPDATED%%</p>
      </div>
      <div class="dt-topbar-right">
        <div class="time-pill" id="dt-clock">--:--:--</div>
        <button class="tb-btn btn-dryrun" onclick="triggerRebalance(true)">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>
          드라이런
        </button>
        <button class="tb-btn btn-rebalance" onclick="confirmRebalance()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.83"/></svg>
          리밸런싱
        </button>
        <button class="tb-btn btn-refresh" onclick="location.reload()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-.48-4.08"/></svg>
          새로고침
        </button>
      </div>
    </div>

    <div class="dt-content">
      <div id="rb-result-panel" style="display:none"></div>

      <div class="dt-kpi-grid" id="dt-sec-kpi">%%DT_KPIS%%</div>

      <div class="dt-row col-3-1" id="dt-sec-nav">
        <div class="dt-panel">
          <div class="dt-ph">
            <div><div class="panel-title">NAV 추이</div><div class="panel-sub">일별 순자산가치</div></div>
            <span id="dt-nav-badge" style="font-size:12px;font-weight:700"></span>
          </div>
          <div class="dt-pb">
            <canvas id="dtNavChart" height="90"></canvas>
            <div id="dtNavEmpty" class="empty-state" style="display:none">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 3v18h18"/><path d="M7 16l4-4 4 4 5-5"/></svg>
              <span>장 마감(15:35) 후 기록됩니다</span>
            </div>
          </div>
        </div>
        <div class="dt-panel">
          <div class="dt-ph"><div><div class="panel-title">최근 활동</div><div class="panel-sub">리밸런싱 기록</div></div></div>
          <div class="dt-pb log-list" id="dt-log">
            <div class="log-item"><div class="log-dot ld-info"></div><div><div class="log-text">대기 중</div><div class="log-meta">매월 첫 영업일 15:15</div></div></div>
          </div>
        </div>
      </div>

      <div class="dt-row col-2" id="dt-sec-holdings">
        <div class="dt-panel">
          <div class="dt-ph">
            <div><div class="panel-title">보유 종목</div><div class="panel-sub" id="dt-hold-count">--</div></div>
            %%DT_STATUS_BADGE%%
          </div>
          <table class="dt-tbl"><thead><tr>
            <th>종목</th><th>수량</th><th>평균단가</th><th>평가금액</th><th>비중</th><th>수익률</th>
          </tr></thead><tbody>%%DT_ROWS%%</tbody></table>
        </div>
        <div class="dt-panel">
          <div class="dt-ph"><div><div class="panel-title">목표 vs 현재 비중</div><div class="panel-sub">전략 목표 대비 실제 배분</div></div></div>
          <div class="dt-pb">
            <canvas id="dtWeightChart" height="200"></canvas>
            <div id="dtWeightEmpty" class="empty-state" style="display:none">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 21H3V3"/><path d="M7 14l4-4 4 4 5-5"/></svg>
              <span>리밸런싱 실행 후 표시됩니다</span>
            </div>
          </div>
        </div>
      </div>

      <div class="dt-row col-3" id="dt-sec-risk">
        <div class="dt-panel">
          <div class="dt-ph"><div><div class="panel-title">리스크 미터</div><div class="panel-sub">실시간 리스크 지표</div></div></div>
          <div class="dt-pb risk-meter">%%DT_RISK_METERS%%</div>
        </div>
        <div class="dt-panel">
          <div class="dt-ph"><div><div class="panel-title">전략 정보</div><div class="panel-sub">현재 운용 전략</div></div></div>
          <div class="dt-pb">%%DT_STRAT_INFO%%</div>
        </div>
        <div class="dt-panel">
          <div class="dt-ph"><div><div class="panel-title">시스템 상태</div><div class="panel-sub">봇 운용 정보</div></div></div>
          <div class="dt-pb">%%DT_SYS_INFO%%</div>
        </div>
      </div>
    </div>
  </div>
</div>


<!-- ════════════════════════════════════════════════════════
     TABLET  (640px ~ 1023px)
════════════════════════════════════════════════════════ -->
<div class="app-tablet">
  <div class="tb-header">
    <div class="tb-top-row">
      <div class="tb-brand">
        <div class="tb-brand-icon">⚡</div>
        ETF 퀀트봇
        <div class="tb-pulse"></div>
      </div>
      <div class="tb-badge-row">
        <span class="mode-badge %%MODE_CLASS%%">%%MODE_LABEL%%</span>
        %%TB_STATUS_BADGE%%
      </div>
    </div>
    <div class="tb-tabs">
      <div class="tb-tab active" data-tab="tb-overview">개요</div>
      <div class="tb-tab" data-tab="tb-holdings">보유종목</div>
      <div class="tb-tab" data-tab="tb-nav">NAV 추이</div>
      <div class="tb-tab" data-tab="tb-risk">리스크</div>
    </div>
  </div>
  <div class="tb-content">
    <div class="tb-section active" id="tb-overview">
      <div class="tb-kpi-grid">%%TB_KPIS%%</div>
      <div class="tb-row-2">
        <div class="tb-panel">
          <div class="tb-ph"><div class="panel-title">NAV 추이</div><span id="tb-nav-badge" style="font-size:12px;font-weight:700"></span></div>
          <div class="tb-pb"><canvas id="tbNavChart" height="120"></canvas></div>
        </div>
        <div class="tb-panel">
          <div class="tb-ph"><div class="panel-title">비중 배분</div></div>
          <div class="tb-pb"><canvas id="tbWeightChart" height="120"></canvas></div>
        </div>
      </div>
    </div>
    <div class="tb-section" id="tb-holdings">
      <div class="tb-panel">
        <table class="tb-tbl"><thead><tr>
          <th>종목</th><th>평가금액</th><th>비중</th><th>수익률</th>
        </tr></thead><tbody>%%TB_ROWS%%</tbody></table>
      </div>
    </div>
    <div class="tb-section" id="tb-nav">
      <div class="tb-panel">
        <div class="tb-ph"><div><div class="panel-title">NAV 추이</div><div class="panel-sub">일별 포트폴리오 순자산가치</div></div></div>
        <div class="tb-pb"><canvas id="tbNavChart2" height="200"></canvas></div>
      </div>
    </div>
    <div class="tb-section" id="tb-risk">
      <div class="tb-panel">
        <div class="tb-ph"><div class="panel-title">리스크 현황</div></div>
        <div class="tb-pb risk-meter">%%TB_RISK_METERS%%</div>
      </div>
    </div>
  </div>
</div>


<!-- ════════════════════════════════════════════════════════
     MOBILE  (≤ 639px)
════════════════════════════════════════════════════════ -->
<div class="app-mobile">
  <div class="mb-hero">
    <div class="mb-hero-top">
      <div class="mb-brand"><div class="mb-brand-dot"></div>ETF 퀀트봇</div>
      <div class="mb-time" id="mb-clock">--:--:--</div>
    </div>
    <div class="mb-greeting">%%GREETING%%</div>
    <div class="mb-sub">%%UPDATED%%</div>
    <div class="mb-asset-card">
      <div class="mb-asset-lbl">총 자산</div>
      <div class="mb-asset-val">%%MB_TOTAL%%</div>
      <div class="mb-asset-sub">
        <span class="%%MB_PNL_CLS%%">%%MB_PNL%%</span>
        <span class="sep"></span>
        <span>%%MB_STATUS_BADGE%%</span>
      </div>
    </div>
  </div>

  <div class="mb-metrics-scroll">%%MB_METRICS%%</div>

  <div class="mb-section active" id="mb-home">
    <div class="mb-section-title">포트폴리오</div>
    <div class="mb-card">
      <div class="mb-card-hdr">
        <div class="panel-title">보유 종목</div>
        <span style="font-size:11px;color:var(--text-3)">%%MB_HOLD_COUNT%%</span>
      </div>
      <div class="mb-card-body">%%MB_HOLDINGS%%</div>
    </div>
    <div class="mb-card">
      <div class="mb-card-hdr"><div class="panel-title">NAV 추이</div><span id="mb-nav-badge" style="font-size:12px;font-weight:700"></span></div>
      <div class="mb-card-body" style="padding:12px 16px">
        <canvas id="mbNavChart" height="130"></canvas>
        <div id="mbNavEmpty" class="empty-state" style="display:none;padding:24px 0">
          <span>장 마감(15:35) 후 기록됩니다</span>
        </div>
      </div>
    </div>
  </div>

  <div class="mb-section" id="mb-weights">
    <div class="mb-section-title">목표 비중</div>
    <div class="mb-card">
      <div class="mb-card-body" style="padding:12px 16px">
        <canvas id="mbWeightChart" height="220"></canvas>
        <div id="mbWeightEmpty" class="empty-state" style="display:none;padding:24px 0">
          <span>리밸런싱 실행 후 표시됩니다</span>
        </div>
      </div>
    </div>
  </div>

  <div class="mb-section" id="mb-risk">
    <div class="mb-section-title">리스크</div>
    <div class="mb-card"><div class="mb-card-body">%%MB_RISK%%</div></div>
    <div class="mb-card">
      <div class="mb-card-hdr"><div class="panel-title">전략</div></div>
      <div class="mb-card-body" style="font-size:13px;color:var(--text-2)">%%MB_STRAT_INFO%%</div>
    </div>
  </div>

  <div class="mb-section" id="mb-activity">
    <div class="mb-section-title">최근 활동</div>
    <div class="mb-card">
      <div class="mb-card-body log-list" id="mb-log">
        <div class="log-item"><div class="log-dot ld-info"></div><div><div class="log-text">대기 중</div><div class="log-meta">매월 첫 영업일 15:15 리밸런싱</div></div></div>
      </div>
    </div>
  </div>

  <nav class="mb-tabbar">
    <div class="mb-tab active" data-sec="mb-home">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      <span>홈</span>
    </div>
    <div class="mb-tab" data-sec="mb-weights">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>
      <span>비중</span>
    </div>
    <div class="mb-tab" data-sec="mb-risk">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
      <span>리스크</span>
    </div>
    <div class="mb-tab" data-sec="mb-activity">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
      <span>활동</span>
    </div>
  </nav>
</div>


<!-- ════════════════════════════════════════════════════════
     JavaScript
════════════════════════════════════════════════════════ -->
<script>
let TOKEN = localStorage.getItem('etf_dash_token') || '';

function authFetch(url, opts) {
  const sep = url.includes('?') ? '&' : '?';
  return fetch(url + sep + 'token=' + TOKEN, opts || {});
}

async function doLogin() {
  const pw  = document.getElementById('pw-input').value;
  const err = document.getElementById('login-err');
  err.textContent = '';
  try {
    const resp = await fetch('/api/auth', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pw}),
    });
    if (resp.ok) {
      TOKEN = (await resp.json()).token;
      localStorage.setItem('etf_dash_token', TOKEN);
      document.getElementById('login-overlay').style.display = 'none';
      loadNav(); loadWeights(); loadLastResult();
    } else {
      err.textContent = '비밀번호가 올바르지 않습니다';
      document.getElementById('pw-input').select();
    }
  } catch {
    err.textContent = '서버 연결 오류';
  }
}

document.getElementById('pw-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') doLogin();
});

// Auto-login with stored token
(async function checkAuth() {
  if (!TOKEN) return;
  const resp = await authFetch('/api/status').catch(() => null);
  if (resp && resp.ok) {
    document.getElementById('login-overlay').style.display = 'none';
  } else {
    localStorage.removeItem('etf_dash_token');
    TOKEN = '';
  }
})();

Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.color       = '#94A3B8';
Chart.defaults.borderColor = 'rgba(15,23,42,.07)';

function fmtWon(v) {
  if (Math.abs(v) >= 100000000) return (v/100000000).toFixed(2)+'억원';
  if (Math.abs(v) >= 10000)     return (v/10000).toFixed(0)+'만원';
  return v.toLocaleString('ko-KR')+'원';
}

/* Chart config */
const NAV_DS = {
  borderColor: '#4F46E5',
  backgroundColor: (ctx) => {
    const c = ctx.chart.ctx, g = c.createLinearGradient(0,0,0,ctx.chart.height);
    g.addColorStop(0,'rgba(79,70,229,.14)'); g.addColorStop(1,'rgba(79,70,229,0)');
    return g;
  },
  fill: true, tension: 0.4, pointRadius: 0, pointHoverRadius: 5,
  borderWidth: 2.5, pointHoverBackgroundColor: '#4F46E5',
};
const NAV_OPTS = (tickCb) => ({
  responsive: true,
  interaction: { intersect: false, mode: 'index' },
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: '#0F172A', titleColor: '#64748B', bodyColor: '#F1F5F9',
      borderColor: 'rgba(255,255,255,.08)', borderWidth: 1,
      padding: { top:10, right:14, bottom:10, left:14 }, cornerRadius: 8,
      callbacks: { label: ctx => ' ' + ctx.parsed.y.toLocaleString('ko-KR') + '원' }
    }
  },
  scales: {
    x: { grid:{display:false}, border:{display:false},
         ticks:{maxTicksLimit:6, maxRotation:0, color:'#94A3B8', font:{size:11}} },
    y: { grid:{color:'rgba(15,23,42,.05)'}, border:{display:false},
         ticks:{callback:tickCb, color:'#94A3B8', font:{size:11}} }
  }
});
const W_DS = (color, label) => ({
  label, backgroundColor: color, borderRadius: 4, borderSkipped: false
});
const W_OPTS = {
  indexAxis: 'y', responsive: true,
  plugins: {
    legend: { position:'top', labels:{color:'#64748B', boxWidth:10, font:{size:11}} },
    tooltip: {
      backgroundColor:'#0F172A', cornerRadius:8,
      callbacks: { label: c => ' ' + c.parsed.x + '%' }
    }
  },
  scales: {
    x: { grid:{color:'rgba(15,23,42,.05)'}, border:{display:false},
         ticks:{callback:v=>v+'%', color:'#94A3B8', font:{size:11}} },
    y: { grid:{display:false}, border:{display:false},
         ticks:{color:'#64748B', font:{size:11}} }
  }
};

function navBadge(values, elId) {
  if (!values || values.length < 2) return;
  const ret = (values[values.length-1] / values[0] - 1) * 100;
  const el = document.getElementById(elId); if (!el) return;
  el.textContent = (ret>=0?'+':'')+ret.toFixed(2)+'%';
  el.style.color = ret>=0 ? 'var(--green)' : 'var(--red)';
}

function tick() {
  const t = new Date().toLocaleTimeString('ko-KR', {hour12:false});
  ['dt-clock','mb-clock'].forEach(id => { const el=document.getElementById(id); if(el) el.textContent=t; });
  setTimeout(tick, 1000);
}
tick();

async function loadNav() {
  try {
    const d = await authFetch('/api/performance').then(r=>r.json());
    if (!d.dates || d.dates.length < 2) {
      ['dtNavEmpty','mbNavEmpty'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='flex';});
      return null;
    }
    return d;
  } catch { return null; }
}
async function loadWeights() {
  try {
    const d = await authFetch('/api/target-weights').then(r=>r.json());
    if (!d.labels || d.labels.length===0) {
      ['dtWeightEmpty','mbWeightEmpty'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='flex';});
      return null;
    }
    return d;
  } catch { return null; }
}

(async function() {
  const tickFn = v => {
    if(Math.abs(v)>=100000000) return (v/100000000).toFixed(1)+'억';
    return (v/10000).toFixed(0)+'만';
  };
  const nav = await loadNav();
  if (nav) {
    ['dt-nav-badge','tb-nav-badge','mb-nav-badge'].forEach(id => navBadge(nav.values, id));
    const ds = {...NAV_DS, label:'NAV', data:nav.values};
    [
      ['dtNavChart', NAV_OPTS(tickFn)],
      ['tbNavChart', NAV_OPTS(tickFn)],
      ['tbNavChart2', NAV_OPTS(tickFn)],
      ['mbNavChart', NAV_OPTS(v=>(v/10000).toFixed(0)+'만')],
    ].forEach(([id, opts]) => {
      const el=document.getElementById(id); if(!el) return;
      new Chart(el, {type:'line', data:{labels:nav.dates, datasets:[ds]}, options:opts});
    });
  }
  const w = await loadWeights();
  if (w) {
    const data = {labels:w.labels, datasets:[
      {...W_DS('rgba(79,70,229,.75)','목표'),  data:w.target},
      {...W_DS('rgba(16,185,129,.7)','현재'), data:w.current},
    ]};
    ['dtWeightChart','tbWeightChart','mbWeightChart'].forEach(id => {
      const el=document.getElementById(id); if(!el) return;
      new Chart(el, {type:'bar', data, options:W_OPTS});
    });
  }
})();

/* Tablet tabs */
document.querySelectorAll('.tb-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tb-tab').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.tb-section').forEach(s=>s.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.add('active');
  });
});

/* Mobile tabs */
document.querySelectorAll('.mb-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.mb-tab').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.mb-section').forEach(s=>s.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.sec).classList.add('active');
    window.scrollTo({top:0, behavior:'smooth'});
  });
});

/* Rebalance */
function confirmRebalance() {
  if (confirm('⚠️ 실제 주문이 발생합니다.\n리밸런싱을 실행할까요?')) triggerRebalance(false);
}

async function triggerRebalance(dryRun) {
  const panel = document.getElementById('rb-result-panel'); if(!panel) return;
  panel.style.display = '';
  panel.innerHTML = `<div class="rb-panel rb-run"><div class="rb-header">
    <div><div class="rb-title"><span class="spin">⏳</span> ${dryRun?'[드라이런] ':''}리밸런싱 실행 중...</div>
    <div class="rb-meta">전략 신호 계산 및 주문 처리 중입니다</div></div></div></div>`;
  try {
    const resp = await authFetch('/api/rebalance?dry_run='+dryRun, {method:'POST'});
    const data = await resp.json();
    if (data.status === 'already_running') {
      panel.innerHTML = `<div class="rb-panel rb-run"><div class="rb-header">
        <div class="rb-title">⏳ 이미 실행 중입니다</div></div></div>`;
    }
    pollRebalanceResult(0);
  } catch(e) {
    panel.innerHTML = `<div class="rb-panel rb-err"><div class="rb-header">
      <div><div class="rb-title">❌ 요청 실패</div>
      <div class="rb-meta">${e.message}</div></div></div></div>`;
  }
}

async function pollRebalanceResult(attempt) {
  if (attempt > 60) return;
  try {
    const d = await authFetch('/api/rebalance-result').then(r=>r.json());
    if (!d || d.status==='none')  { setTimeout(()=>pollRebalanceResult(attempt+1), 2000); return; }
    if (d.status==='running')     { setTimeout(()=>pollRebalanceResult(attempt+1), 2000); return; }
    renderRebalanceResult(d);
  } catch { setTimeout(()=>pollRebalanceResult(attempt+1), 3000); }
}

function renderRebalanceResult(d) {
  const panel = document.getElementById('rb-result-panel'); if(!panel) return;
  const isDry = d.is_dry_run, isErr = d.status==='error';
  const cls   = isErr?'rb-err':(isDry?'rb-dry':'');
  const icon  = isErr?'❌':(isDry?'📊':'✅');
  const badge = isDry
    ? `<span style="background:var(--amber-bg);color:#92400E;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700">DRY RUN</span>`
    : '';
  const dt = d.executed_at ? d.executed_at.replace('T',' ').slice(0,16) : '';

  if (isErr) {
    panel.innerHTML = `<div class="rb-panel rb-err"><div class="rb-header">
      <div><div class="rb-title">${icon} 리밸런싱 오류 ${badge}</div>
      <div class="rb-meta">${d.error||''} · ${dt}</div></div>
      <button onclick="document.getElementById('rb-result-panel').style.display='none'"
        style="background:none;color:var(--text-3);font-size:18px;padding:4px;cursor:pointer">✕</button>
    </div></div>`; return;
  }

  const orderRows = (d.orders||[]).map(o => {
    const sh = o.side==='buy' ? "<span class='side-buy'>▲ 매수</span>" : "<span class='side-sell'>▼ 매도</span>";
    return `<tr>
      <td><div style="font-weight:600">${o.name}</div><div style="font-size:10px;color:var(--text-4)">${o.ticker}</div></td>
      <td>${sh}</td><td>${o.qty.toLocaleString()}주</td><td>${o.price.toLocaleString()}원</td>
      <td><span style="color:var(--text-3)">${o.cur_w}%</span> → <b>${o.tgt_w}%</b></td>
      <td style="font-weight:700">${(o.tgt_w-o.cur_w)>=0?'+':''}${(o.tgt_w-o.cur_w).toFixed(1)}%</td>
    </tr>`;
  }).join('');

  panel.innerHTML = `<div class="rb-panel ${cls}">
    <div class="rb-header">
      <div><div class="rb-title">${icon} 리밸런싱 완료 ${badge}</div>
      <div class="rb-meta">실행시각: ${dt}</div></div>
      <button onclick="document.getElementById('rb-result-panel').style.display='none'"
        style="background:none;color:var(--text-3);font-size:18px;padding:4px;cursor:pointer">✕</button>
    </div>
    <div class="rb-stats">
      <div class="rb-stat"><div class="rb-stat-val" style="color:var(--green)">${d.success_count}</div><div class="rb-stat-lbl">성공</div></div>
      <div class="rb-stat"><div class="rb-stat-val" style="color:${d.fail_count>0?'var(--red)':'var(--text-4)'}">${d.fail_count}</div><div class="rb-stat-lbl">실패</div></div>
      <div class="rb-stat"><div class="rb-stat-val" style="color:var(--text-3)">${d.skipped_count}</div><div class="rb-stat-lbl">스킵</div></div>
      <div class="rb-stat"><div class="rb-stat-val">${d.total_turnover?.toFixed(1)??0}%</div><div class="rb-stat-lbl">회전율</div></div>
      <div class="rb-stat"><div class="rb-stat-val">${((d.total_assets||0)/10000).toFixed(0)}만원</div><div class="rb-stat-lbl">총자산</div></div>
    </div>
    ${(d.orders||[]).length>0
      ? `<table class="rb-tbl"><thead><tr><th>종목</th><th>방향</th><th>수량</th><th>가격</th><th>비중 변화</th><th>차이</th></tr></thead><tbody>${orderRows}</tbody></table>`
      : `<div style="padding:24px 20px;color:var(--text-3);font-size:13px">리밸런싱 불필요 — 모든 비중이 임계값(±3%) 이내입니다</div>`}
  </div>`;
}

(async function loadLastResult() {
  try {
    const d = await authFetch('/api/rebalance-result').then(r=>r.json());
    if (d && d.status!=='none' && d.status!=='running') renderRebalanceResult(d);
  } catch {}
})();

/* Desktop sidebar */
(function() {
  const sectionMap = {
    all:      ['dt-sec-kpi','dt-sec-nav','dt-sec-holdings','dt-sec-risk'],
    nav:      ['dt-sec-kpi','dt-sec-nav'],
    holdings: ['dt-sec-kpi','dt-sec-holdings'],
    backtest: ['dt-sec-kpi'],
    risk:     ['dt-sec-kpi','dt-sec-risk'],
  };
  const btMsg = document.createElement('div');
  btMsg.id = 'dt-sec-backtest';
  btMsg.style.cssText = 'display:none;text-align:center;padding:80px 20px;color:var(--text-3)';
  btMsg.innerHTML = '<div style="font-size:48px;margin-bottom:16px;opacity:.25">📊</div>'
    +'<div style="font-size:15px;font-weight:700;color:var(--text-2);margin-bottom:6px">백테스트 준비 중</div>'
    +'<div style="font-size:13px">run_backtest.py를 실행하여 결과를 확인하세요</div>';
  const dtContent = document.querySelector('.dt-content');
  if (dtContent) dtContent.appendChild(btMsg);

  document.querySelectorAll('.sb-nav-item[data-view]').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.sb-nav-item').forEach(i=>i.classList.remove('active'));
      item.classList.add('active');
      const view = item.dataset.view;
      const show = sectionMap[view] || sectionMap.all;
      Object.values(sectionMap).flat().forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='none';});
      btMsg.style.display='none';
      if (view==='backtest') {
        document.getElementById('dt-sec-kpi').style.display='';
        btMsg.style.display='';
      } else {
        show.forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='';});
      }
      window.scrollTo({top:0, behavior:'smooth'});
    });
  });
})();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# 빌드 헬퍼
# ─────────────────────────────────────────────────────────────

def _pcc(v: float) -> str:
    return "pos" if v > 0 else ("neg" if v < 0 else "neu")


def _greeting() -> str:
    h = datetime.now().hour
    return ("안녕하세요 👋" if h < 6 else
            "좋은 아침입니다 ☀️" if h < 12 else
            "좋은 오후입니다 📈" if h < 18 else
            "좋은 저녁입니다 🌙")


def _status_badge(mdd: float, is_halted: bool) -> tuple[str, str]:
    if is_halted:
        return ("<span class='badge b-halt'><span class='badge-dot'></span>거래 중단</span>", "b-halt")
    if mdd <= -0.08:
        return ("<span class='badge b-warn'><span class='badge-dot'></span>경고</span>", "b-warn")
    return ("<span class='badge b-ok'><span class='badge-dot'></span>정상 운용</span>", "b-ok")


def _info_row(label: str, value: str, value_color: str = "var(--text-1)") -> str:
    return (
        f"<div style='display:flex;justify-content:space-between;align-items:center;"
        f"padding:8px 0;border-bottom:1px solid var(--border)'>"
        f"<span style='font-size:12px;color:var(--text-3);font-weight:500'>{label}</span>"
        f"<span style='font-size:12px;font-weight:700;color:{value_color}'>{value}</span>"
        f"</div>"
    )


def _risk_meter(label: str, value_pct: float, limit_pct: float, unit: str = "%") -> str:
    ratio = min(abs(value_pct / limit_pct) if limit_pct else 0, 1.0) * 100
    cls   = "rm-bad" if ratio >= 80 else ("rm-warn" if ratio >= 50 else "rm-ok")
    val_color = ("neg" if value_pct > 0 else "neu")
    return (
        f"<div class='rm-item {cls}'>"
        f"<div class='rm-row'>"
        f"<span class='rm-label'>{label}</span>"
        f"<span class='rm-value {val_color}'>{value_pct:+.2f}{unit} / {limit_pct:.0f}{unit}</span>"
        f"</div>"
        f"<div class='rm-track'><div class='rm-fill' style='width:{ratio:.1f}%'></div></div>"
        f"</div>"
    )


def _mb_risk_row(label: str, value_str: str, ratio: float, cls: str) -> str:
    bar_cls = "rm-ok" if ratio < 50 else ("rm-warn" if ratio < 80 else "rm-bad")
    return (
        f"<div class='mb-risk-row'>"
        f"<div class='mb-risk-top'>"
        f"<span class='mb-risk-label'>{label}</span>"
        f"<span class='mb-risk-value {cls}'>{value_str}</span>"
        f"</div>"
        f"<div class='prog-wrap {bar_cls}'>"
        f"<div class='prog-bar' style='width:{min(ratio,100):.1f}%;background:inherit'></div>"
        f"</div></div>"
    )


def _strat_info_html(strategy_name: str, mode: str) -> str:
    mode_map = {"kis_real": "실전 매매", "kis_paper": "KIS 모의", "paper": "페이퍼"}
    rows = (
        _info_row("전략", strategy_name)
        + _info_row("모드", mode_map.get(mode, mode))
        + _info_row("리밸런싱", "매월 첫 영업일 15:15")
        + f"<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0'>"
        f"<span style='font-size:12px;color:var(--text-3);font-weight:500'>임계값</span>"
        f"<span style='font-size:12px;font-weight:700;color:var(--text-1)'>±3%</span></div>"
    )
    return f"<div style='font-size:13px'>{rows}</div>"


def _sys_info_html(mdd: float) -> str:
    now = datetime.now()
    market_open = 9 <= now.hour < 15 or (now.hour == 15 and now.minute < 30)
    market_color = "var(--green)" if market_open else "var(--text-2)"
    mdd_color    = "var(--red)" if mdd <= -0.08 else "var(--text-1)"
    rows = (
        _info_row("시장 상태", "장중 ●" if market_open else "장외 ○", market_color)
        + _info_row("현재 MDD",  f"{mdd*100:+.2f}%", mdd_color)
        + _info_row("하드스탑",  "-18%")
        + f"<div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0'>"
        f"<span style='font-size:12px;color:var(--text-3);font-weight:500'>업데이트</span>"
        f"<span style='font-size:12px;font-weight:700;color:var(--text-1)'>{now.strftime('%H:%M')}</span></div>"
    )
    return f"<div style='font-size:13px'>{rows}</div>"


def _build_html(bot: "ETFQuantBot") -> str:
    try:
        balance = bot.broker.get_balance()
        risk_st = bot.guard.get_status()
    except Exception as e:
        return (
            "<div style='font-family:Inter,sans-serif;background:#EEF2F9;min-height:100vh;"
            "display:flex;align-items:center;justify-content:center'>"
            f"<div style='background:#fff;border-radius:12px;padding:32px 40px;"
            f"box-shadow:0 2px 12px rgba(0,0,0,.08);border:1px solid rgba(15,23,42,.08)'>"
            f"<h2 style='color:#DC2626;margin-bottom:8px;font-family:Inter,sans-serif'>연결 오류</h2>"
            f"<p style='color:#64748B;font-size:13px;font-family:Inter,sans-serif'>{e}</p></div></div>"
        )

    total     = balance.total_assets
    mdd       = risk_st["current_mdd"]
    is_halted = risk_st["is_halted"]
    pnl       = balance.total_pnl
    pnl_rate  = balance.total_pnl_rate
    daily_loss = risk_st.get("daily_loss", 0.0)

    strategy_name = getattr(bot, "strategy_name", "MultiStrategy")
    mode          = getattr(bot, "mode", "paper")
    mode_cls      = "mode-live" if mode == "kis_real" else "mode-paper"
    mode_label    = "● LIVE" if mode == "kis_real" else "○ PAPER"

    status_badge, _  = _status_badge(mdd, is_halted)
    holdings_sorted  = sorted(balance.holdings, key=lambda x: x.eval_amount, reverse=True)
    hold_count       = len(holdings_sorted)

    now_str      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    greeting_str = _greeting()

    # ── Desktop KPI ──────────────────────────────────────────
    dt_kpis = (
        f"<div class='dt-kpi accent'><div class='kpi-ico'>💰</div>"
        f"<div class='kpi-lbl'>총 자산</div>"
        f"<div class='kpi-val'>{total/10000:.0f}만원</div>"
        f"<div class='kpi-note'>예수금 {balance.cash/10000:.0f}만원</div></div>"

        f"<div class='dt-kpi kpi-green'><div class='kpi-ico'>📈</div>"
        f"<div class='kpi-lbl'>평가 손익</div>"
        f"<div class='kpi-val {_pcc(pnl)}'>{pnl:+,.0f}원</div>"
        f"<div class='kpi-note {_pcc(pnl_rate)}'>{pnl_rate:+.2f}%</div></div>"

        f"<div class='dt-kpi kpi-amber'><div class='kpi-ico'>🛡️</div>"
        f"<div class='kpi-lbl'>현재 MDD</div>"
        f"<div class='kpi-val {'neg' if mdd<=-0.08 else 'neu'}'>{mdd*100:+.2f}%</div>"
        f"<div class='kpi-note' style='color:var(--text-3)'>한도 -18%</div></div>"

        f"<div class='dt-kpi kpi-cyan'><div class='kpi-ico'>🤖</div>"
        f"<div class='kpi-lbl'>봇 상태</div>"
        f"<div class='kpi-val' style='font-size:15px;margin-top:4px'>{status_badge}</div>"
        f"<div class='kpi-note'>{risk_st.get('halt_reason') or '자동 매매 활성'}</div></div>"
    )

    # ── Desktop 보유종목 행 ───────────────────────────────────
    dt_rows = []
    for h in holdings_sorted:
        w = h.eval_amount / total * 100 if total > 0 else 0
        dt_rows.append(
            f"<tr>"
            f"<td><div class='t-name'>{h.name}</div><div class='t-code'>{h.ticker}</div></td>"
            f"<td>{h.qty:,}주</td>"
            f"<td>{h.avg_price:,.0f}원</td>"
            f"<td>{h.eval_amount/10000:.0f}만원</td>"
            f"<td><div style='font-size:12px;font-weight:600'>{w:.1f}%</div>"
            f"<div class='prog-wrap' style='margin-top:4px'>"
            f"<div class='prog-bar' style='width:{min(w,100):.1f}%'></div></div></td>"
            f"<td class='{_pcc(h.profit_rate)}' style='font-weight:700'>{h.profit_rate:+.1f}%</td>"
            f"</tr>"
        )
    if not dt_rows:
        dt_rows = ["<tr><td colspan='6' style='text-align:center;padding:40px;color:var(--text-3);font-size:13px'>보유 종목 없음</td></tr>"]

    # ── Tablet 보유종목 행 ────────────────────────────────────
    tb_rows = []
    for h in holdings_sorted:
        w = h.eval_amount / total * 100 if total > 0 else 0
        tb_rows.append(
            f"<tr>"
            f"<td><div style='font-weight:600'>{h.name}</div>"
            f"<div style='font-size:10px;color:var(--text-4)'>{h.ticker}</div></td>"
            f"<td>{h.eval_amount/10000:.0f}만원</td>"
            f"<td>{w:.1f}%<div class='prog-wrap' style='margin-top:4px'>"
            f"<div class='prog-bar' style='width:{min(w,100):.1f}%'></div></div></td>"
            f"<td class='{_pcc(h.profit_rate)}' style='font-weight:700'>{h.profit_rate:+.1f}%</td>"
            f"</tr>"
        )
    if not tb_rows:
        tb_rows = ["<tr><td colspan='4' style='text-align:center;padding:32px;color:var(--text-3)'>보유 종목 없음</td></tr>"]

    # ── Mobile 보유종목 ────────────────────────────────────────
    mb_holdings = []
    for h in holdings_sorted[:8]:
        w = h.eval_amount / total * 100 if total > 0 else 0
        initial = h.name[0] if h.name else "?"
        mb_holdings.append(
            f"<div class='mb-holding'>"
            f"<div class='mb-h-icon'>{initial}</div>"
            f"<div class='mb-h-info'>"
            f"<div class='mb-h-name'>{h.name}</div>"
            f"<div class='mb-h-sub'>{h.ticker} · {w:.1f}%</div>"
            f"<div class='mb-h-prog'><div class='prog-wrap'>"
            f"<div class='prog-bar' style='width:{min(w,100):.1f}%'></div></div></div>"
            f"</div>"
            f"<div class='mb-h-right'>"
            f"<div class='mb-h-pct {_pcc(h.profit_rate)}'>{h.profit_rate:+.1f}%</div>"
            f"<div class='mb-h-amount'>{h.eval_amount/10000:.0f}만원</div>"
            f"</div></div>"
        )
    if not mb_holdings:
        mb_holdings = ["<div style='text-align:center;color:var(--text-3);padding:24px;font-size:13px'>보유 종목 없음</div>"]

    # ── Mobile 지표 스크롤 ────────────────────────────────────
    mb_metrics = (
        f"<div class='mb-metric'><div class='kpi-lbl'>평가 손익</div>"
        f"<div class='kpi-val {_pcc(pnl)}'>{pnl/10000:+.0f}만</div>"
        f"<div class='kpi-note {_pcc(pnl_rate)}'>{pnl_rate:+.2f}%</div></div>"

        f"<div class='mb-metric'><div class='kpi-lbl'>현재 MDD</div>"
        f"<div class='kpi-val {'neg' if mdd<=-0.08 else 'neu'}'>{mdd*100:+.2f}%</div>"
        f"<div class='kpi-note'>한도 -18%</div></div>"

        f"<div class='mb-metric'><div class='kpi-lbl'>예수금</div>"
        f"<div class='kpi-val neu'>{balance.cash/10000:.0f}만원</div>"
        f"<div class='kpi-note'>가용 현금</div></div>"

        f"<div class='mb-metric'><div class='kpi-lbl'>종목 수</div>"
        f"<div class='kpi-val neu'>{hold_count}개</div>"
        f"<div class='kpi-note'>보유 ETF</div></div>"
    )

    # ── 리스크 미터 ─────────────────────────────────────────
    mdd_ratio   = min(abs(mdd) / 0.18, 1.0) * 100
    daily_ratio = min(abs(daily_loss) / 0.03, 1.0) * 100

    risk_meters_html = (
        _risk_meter("MDD",       abs(mdd) * 100,       18.0)
        + _risk_meter("일간 손실", abs(daily_loss) * 100, 3.0)
        + _risk_meter("연속 손실일", risk_st.get("consecutive_loss_days", 0), 5.0, "일")
    )

    mb_risk_html = (
        _mb_risk_row("MDD",       f"{mdd*100:+.2f}%",         mdd_ratio,
                     "neg" if mdd <= -0.08 else "neu")
        + _mb_risk_row("일간 손실",  f"{daily_loss*100:+.2f}%", daily_ratio,
                       "neg" if daily_loss <= -0.03 else "neu")
        + _mb_risk_row("연속 손실일", f"{risk_st.get('consecutive_loss_days', 0)}일",
                       min(risk_st.get("consecutive_loss_days", 0) / 5 * 100, 100), "neu")
    )

    # ── Tablet KPI ────────────────────────────────────────────
    tb_kpis = (
        f"<div class='tb-kpi accent'><div class='kpi-lbl'>총 자산</div>"
        f"<div class='kpi-val'>{total/10000:.0f}만원</div>"
        f"<div class='kpi-note'>예수금 {balance.cash/10000:.0f}만원</div></div>"

        f"<div class='tb-kpi'><div class='kpi-lbl'>평가 손익</div>"
        f"<div class='kpi-val {_pcc(pnl)}'>{pnl:+,.0f}원</div>"
        f"<div class='kpi-note {_pcc(pnl_rate)}'>{pnl_rate:+.2f}%</div></div>"

        f"<div class='tb-kpi'><div class='kpi-lbl'>현재 MDD</div>"
        f"<div class='kpi-val {'neg' if mdd<=-0.08 else 'neu'}'>{mdd*100:+.2f}%</div>"
        f"<div class='kpi-note'>한도 -18%</div></div>"

        f"<div class='tb-kpi'><div class='kpi-lbl'>봇 상태</div>"
        f"<div class='kpi-val' style='font-size:15px;margin-top:4px'>{status_badge}</div>"
        f"<div class='kpi-note'>{risk_st.get('halt_reason') or '자동 매매'}</div></div>"
    )

    # ── 템플릿 치환 ───────────────────────────────────────────
    html = _TEMPLATE
    subs = {
        "%%GREETING%%":        greeting_str,
        "%%UPDATED%%":         f"마지막 업데이트: {now_str}",
        "%%STRATEGY%%":        strategy_name,
        "%%MODE_CLASS%%":      mode_cls,
        "%%MODE_LABEL%%":      mode_label,
        "%%DT_KPIS%%":         dt_kpis,
        "%%DT_STATUS_BADGE%%": status_badge,
        "%%DT_ROWS%%":         "".join(dt_rows),
        "%%DT_RISK_METERS%%":  risk_meters_html,
        "%%DT_STRAT_INFO%%":   _strat_info_html(strategy_name, mode),
        "%%DT_SYS_INFO%%":     _sys_info_html(mdd),
        "%%TB_STATUS_BADGE%%": status_badge,
        "%%TB_KPIS%%":         tb_kpis,
        "%%TB_ROWS%%":         "".join(tb_rows),
        "%%TB_RISK_METERS%%":  risk_meters_html,
        "%%MB_TOTAL%%":        f"{total/10000:.0f}만원",
        "%%MB_PNL%%":          f"{pnl_rate:+.2f}%",
        "%%MB_PNL_CLS%%":      _pcc(pnl_rate),
        "%%MB_STATUS_BADGE%%": status_badge,
        "%%MB_METRICS%%":      mb_metrics,
        "%%MB_HOLDINGS%%":     "".join(mb_holdings),
        "%%MB_HOLD_COUNT%%":   f"{hold_count}개",
        "%%MB_RISK%%":         mb_risk_html,
        "%%MB_STRAT_INFO%%":   _strat_info_html(strategy_name, mode),
    }
    for key, val in subs.items():
        html = html.replace(key, val)
    return html


# ─────────────────────────────────────────────────────────────
# FastAPI 서버
# ─────────────────────────────────────────────────────────────

def start_dashboard(bot: "ETFQuantBot", port: int = 8080) -> None:
    """대시보드 웹서버를 데몬 스레드로 시작"""
    try:
        from fastapi import FastAPI, Depends, HTTPException, Query, Body
        from fastapi.responses import HTMLResponse, JSONResponse
        import uvicorn
    except ImportError:
        logger.warning("[Dashboard] fastapi/uvicorn 미설치 → pip install fastapi uvicorn")
        return

    import time as _time

    # ── 인증 설정 ──────────────────────────────────────────────
    _password = os.getenv("DASHBOARD_SECRET", "")
    if not _password:
        _password = secrets.token_urlsafe(16)
        logger.warning(
            f"[Dashboard] DASHBOARD_SECRET 미설정 → 임시 비밀번호: {_password}\n"
            "           .env에 DASHBOARD_SECRET=원하는비밀번호 를 추가하세요."
        )

    _tokens: dict[str, float] = {}   # token → expiry timestamp

    def _new_token() -> str:
        tok = secrets.token_hex(32)
        _tokens[tok] = _time.time() + 86400   # 24h
        return tok

    def _check_token(tok: str) -> bool:
        exp = _tokens.get(tok)
        if not exp or _time.time() > exp:
            _tokens.pop(tok, None)
            return False
        return True

    def _require_token(token: str = Query("")):
        if not _check_token(token):
            raise HTTPException(status_code=401, detail="Unauthorized")

    # ── FastAPI 앱 ─────────────────────────────────────────────
    app = FastAPI(title="ETF 퀀트봇", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _build_html(bot)

    @app.post("/api/auth")
    async def api_auth(password: str = Body("", embed=True)):
        if secrets.compare_digest(
            password.encode("utf-8"),
            _password.encode("utf-8"),
        ):
            return {"token": _new_token()}
        raise HTTPException(status_code=401, detail="Invalid password")

    @app.get("/api/status")
    async def api_status(_: None = Depends(_require_token)):
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
                    {"ticker": h.ticker, "name": h.name, "qty": h.qty,
                     "eval_amount": h.eval_amount, "profit_rate": h.profit_rate}
                    for h in balance.holdings
                ],
            }
        except Exception:
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    _RB_RESULT_PATH = Path("data/cache/last_rebalance.json")
    _rb_running = threading.Event()

    @app.post("/api/rebalance")
    async def api_rebalance(dry_run: bool = True, _: None = Depends(_require_token)):
        if _rb_running.is_set():
            return {"status": "already_running"}
        _rb_running.set()

        _tmp = _RB_RESULT_PATH.with_suffix(".tmp")
        _RB_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _tmp.write_text(json.dumps({
            "status": "running", "is_dry_run": dry_run,
            "executed_at": datetime.now().isoformat(),
            "total_assets": 0, "success_count": 0,
            "fail_count": 0, "skipped_count": 0,
            "total_turnover": 0, "orders": [],
        }, ensure_ascii=False), encoding="utf-8")
        _tmp.replace(_RB_RESULT_PATH)

        def _run():
            try:
                bot.rebalance_now(dry_run=dry_run)
            except Exception:
                _t = _RB_RESULT_PATH.with_suffix(".tmp")
                _t.write_text(json.dumps({
                    "status": "error", "is_dry_run": dry_run,
                    "executed_at": datetime.now().isoformat(),
                    "error": "Rebalance failed",
                }, ensure_ascii=False), encoding="utf-8")
                _t.replace(_RB_RESULT_PATH)
            finally:
                _rb_running.clear()

        threading.Thread(target=_run, daemon=True, name="rebalance").start()
        return {"status": "started"}

    @app.get("/api/rebalance-result")
    async def api_rebalance_result(_: None = Depends(_require_token)):
        if not _RB_RESULT_PATH.exists():
            return {"status": "none"}
        try:
            return json.loads(_RB_RESULT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "none"}

    @app.get("/api/performance")
    async def api_performance(_: None = Depends(_require_token)):
        try:
            path = Path("data/cache/performance.json")
            if not path.exists():
                return {"dates": [], "values": []}
            history = json.loads(path.read_text(encoding="utf-8"))
            return {
                "dates":  [h["date"][5:] for h in history],
                "values": [h["nav"] for h in history],
            }
        except Exception:
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @app.get("/api/target-weights")
    async def api_target_weights(_: None = Depends(_require_token)):
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
        except Exception:
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    def _run():
        config = uvicorn.Config(
            app, host="0.0.0.0", port=port,
            log_level="warning", access_log=False,
        )
        uvicorn.Server(config).run()

    t = threading.Thread(target=_run, daemon=True, name="dashboard")
    t.start()
    logger.info(f"[Dashboard] 반응형 대시보드 시작 → http://0.0.0.0:{port}")
