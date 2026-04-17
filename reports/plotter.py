"""
백테스트 결과 시각화
- 포트폴리오 가치 곡선
- 드로다운 차트
- 자산 배분 히스토리
- 전략 비교 차트
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")   # 헤드리스 환경 지원
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import REPORT_DIR


STYLE_COLORS = [
    "#2E86AB", "#A23B72", "#F18F01", "#C73E1D",
    "#3B1F2B", "#44BBA4", "#E94F37", "#393E41",
]


def plot_backtest_result(
    portfolio_values: pd.Series,
    strategy_name: str = "Strategy",
    benchmark: pd.Series | None = None,
    weights_history: pd.DataFrame | None = None,
    save_path: Path | None = None,
) -> Path:
    """
    백테스트 결과 4-패널 차트

    Returns: 저장된 파일 경로
    """
    fig = plt.figure(figsize=(16, 12))
    fig.suptitle(
        f"[{strategy_name}] 백테스트 결과\n"
        f"{str(portfolio_values.index[0].date())} ~ "
        f"{str(portfolio_values.index[-1].date())}",
        fontsize=14, fontweight="bold", y=0.98
    )
    gs = GridSpec(3, 2, figure=fig, hspace=0.4, wspace=0.3)

    # ── 1. 포트폴리오 가치 ──────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    pv_norm = portfolio_values / portfolio_values.iloc[0] * 100
    ax1.plot(pv_norm.index, pv_norm.values, color=STYLE_COLORS[0],
             linewidth=2, label=strategy_name)
    if benchmark is not None:
        bm_norm = benchmark.reindex(portfolio_values.index).ffill()
        bm_norm = bm_norm / bm_norm.iloc[0] * 100
        ax1.plot(bm_norm.index, bm_norm.values, color=STYLE_COLORS[3],
                 linewidth=1.5, linestyle="--", alpha=0.8, label="Benchmark")
    ax1.axhline(100, color="gray", linewidth=0.8, linestyle=":")
    ax1.set_ylabel("포트폴리오 가치 (시작=100)")
    ax1.set_title("누적 수익률")
    ax1.legend()
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.grid(alpha=0.3)

    # ── 2. 드로다운 ─────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, :])
    cummax   = portfolio_values.cummax()
    drawdown = (portfolio_values - cummax) / cummax * 100
    ax2.fill_between(drawdown.index, drawdown.values, 0,
                     color=STYLE_COLORS[3], alpha=0.5, label="Drawdown")
    ax2.axhline(-10, color="orange", linewidth=1, linestyle="--", alpha=0.7, label="-10%")
    ax2.axhline(-15, color="red",    linewidth=1, linestyle="--", alpha=0.7, label="-15%")
    ax2.set_ylabel("드로다운 (%)")
    ax2.set_title("Drawdown")
    ax2.legend(loc="lower left", fontsize=9)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.grid(alpha=0.3)

    # ── 3. 월별 수익률 히트맵 ────────────────────────────
    ax3 = fig.add_subplot(gs[2, 0])
    _plot_monthly_returns(ax3, portfolio_values)

    # ── 4. 자산 배분 히스토리 ────────────────────────────
    ax4 = fig.add_subplot(gs[2, 1])
    if weights_history is not None and not weights_history.empty:
        _plot_weights_history(ax4, weights_history)
    else:
        ax4.text(0.5, 0.5, "비중 데이터 없음",
                 ha="center", va="center", transform=ax4.transAxes)

    if save_path is None:
        save_path = REPORT_DIR / f"{strategy_name.replace(' ', '_')}_backtest.png"

    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


def plot_strategy_comparison(
    results: dict[str, pd.Series],
    save_path: Path | None = None,
) -> Path:
    """여러 전략 수익률 비교 차트"""
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle("전략 비교", fontsize=14, fontweight="bold")

    ax1, ax2 = axes

    for i, (name, pv) in enumerate(results.items()):
        color  = STYLE_COLORS[i % len(STYLE_COLORS)]
        norm   = pv / pv.iloc[0] * 100
        ax1.plot(norm.index, norm.values, color=color, linewidth=1.8, label=name)

        cummax   = pv.cummax()
        drawdown = (pv - cummax) / cummax * 100
        ax2.plot(drawdown.index, drawdown.values, color=color,
                 linewidth=1.5, alpha=0.8, label=name)

    ax1.set_title("누적 수익률 비교")
    ax1.set_ylabel("가치 (시작=100)")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2.set_title("드로다운 비교")
    ax2.set_ylabel("드로다운 (%)")
    ax2.axhline(-10, color="gray", linestyle="--", alpha=0.5)
    ax2.axhline(-15, color="red",  linestyle="--", alpha=0.5)
    ax2.legend()
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()

    if save_path is None:
        save_path = REPORT_DIR / "strategy_comparison.png"
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return save_path


def _plot_monthly_returns(ax: plt.Axes, portfolio_values: pd.Series) -> None:
    """월별 수익률 히트맵"""
    monthly = portfolio_values.resample("ME").last().pct_change().dropna() * 100
    if monthly.empty:
        return

    pivot = monthly.copy()
    pivot.index = pd.MultiIndex.from_arrays(
        [pivot.index.year, pivot.index.month]
    )
    try:
        table = pivot.unstack(level=1)
    except Exception:
        return

    table.columns = ["Jan","Feb","Mar","Apr","May","Jun",
                     "Jul","Aug","Sep","Oct","Nov","Dec"]

    im = ax.imshow(table.values, cmap="RdYlGn", aspect="auto",
                   vmin=-8, vmax=8)
    ax.set_xticks(range(12))
    ax.set_xticklabels(table.columns, fontsize=8)
    ax.set_yticks(range(len(table)))
    ax.set_yticklabels(table.index, fontsize=8)
    ax.set_title("월별 수익률 (%)", fontsize=10)

    for i in range(table.shape[0]):
        for j in range(table.shape[1]):
            val = table.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{val:.1f}", ha="center", va="center",
                        fontsize=6, color="black")


def _plot_weights_history(ax: plt.Axes, weights: pd.DataFrame) -> None:
    """자산 배분 스택 영역 차트"""
    from config import ALL_ETFS
    # ticker → 이름 변환
    renamed = weights.rename(columns=ALL_ETFS)
    # 상위 8개만 표시
    mean_w  = renamed.mean().nlargest(8)
    top     = renamed[mean_w.index]

    ax.stackplot(
        top.index, top.T.values,
        labels=top.columns.tolist(),
        colors=STYLE_COLORS[:len(top.columns)],
        alpha=0.8,
    )
    ax.set_title("자산 배분 히스토리", fontsize=10)
    ax.set_ylabel("비중")
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left", fontsize=7, ncol=2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
