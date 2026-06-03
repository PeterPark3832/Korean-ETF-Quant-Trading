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
<title>ETF 퀀트봇</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ════════════════════════════════════════════════════════════
   0. 리셋 + CSS 변수
════════════════════════════════════════════════════════════ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --indigo:    #4338CA;
  --indigo-d:  #312E81;
  --indigo-l:  #6366F1;
  --indigo-xl: #EEF2FF;
  --bg:        #EEF2F7;
  --card:      #FFFFFF;
  --card-alt:  #F8FAFC;
  --text-1:    #1E293B;
  --text-2:    #64748B;
  --text-3:    #94A3B8;
  --border:    #E2E8F0;
  --green:     #10B981;
  --green-bg:  #ECFDF5;
  --red:       #EF4444;
  --red-bg:    #FEF2F2;
  --amber:     #F59E0B;
  --amber-bg:  #FFFBEB;
  --shadow:    0 2px 12px rgba(0,0,0,.06);
  --radius:    14px;
  --radius-sm: 8px;

  /* 모바일 하단 탭 높이 */
  --tab-h: 64px;
}
html { -webkit-tap-highlight-color: transparent; }
body {
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text-1);
  font-size: 14px;
  line-height: 1.5;
  min-height: 100vh;
}
button { font-family: inherit; cursor: pointer; border: none; }
img { display: block; }

/* ════════════════════════════════════════════════════════════
   1. 공통 컴포넌트
════════════════════════════════════════════════════════════ */
.card {
  background: var(--card);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}
.panel-title { font-size: 14px; font-weight: 700; }
.panel-sub   { font-size: 11px; color: var(--text-2); margin-top: 2px; }

/* 색상 */
.pos { color: var(--green); }
.neg { color: var(--red);   }
.neu { color: var(--text-1);}

