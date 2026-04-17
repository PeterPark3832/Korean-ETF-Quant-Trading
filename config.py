"""
전략 및 포트폴리오 전역 설정
"""
from pathlib import Path
from datetime import datetime

# ── 경로 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "cache"
REPORT_DIR = BASE_DIR / "reports"

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── ETF 유니버스 ───────────────────────────────────────
ETF_UNIVERSE = {
    # 한국주식
    "KR_EQUITY": {
        "069500": "KODEX 200",
        "102110": "TIGER 코스피",
        "278540": "KODEX 200TR",
    },
    # 해외주식
    "GLOBAL_EQUITY": {
        "360750": "TIGER 미국S&P500",
        "379800": "KODEX 미국나스닥100TR",
        "195970": "KODEX 유럽선진국MSCI",
        "192090": "TIGER 차이나CSI300",
        "381170": "TIGER 미국테크TOP10",
    },
    # 채권
    "BOND": {
        "114820": "KODEX 국고채3년",
        "148070": "TIGER 국고채10년",
        "308620": "KODEX 미국채10년선물",
        "136340": "KODEX 단기채권PLUS",
    },
    # 원자재
    "COMMODITY": {
        "132030": "KODEX 골드선물(H)",
        "261220": "TIGER 원유선물Enhanced(H)",
        "144600": "KODEX 은선물(H)",
    },
    # 현금성 (MMF 대용)
    "CASH": {
        "449170": "KODEX KOFR금리액티브(합성)",
        "157450": "TIGER 단기통안채",
    },
}

# 전 종목 flat dict
ALL_ETFS: dict[str, str] = {}
for group in ETF_UNIVERSE.values():
    ALL_ETFS.update(group)

# ── 자산군 최대 비중 제약 ──────────────────────────────
ASSET_CLASS_CONSTRAINTS = {
    "KR_EQUITY":     {"min": 0.00, "max": 0.40},
    "GLOBAL_EQUITY": {"min": 0.00, "max": 0.50},
    "BOND":          {"min": 0.10, "max": 0.60},
    "COMMODITY":     {"min": 0.00, "max": 0.20},
    "CASH":          {"min": 0.05, "max": 0.40},
}

# ── 리밸런싱 ──────────────────────────────────────────
REBALANCE_FREQUENCY = "monthly"   # monthly | weekly
REBALANCE_DAY = 1                  # 매월 1일 (영업일 기준 첫날)

# ── 리스크 파라미터 ────────────────────────────────────
TARGET_MDD = 0.12            # 목표 MDD (12%)
MAX_MDD_HARD_STOP = 0.18     # 하드스탑 MDD (18%)
LOOKBACK_MONTHS = 12         # 모멘텀 계산 기간 (개월)
MOMENTUM_SKIP_MONTHS = 1     # 최근 1개월 제외 (reversal 방지)
VOLATILITY_WINDOW = 60       # 변동성 계산 윈도우 (거래일)

# ── 백테스트 설정 ──────────────────────────────────────
BACKTEST_START = "2015-01-01"
BACKTEST_END   = datetime.today().strftime("%Y-%m-%d")
INITIAL_CAPITAL = 10_000_000   # 1천만원

# 수수료 / 세금
TRANSACTION_COST = 0.003    # 매수·매도 각 0.15% → 왕복 약 0.3%
SLIPPAGE = 0.001            # 슬리피지 0.1%

# Walk-Forward 설정
WF_TRAIN_YEARS = 3           # In-sample 기간
WF_TEST_YEARS  = 1           # Out-of-sample 기간
WF_STEP_MONTHS = 6           # 슬라이딩 스텝