/* 상태 뱃지 */
.badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: 99px;
  font-size: 11px; font-weight: 600; white-space: nowrap;
}
.badge-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.b-ok   { background: var(--green-bg); color: #059669; }
.b-ok   .badge-dot { background: var(--green); }
.b-warn { background: var(--amber-bg);  color: #B45309; }
.b-warn .badge-dot { background: var(--amber); }
.b-halt { background: var(--red-bg);   color: #DC2626; }
.b-halt .badge-dot { background: var(--red); }

/* 진행바 */
.prog-wrap { background: var(--border); border-radius: 99px; height: 4px; }
.prog-bar  { background: var(--indigo-l); border-radius: 99px; height: 4px;
             transition: width .4s ease; }

/* 구분선 */
.divider { border: none; border-top: 1px solid var(--border); }

/* 로그 타임라인 */
.log-list  { display: flex; flex-direction: column; }
.log-item  { display: flex; align-items: flex-start; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); }
.log-item:last-child { border-bottom: none; }
.log-dot   { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
.ld-buy    { background: var(--green); }
.ld-sell   { background: var(--red); }
.ld-info   { background: var(--indigo-l); }
.log-text  { font-size: 13px; font-weight: 500; }
.log-meta  { font-size: 11px; color: var(--text-2); margin-top: 2px; }

/* 빈 상태 */
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 40px 16px; color: var(--text-3); font-size: 13px; gap: 8px;
}
.empty-state svg { width: 40px; height: 40px; opacity: .35; }

/* ════════════════════════════════════════════════════════════
   2. ██ DESKTOP  (min-width: 1024px)
════════════════════════════════════════════════════════════ */
@media (min-width: 1024px) {

  /* ── 구조 ── */
  .app-mobile, .app-tablet { display: none; }
  .app-desktop { display: flex; min-height: 100vh; }

  /* ── 사이드바 ── */
  .sidebar {
    width: 240px; flex-shrink: 0;
    background: var(--indigo-d);
    display: flex; flex-direction: column;
    padding: 0;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
  }
  .sb-logo {
    padding: 28px 24px 24px;
    border-bottom: 1px solid rgba(255,255,255,.08);
  }
  .sb-brand {
    font-size: 17px; font-weight: 800; color: #fff;
    display: flex; align-items: center; gap: 8px; letter-spacing: -.3px;
  }
  .sb-brand .pulse {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green); box-shadow: 0 0 8px var(--green);
    flex-shrink: 0;
  }
  .sb-sub { font-size: 11px; color: #818CF8; margin-top: 4px; }

  .sb-nav { padding: 16px 12px; flex: 1; display: flex; flex-direction: column; gap: 2px; }
  .sb-nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; border-radius: 10px;
    font-size: 13px; font-weight: 500; color: #A5B4FC;
    transition: all .15s; user-select: none;
  }
  .sb-nav-item:hover, .sb-nav-item.active {
    background: rgba(255,255,255,.1); color: #fff;
  }
  .sb-nav-item svg { width: 16px; height: 16px; flex-shrink: 0; }
  .sb-nav-sep { height: 1px; background: rgba(255,255,255,.07); margin: 8px 0; }

  .sb-footer {
    margin: 16px 12px; padding: 16px;
    background: rgba(255,255,255,.06); border-radius: 12px;
  }
  .sb-footer .sf-label { font-size: 10px; color: #818CF8; text-transform: uppercase;
    letter-spacing: .06em; margin-bottom: 8px; }
  .sf-strat { font-size: 13px; font-weight: 600; color: #fff; margin-bottom: 6px; }
  .mode-badge {
    display: inline-block; padding: 3px 10px; border-radius: 99px;
    font-size: 10px; font-weight: 600;
  }
  .mode-live  { background: rgba(16,185,129,.2); color: #34D399; }
  .mode-paper { background: rgba(249,115,22,.2);  color: #FB923C; }

  /* ── 메인 영역 ── */
  .dt-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }

  .dt-topbar {
    background: var(--card); border-bottom: 1px solid var(--border);
    padding: 18px 32px;
    display: flex; align-items: center; gap: 16px;
    position: sticky; top: 0; z-index: 10;
  }
  .dt-topbar-left { flex: 1; }
  .dt-topbar-left h2 { font-size: 22px; font-weight: 800; letter-spacing: -.3px; }
  .dt-topbar-left p  { font-size: 12px; color: var(--text-2); margin-top: 3px; }
  .dt-topbar-right   { display: flex; align-items: center; gap: 10px; }
  .time-pill {
    background: var(--card-alt); border: 1px solid var(--border);
    border-radius: var(--radius-sm); padding: 7px 14px;
    font-size: 12px; font-weight: 500; color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
  .btn-refresh {
    background: var(--indigo); color: #fff; border-radius: var(--radius-sm);
    padding: 8px 20px; font-size: 12px; font-weight: 600;
    transition: opacity .15s;
  }
  .btn-refresh:hover { opacity: .85; }

  .dt-content { flex: 1; padding: 28px 32px; overflow-y: auto; }

  /* KPI 카드 */
  .dt-kpi-grid {
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 18px; margin-bottom: 24px;
  }
  .dt-kpi {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow); padding: 22px; position: relative; overflow: hidden;
  }
  .dt-kpi.accent {
    background: linear-gradient(135deg, var(--indigo-d), var(--indigo));
    color: #fff;
  }
  .kpi-ico {
    position: absolute; right: 18px; top: 18px;
    width: 38px; height: 38px; border-radius: 10px;
    background: rgba(0,0,0,.07);
    display: flex; align-items: center; justify-content: center; font-size: 18px;
  }
  .dt-kpi.accent .kpi-ico { background: rgba(255,255,255,.15); }
  .kpi-lbl { font-size: 10px; font-weight: 600; color: var(--text-2);
    text-transform: uppercase; letter-spacing: .07em; margin-bottom: 8px; }
  .dt-kpi.accent .kpi-lbl { color: #A5B4FC; }
  .kpi-val { font-size: 24px; font-weight: 800; letter-spacing: -.5px; }
  .kpi-note { font-size: 12px; color: var(--text-2); margin-top: 4px; }
  .dt-kpi.accent .kpi-note { color: #C7D2FE; }

  /* 2열 / 3열 패널 */
  .dt-row { display: grid; gap: 20px; margin-bottom: 20px; }
  .dt-row.col-3-1 { grid-template-columns: 3fr 1.4fr; }
  .dt-row.col-2   { grid-template-columns: 1fr 1fr; }
  .dt-row.col-3   { grid-template-columns: 1fr 1fr 1fr; }

  .dt-panel {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow); overflow: hidden; display: flex; flex-direction: column;
  }
  .dt-ph {
    padding: 18px 22px 14px;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid var(--border);
  }
  .dt-pb { padding: 20px 22px; flex: 1; }

  /* 테이블 */
  .dt-tbl { width: 100%; border-collapse: collapse; }
  .dt-tbl th {
    text-align: left; padding: 10px 18px;
    font-size: 10px; font-weight: 600; color: var(--text-3);
    text-transform: uppercase; letter-spacing: .06em;
    background: var(--card-alt);
  }
  .dt-tbl td { padding: 13px 18px; border-top: 1px solid var(--border); font-size: 13px; }
  .dt-tbl tr:hover td { background: var(--card-alt); }
  .t-name  { font-weight: 600; }
  .t-code  { font-size: 10px; color: var(--text-3); margin-top: 2px; }

  /* 리스크 미터 */
  .risk-meter { display: flex; flex-direction: column; gap: 14px; }
  .rm-item    { display: flex; flex-direction: column; gap: 5px; }
  .rm-row     { display: flex; justify-content: space-between; align-items: center; }
  .rm-label   { font-size: 12px; color: var(--text-2); font-weight: 500; }
  .rm-value   { font-size: 12px; font-weight: 700; }
  .rm-track   { height: 6px; background: var(--border); border-radius: 99px; overflow: hidden; }
  .rm-fill    { height: 6px; border-radius: 99px; transition: width .5s ease; }
  .rm-ok   .rm-fill { background: var(--green); }
  .rm-warn .rm-fill { background: var(--amber); }
  .rm-bad  .rm-fill { background: var(--red); }
}

/* ════════════════════════════════════════════════════════════
   3. ██ TABLET  (640px ~ 1023px)
════════════════════════════════════════════════════════════ */
@media (min-width: 640px) and (max-width: 1023px) {

  .app-mobile, .app-desktop { display: none; }
  .app-tablet { display: flex; flex-direction: column; min-height: 100vh; }

  /* 상단 헤더 */
  .tb-header {
    background: var(--indigo-d);
    padding: 20px 24px 0;
    display: flex; flex-direction: column; gap: 16px;
  }
  .tb-top-row {
    display: flex; align-items: center; justify-content: space-between;
  }
  .tb-brand { font-size: 16px; font-weight: 800; color: #fff; display: flex; align-items: center; gap: 8px; }
  .tb-pulse { width: 7px; height: 7px; border-radius: 50%;
    background: var(--green); box-shadow: 0 0 6px var(--green); }
  .tb-badge-row { display: flex; align-items: center; gap: 10px; }

  /* 상단 탭 */
  .tb-tabs {
    display: flex; gap: 0;
  }
  .tb-tab {
    flex: 1; padding: 12px 8px;
    text-align: center; font-size: 12px; font-weight: 600;
    color: rgba(255,255,255,.5); border-bottom: 2px solid transparent;
    cursor: pointer; transition: all .15s; user-select: none;
  }
  .tb-tab.active { color: #fff; border-bottom-color: #fff; }

  /* 콘텐츠 */
  .tb-content { flex: 1; padding: 20px 24px; }
  .tb-section { display: none; }
  .tb-section.active { display: block; }

  /* KPI 2×2 */
  .tb-kpi-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 20px;
  }
  .tb-kpi {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow); padding: 18px; position: relative; overflow: hidden;
  }
  .tb-kpi.accent {
    background: linear-gradient(135deg, var(--indigo-d), var(--indigo)); color: #fff;
  }
  .tb-kpi .kpi-lbl { font-size: 10px; font-weight: 600; color: var(--text-2);
    text-transform: uppercase; letter-spacing: .07em; margin-bottom: 6px; }
  .tb-kpi.accent .kpi-lbl { color: #A5B4FC; }
  .tb-kpi .kpi-val { font-size: 20px; font-weight: 800; letter-spacing: -.4px; }
  .tb-kpi .kpi-note { font-size: 11px; color: var(--text-2); margin-top: 3px; }
  .tb-kpi.accent .kpi-note { color: #C7D2FE; }

  /* 패널 */
  .tb-panel {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow); overflow: hidden; margin-bottom: 18px;
  }
  .tb-ph { padding: 16px 20px 12px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between; }
  .tb-pb { padding: 18px 20px; }

  /* 2열 그리드 */
  .tb-row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 18px; }

  /* 테이블 */
  .tb-tbl { width: 100%; border-collapse: collapse; }
  .tb-tbl th { text-align: left; padding: 9px 16px; font-size: 10px; font-weight: 600;
    color: var(--text-3); text-transform: uppercase; background: var(--card-alt); }
  .tb-tbl td { padding: 12px 16px; border-top: 1px solid var(--border); font-size: 13px; }
  .tb-tbl tr:hover td { background: var(--card-alt); }
}

/* ════════════════════════════════════════════════════════════
   4. ██ MOBILE  (max-width: 639px)
════════════════════════════════════════════════════════════ */
@media (max-width: 639px) {

  .app-desktop, .app-tablet { display: none; }
  .app-mobile {
    display: flex; flex-direction: column;
    min-height: 100vh; background: var(--bg);
    padding-bottom: var(--tab-h);
  }

  /* ── 모바일 히어로 헤더 ── */
  .mb-hero {
    background: linear-gradient(160deg, var(--indigo-d) 0%, var(--indigo) 100%);
    padding: 24px 20px 28px;
    color: #fff;
  }
  .mb-hero-top {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 18px;
  }
  .mb-brand { font-size: 14px; font-weight: 700; color: rgba(255,255,255,.7); }
  .mb-time  { font-size: 12px; color: rgba(255,255,255,.5); font-variant-numeric: tabular-nums; }
  .mb-greeting { font-size: 22px; font-weight: 800; letter-spacing: -.4px; margin-bottom: 4px; }
  .mb-sub  { font-size: 12px; color: rgba(255,255,255,.6); }

  /* 총자산 큰 숫자 */
  .mb-asset-card {
    background: rgba(255,255,255,.12); border-radius: var(--radius);
    padding: 18px; margin-top: 20px;
    backdrop-filter: blur(8px);
  }
  .mb-asset-lbl  { font-size: 11px; color: rgba(255,255,255,.6); margin-bottom: 6px;
    text-transform: uppercase; letter-spacing: .07em; }
  .mb-asset-val  { font-size: 30px; font-weight: 800; letter-spacing: -.6px; }
  .mb-asset-sub  { font-size: 13px; color: rgba(255,255,255,.7); margin-top: 4px;
    display: flex; align-items: center; gap: 8px; }
  .mb-asset-sub .sep { width: 1px; height: 12px; background: rgba(255,255,255,.3); }

  /* ── 빠른 지표 가로 스크롤 ── */
  .mb-metrics-scroll {
    display: flex; gap: 12px; padding: 16px 20px;
    overflow-x: auto; -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .mb-metrics-scroll::-webkit-scrollbar { display: none; }
  .mb-metric {
    flex-shrink: 0; background: var(--card); border-radius: var(--radius);
    padding: 14px 18px; min-width: 130px; box-shadow: var(--shadow);
  }
  .mb-metric .kpi-lbl  { font-size: 10px; font-weight: 600; color: var(--text-2);
    text-transform: uppercase; letter-spacing: .06em; margin-bottom: 5px; }
  .mb-metric .kpi-val  { font-size: 18px; font-weight: 700; }
  .mb-metric .kpi-note { font-size: 11px; color: var(--text-2); margin-top: 2px; }

  /* ── 섹션 ── */
  .mb-section { display: none; padding: 0 16px 16px; }
  .mb-section.active { display: block; }

  .mb-section-title {
    font-size: 16px; font-weight: 700; padding: 20px 16px 12px;
    position: sticky; top: 0; background: var(--bg); z-index: 5;
  }

  /* ── 모바일 카드 ── */
  .mb-card {
    background: var(--card); border-radius: var(--radius);
    box-shadow: var(--shadow); overflow: hidden; margin-bottom: 14px;
  }
  .mb-card-hdr {
    padding: 14px 16px 10px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
  }
  .mb-card-body { padding: 16px; }

  /* ── 종목 리스트 ── */
  .mb-holding {
    display: flex; align-items: center; gap: 12px;
    padding: 13px 0; border-bottom: 1px solid var(--border);
  }
  .mb-holding:last-child { border-bottom: none; }
  .mb-h-icon {
    width: 38px; height: 38px; border-radius: 10px;
    background: var(--indigo-xl); display: flex; align-items: center; justify-content: center;
    font-size: 15px; flex-shrink: 0; font-weight: 700; color: var(--indigo);
  }
  .mb-h-info { flex: 1; min-width: 0; }
  .mb-h-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .mb-h-sub  { font-size: 11px; color: var(--text-2); margin-top: 1px; }
  .mb-h-prog { margin-top: 5px; }
  .mb-h-right { text-align: right; flex-shrink: 0; }
  .mb-h-pct   { font-size: 14px; font-weight: 700; }
  .mb-h-amount { font-size: 11px; color: var(--text-2); margin-top: 2px; }

  /* ── 리스크 미터 ── */
  .mb-risk-row { padding: 12px 0; border-bottom: 1px solid var(--border); }
  .mb-risk-row:last-child { border-bottom: none; }
  .mb-risk-top { display: flex; justify-content: space-between; margin-bottom: 6px; }
  .mb-risk-label { font-size: 13px; font-weight: 500; color: var(--text-1); }
  .mb-risk-value { font-size: 13px; font-weight: 700; }

  /* ── 하단 탭바 ── */
  .mb-tabbar {
    position: fixed; bottom: 0; left: 0; right: 0;
    height: var(--tab-h);
    background: var(--card); border-top: 1px solid var(--border);
    display: flex; align-items: center;
    z-index: 100;
    padding-bottom: env(safe-area-inset-bottom, 0);
  }
  .mb-tab {
    flex: 1; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 4px; padding: 8px 0;
    color: var(--text-3); cursor: pointer; transition: color .15s; user-select: none;
    -webkit-tap-highlight-color: transparent;
  }
  .mb-tab svg { width: 22px; height: 22px; }
  .mb-tab span { font-size: 10px; font-weight: 600; }
  .mb-tab.active { color: var(--indigo); }
  .mb-tab.active svg { stroke: var(--indigo); }
}
</style>
</head>
<body>

<!-- ════════════════════════════════════════════════════════
     DESKTOP  (≥ 1024px)
════════════════════════════════════════════════════════ -->
<div class="app-desktop">

  <!-- 사이드바 -->
  <aside class="sidebar">
    <div class="sb-logo">
      <div class="sb-brand"><span class="pulse"></span>ETF 퀀트봇</div>
      <div class="sb-sub">Automated Portfolio System</div>
    </div>
    <nav class="sb-nav">
      <div class="sb-nav-item active">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
        대시보드
      </div>
      <div class="sb-nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        NAV 추이
      </div>
      <div class="sb-nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        전략 관리
      </div>
      <div class="sb-nav-sep"></div>
      <div class="sb-nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>
        백테스트
      </div>
      <div class="sb-nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4"/></svg>
        리스크 설정
      </div>
    </nav>
    <div class="sb-footer">
      <div class="sf-label">현재 전략</div>
      <div class="sf-strat">%%STRATEGY%%</div>
      <span class="mode-badge %%MODE_CLASS%%">%%MODE_LABEL%%</span>
    </div>
  </aside>

  <!-- 메인 -->
  <div class="dt-main">
    <div class="dt-topbar">
      <div class="dt-topbar-left">
        <h2>%%GREETING%%</h2>
        <p>%%UPDATED%%</p>
      </div>
      <div class="dt-topbar-right">
        <div class="time-pill" id="dt-clock">--:--:--</div>
        <button class="btn-refresh" onclick="location.reload()">↻ 새로고침</button>
      </div>
    </div>

    <div class="dt-content">
      <!-- KPI -->
      <div class="dt-kpi-grid">%%DT_KPIS%%</div>

      <!-- NAV + 리밸런싱 로그 -->
      <div class="dt-row col-3-1">
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

      <!-- 보유종목 + 비중 -->
      <div class="dt-row col-2">
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

      <!-- 리스크 미터 + MDD 진행 -->
      <div class="dt-row col-3">
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
      <div class="tb-brand"><span class="tb-pulse"></span>ETF 퀀트봇</div>
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
    <!-- 개요 탭 -->
    <div class="tb-section active" id="tb-overview">
      <div class="tb-kpi-grid">%%TB_KPIS%%</div>
      <div class="tb-row-2">
        <div class="tb-panel">
          <div class="tb-ph"><div><div class="panel-title">NAV 추이</div></div><span id="tb-nav-badge" style="font-size:12px;font-weight:700"></span></div>
          <div class="tb-pb"><canvas id="tbNavChart" height="120"></canvas></div>
        </div>
        <div class="tb-panel">
          <div class="tb-ph"><div><div class="panel-title">비중 배분</div></div></div>
          <div class="tb-pb"><canvas id="tbWeightChart" height="120"></canvas></div>
        </div>
      </div>
    </div>

    <!-- 보유종목 탭 -->
    <div class="tb-section" id="tb-holdings">
      <div class="tb-panel">
        <table class="tb-tbl"><thead><tr>
          <th>종목</th><th>평가금액</th><th>비중</th><th>수익률</th>
        </tr></thead><tbody>%%TB_ROWS%%</tbody></table>
      </div>
    </div>

    <!-- NAV 탭 -->
    <div class="tb-section" id="tb-nav">
      <div class="tb-panel">
        <div class="tb-ph"><div><div class="panel-title">NAV 추이</div><div class="panel-sub">일별 포트폴리오 순자산가치</div></div></div>
        <div class="tb-pb"><canvas id="tbNavChart2" height="200"></canvas></div>
      </div>
    </div>

    <!-- 리스크 탭 -->
    <div class="tb-section" id="tb-risk">
      <div class="tb-panel">
        <div class="tb-ph"><div><div class="panel-title">리스크 현황</div></div></div>
        <div class="tb-pb risk-meter">%%TB_RISK_METERS%%</div>
      </div>
    </div>
  </div>
</div>

<!-- ════════════════════════════════════════════════════════
     MOBILE  (≤ 639px)
════════════════════════════════════════════════════════ -->
<div class="app-mobile">

  <!-- 히어로 -->
  <div class="mb-hero">
    <div class="mb-hero-top">
      <div class="mb-brand">ETF 퀀트봇</div>
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

  <!-- 가로 스크롤 지표 -->
  <div class="mb-metrics-scroll">%%MB_METRICS%%</div>

  <!-- 섹션: 홈 -->
  <div class="mb-section active" id="mb-home">
    <div class="mb-section-title">포트폴리오 현황</div>
    <div class="mb-card">
      <div class="mb-card-hdr">
        <div class="panel-title">보유 종목</div>
        <span style="font-size:11px;color:var(--text-2)">%%MB_HOLD_COUNT%%</span>
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

  <!-- 섹션: 비중 -->
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

  <!-- 섹션: 리스크 -->
  <div class="mb-section" id="mb-risk">
    <div class="mb-section-title">리스크 현황</div>
    <div class="mb-card">
      <div class="mb-card-body">%%MB_RISK%%</div>
    </div>
    <div class="mb-card">
      <div class="mb-card-hdr"><div class="panel-title">전략</div></div>
      <div class="mb-card-body" style="font-size:13px;color:var(--text-2)">%%MB_STRAT_INFO%%</div>
    </div>
  </div>

  <!-- 섹션: 활동 -->
  <div class="mb-section" id="mb-activity">
    <div class="mb-section-title">최근 활동</div>
    <div class="mb-card">
      <div class="mb-card-body log-list" id="mb-log">
        <div class="log-item"><div class="log-dot ld-info"></div><div><div class="log-text">대기 중</div><div class="log-meta">매월 첫 영업일 15:15 리밸런싱</div></div></div>
      </div>
    </div>
  </div>

  <!-- 하단 탭바 -->
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
/* ── 공통 유틸 ─────────────────────────────────── */
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.color = '#94A3B8';
Chart.defaults.borderColor = 'rgba(226,232,240,.6)';

function fmtWon(v) {
  if (Math.abs(v) >= 100000000) return (v / 100000000).toFixed(2) + '억원';
  if (Math.abs(v) >= 10000)     return (v / 10000).toFixed(0) + '만원';
  return v.toLocaleString('ko-KR') + '원';
}

const NAV_DS = {
  borderColor: '#4338CA', backgroundColor: 'rgba(99,102,241,.08)',
  fill: true, tension: 0.4, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2.5,
};
const NAV_OPTS = (tickCb) => ({
  responsive: true,
  interaction: { intersect: false, mode: 'index' },
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: '#1E293B', titleColor: '#94A3B8', bodyColor: '#F1F5F9', padding: 10,
      callbacks: { label: ctx => ' ' + ctx.parsed.y.toLocaleString('ko-KR') + '원' }
    }
  },
  scales: {
    x: { grid: { display: false }, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
    y: { grid: { color: 'rgba(226,232,240,.5)' }, ticks: { callback: tickCb } }
  }
});
const W_DS = (color, label) => ({
  label, backgroundColor: color, borderRadius: 4, borderSkipped: false
});
const W_OPTS = {
  indexAxis: 'y', responsive: true,
  plugins: { legend: { position: 'top', labels: { color: '#64748B', boxWidth: 10, font: { size: 11 } } },
    tooltip: { backgroundColor: '#1E293B', callbacks: { label: c => ' ' + c.parsed.x + '%' } } },
  scales: {
    x: { grid: { color: 'rgba(226,232,240,.5)' }, ticks: { callback: v => v + '%' } },
    y: { grid: { display: false }, ticks: { font: { size: 11 } } }
  }
};

/* NAV 뱃지 */
function navBadge(values, elId) {
  if (!values || values.length < 2) return;
  const ret = (values[values.length-1] / values[0] - 1) * 100;
  const el = document.getElementById(elId);
  if (!el) return;
  el.textContent = (ret >= 0 ? '+' : '') + ret.toFixed(2) + '%';
  el.style.color = ret >= 0 ? 'var(--green)' : 'var(--red)';
}

/* ── 실시간 시계 ─────────────────────────────── */
function tick() {
  const t = new Date().toLocaleTimeString('ko-KR', { hour12: false });
  ['dt-clock','mb-clock'].forEach(id => { const el=document.getElementById(id); if(el) el.textContent=t; });
  setTimeout(tick, 1000);
}
tick();

/* ── API 로드 ────────────────────────────────── */
async function loadNav() {
  try {
    const d = await fetch('/api/performance').then(r => r.json());
    if (!d.dates || d.dates.length < 2) {
      ['dtNavEmpty','mbNavEmpty'].forEach(id => {
        const el=document.getElementById(id); if(el) el.style.display='flex';
      });
      return null;
    }
    return d;
  } catch { return null; }
}

async function loadWeights() {
  try {
    const d = await fetch('/api/target-weights').then(r => r.json());
    if (!d.labels || d.labels.length === 0) {
      ['dtWeightEmpty','mbWeightEmpty'].forEach(id => {
        const el=document.getElementById(id); if(el) el.style.display='flex';
      });
      return null;
    }
    return d;
  } catch { return null; }
}

/* ── Desktop 차트 ───────────────────────────── */
(async function() {
  const tickFn = v => { if(Math.abs(v)>=100000000) return (v/100000000).toFixed(1)+'억'; return (v/10000).toFixed(0)+'만'; };
  const nav = await loadNav();
  if (nav) {
    navBadge(nav.values, 'dt-nav-badge');
    navBadge(nav.values, 'tb-nav-badge');
    new Chart(document.getElementById('dtNavChart'), {
      type:'line', data:{labels:nav.dates,datasets:[{...NAV_DS,label:'NAV',data:nav.values}]},
      options: NAV_OPTS(tickFn)
    });
    new Chart(document.getElementById('tbNavChart'), {
      type:'line', data:{labels:nav.dates,datasets:[{...NAV_DS,label:'NAV',data:nav.values}]},
      options: NAV_OPTS(tickFn)
    });
    new Chart(document.getElementById('tbNavChart2'), {
      type:'line', data:{labels:nav.dates,datasets:[{...NAV_DS,label:'NAV',data:nav.values}]},
      options: NAV_OPTS(tickFn)
    });
    navBadge(nav.values, 'mb-nav-badge');
    new Chart(document.getElementById('mbNavChart'), {
      type:'line', data:{labels:nav.dates,datasets:[{...NAV_DS,label:'NAV',data:nav.values}]},
      options: NAV_OPTS(v => (v/10000).toFixed(0)+'만')
    });
  }

  const w = await loadWeights();
  if (w) {
    [
      ['dtWeightChart', 200],
      ['tbWeightChart', 120],
      ['mbWeightChart', 220],
    ].forEach(([id, h]) => {
      const el = document.getElementById(id);
      if (!el) return;
      new Chart(el, {
        type:'bar',
        data:{labels:w.labels, datasets:[
          {...W_DS('rgba(67,56,202,.8)', '목표'), data: w.target},
          {...W_DS('rgba(16,185,129,.7)', '현재'), data: w.current},
        ]},
        options: W_OPTS
      });
    });
  }
})();

/* ── Tablet 탭 전환 ─────────────────────────── */
document.querySelectorAll('.tb-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tb-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tb-section').forEach(s => s.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.add('active');
  });
});

/* ── Mobile 탭 전환 ─────────────────────────── */
document.querySelectorAll('.mb-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.mb-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.mb-section').forEach(s => s.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.sec).classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
});
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
    """(badge_html, badge_class) 반환"""
    if is_halted:
        return ("<span class='badge b-halt'><span class='badge-dot'></span>거래 중단</span>", "b-halt")
    if mdd <= -0.08:
        return ("<span class='badge b-warn'><span class='badge-dot'></span>경고</span>", "b-warn")
    return ("<span class='badge b-ok'><span class='badge-dot'></span>정상 운용</span>", "b-ok")


def _risk_meter(label: str, value_pct: float, limit_pct: float, unit: str = "%") -> str:
    """리스크 미터 한 행 생성 (value/limit 모두 양수로 전달)"""
    ratio = min(abs(value_pct / limit_pct) if limit_pct else 0, 1.0) * 100
    cls   = "rm-bad" if ratio >= 80 else ("rm-warn" if ratio >= 50 else "rm-ok")
    return (
        f"<div class='rm-item {cls}'>"
        f"<div class='rm-row'><span class='rm-label'>{label}</span>"
        f"<span class='rm-value {(_pcc(-value_pct) if value_pct > 0 else 'neu')}'>"
        f"{value_pct:+.2f}{unit} / {limit_pct:.0f}{unit}</span></div>"
        f"<div class='rm-track'><div class='rm-fill' style='width:{ratio:.1f}%'></div></div>"
        f"</div>"
    )


def _mb_risk_row(label: str, value_str: str, ratio: float, cls: str) -> str:
    bar_cls = "rm-ok" if ratio < 50 else ("rm-warn" if ratio < 80 else "rm-bad")
    return (
        f"<div class='mb-risk-row'>"
        f"<div class='mb-risk-top'><span class='mb-risk-label'>{label}</span>"
        f"<span class='mb-risk-value {cls}'>{value_str}</span></div>"
        f"<div class='prog-wrap {bar_cls}'>"
        f"<div class='prog-bar' style='width:{min(ratio,100):.1f}%;background:inherit'></div>"
        f"</div></div>"
    )


def _strat_info_html(strategy_name: str, mode: str) -> str:
    mode_map = {"kis_real": "실전 매매", "kis_paper": "KIS 모의", "paper": "페이퍼"}
    schedule = "매월 첫 영업일 15:15"
    return (
        f"<div style='display:flex;flex-direction:column;gap:10px;font-size:13px'>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:var(--text-2)'>전략</span><span style='font-weight:600'>{strategy_name}</span></div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:var(--text-2)'>모드</span><span style='font-weight:600'>{mode_map.get(mode, mode)}</span></div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:var(--text-2)'>리밸런싱</span><span style='font-weight:600'>{schedule}</span></div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:var(--text-2)'>임계값</span><span style='font-weight:600'>±3%</span></div>"
        f"</div>"
    )


def _sys_info_html(mdd: float) -> str:
    now = datetime.now()
    market_open = 9 <= now.hour < 15 or (now.hour == 15 and now.minute < 30)
    market_str  = "장중 ●" if market_open else "장외 ○"
    mdd_cap     = f"{mdd * 100:+.2f}%"
    return (
        f"<div style='display:flex;flex-direction:column;gap:10px;font-size:13px'>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:var(--text-2)'>시장 상태</span><span style='font-weight:600'>{market_str}</span></div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:var(--text-2)'>현재 MDD</span><span style='font-weight:600;color:{'var(--red)' if mdd<=-0.08 else 'var(--text-1)'}'>{mdd_cap}</span></div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:var(--text-2)'>하드스탑</span><span style='font-weight:600'>-18%</span></div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:var(--text-2)'>업데이트</span><span style='font-weight:600'>{now.strftime('%H:%M')}</span></div>"
        f"</div>"
    )


def _build_html(bot: "ETFQuantBot") -> str:
    try:
        balance = bot.broker.get_balance()
        risk_st = bot.guard.get_status()
    except Exception as e:
        return (
            "<div style='font-family:Inter,sans-serif;background:#EEF2F7;min-height:100vh;"
            "display:flex;align-items:center;justify-content:center'>"
            f"<div style='background:#fff;border-radius:14px;padding:32px 40px;box-shadow:0 2px 12px rgba(0,0,0,.08)'>"
            f"<h2 style='color:#EF4444;margin-bottom:8px'>연결 오류</h2>"
            f"<p style='color:#64748B;font-size:13px'>{e}</p></div></div>"
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

    # ── 공통 상태값 ──────────────────────────────────────────
    now_str      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    greeting_str = _greeting()

    # ── Desktop KPI ──────────────────────────────────────────
    dt_kpis = (
        f"<div class='dt-kpi accent'><div class='kpi-ico'>💰</div>"
        f"<div class='kpi-lbl'>총 자산</div>"
        f"<div class='kpi-val'>{total/10000:.0f}만원</div>"
        f"<div class='kpi-note'>예수금 {balance.cash/10000:.0f}만원</div></div>"

        f"<div class='dt-kpi'><div class='kpi-ico'>📊</div>"
        f"<div class='kpi-lbl'>평가 손익</div>"
        f"<div class='kpi-val {_pcc(pnl)}'>{pnl:+,.0f}원</div>"
        f"<div class='kpi-note {_pcc(pnl_rate)}'>{pnl_rate:+.2f}%</div></div>"

        f"<div class='dt-kpi'><div class='kpi-ico'>🛡️</div>"
        f"<div class='kpi-lbl'>현재 MDD</div>"
        f"<div class='kpi-val {'neg' if mdd<=-0.08 else 'neu'}'>{mdd*100:+.2f}%</div>"
        f"<div class='kpi-note' style='color:var(--text-3)'>한도 -18%</div></div>"

        f"<div class='dt-kpi'><div class='kpi-ico'>🤖</div>"
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
            f"<div class='prog-wrap'><div class='prog-bar' style='width:{min(w,100):.1f}%'></div></div></td>"
            f"<td class='{_pcc(h.profit_rate)}' style='font-weight:600'>{h.profit_rate:+.1f}%</td>"
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
            f"<td><div style='font-weight:600'>{h.name}</div><div style='font-size:10px;color:var(--text-3)'>{h.ticker}</div></td>"
            f"<td>{h.eval_amount/10000:.0f}만원</td>"
            f"<td>{w:.1f}%<div class='prog-wrap' style='margin-top:4px'><div class='prog-bar' style='width:{min(w,100):.1f}%'></div></div></td>"
            f"<td class='{_pcc(h.profit_rate)}' style='font-weight:600'>{h.profit_rate:+.1f}%</td>"
            f"</tr>"
        )
    if not tb_rows:
        tb_rows = ["<tr><td colspan='4' style='text-align:center;padding:32px;color:var(--text-3)'>보유 종목 없음</td></tr>"]

    # ── Mobile 보유종목 ────────────────────────────────────────
    mb_holdings = []
    for h in holdings_sorted[:8]:  # 모바일은 상위 8개
        w = h.eval_amount / total * 100 if total > 0 else 0
        initial = h.name[0] if h.name else "?"
        mb_holdings.append(
            f"<div class='mb-holding'>"
            f"<div class='mb-h-icon'>{initial}</div>"
            f"<div class='mb-h-info'>"
            f"<div class='mb-h-name'>{h.name}</div>"
            f"<div class='mb-h-sub'>{h.ticker} · {w:.1f}%</div>"
            f"<div class='mb-h-prog'><div class='prog-wrap'><div class='prog-bar' style='width:{min(w,100):.1f}%'></div></div></div>"
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

    # ── 리스크 미터 (공통) ────────────────────────────────────
    mdd_ratio   = min(abs(mdd) / 0.18, 1.0) * 100
    daily_ratio = min(abs(daily_loss) / 0.03, 1.0) * 100

    risk_meters_html = (
        _risk_meter("MDD",      abs(mdd) * 100,     18.0)
        + _risk_meter("일간 손실", abs(daily_loss) * 100, 3.0)
        + _risk_meter("연속 손실일", risk_st.get("consecutive_loss_days", 0), 5.0, "일")
    )

    # Mobile 리스크
    mb_risk_html = (
        _mb_risk_row("MDD",       f"{mdd*100:+.2f}%",   mdd_ratio,
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
        "%%GREETING%%":          greeting_str,
        "%%UPDATED%%":           f"마지막 업데이트: {now_str}",
        "%%STRATEGY%%":          strategy_name,
        "%%MODE_CLASS%%":        mode_cls,
        "%%MODE_LABEL%%":        mode_label,
        # Desktop
        "%%DT_KPIS%%":           dt_kpis,
        "%%DT_STATUS_BADGE%%":   status_badge,
        "%%DT_ROWS%%":           "".join(dt_rows),
        "%%DT_RISK_METERS%%":    risk_meters_html,
        "%%DT_STRAT_INFO%%":     _strat_info_html(strategy_name, mode),
        "%%DT_SYS_INFO%%":       _sys_info_html(mdd),
        # Tablet
        "%%TB_STATUS_BADGE%%":   status_badge,
        "%%TB_KPIS%%":           tb_kpis,
        "%%TB_ROWS%%":           "".join(tb_rows),
        "%%TB_RISK_METERS%%":    risk_meters_html,
        # Mobile
        "%%MB_TOTAL%%":          f"{total/10000:.0f}만원",
        "%%MB_PNL%%":            f"{pnl_rate:+.2f}%",
        "%%MB_PNL_CLS%%":        _pcc(pnl_rate),
        "%%MB_STATUS_BADGE%%":   status_badge,
        "%%MB_METRICS%%":        mb_metrics,
        "%%MB_HOLDINGS%%":       "".join(mb_holdings),
        "%%MB_HOLD_COUNT%%":     f"{hold_count}개",
        "%%MB_RISK%%":           mb_risk_html,
        "%%MB_STRAT_INFO%%":     _strat_info_html(strategy_name, mode),
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
                    {"ticker": h.ticker, "name": h.name, "qty": h.qty,
                     "eval_amount": h.eval_amount, "profit_rate": h.profit_rate}
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
    logger.info(f"[Dashboard] 반응형 대시보드 시작 → http://0.0.0.0:{port}")
