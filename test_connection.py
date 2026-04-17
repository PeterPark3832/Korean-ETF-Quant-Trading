"""
KIS API 연결 테스트 및 모의 브로커 동작 확인 스크립트

실행 방법:
    # 1단계: 모의 브로커 (API 키 불필요, 즉시 실행 가능)
    python test_connection.py --mode paper

    # 2단계: KIS 모의투자 API 연결 테스트
    python test_connection.py --mode kis_paper

    # 3단계: 리밸런싱 시뮬레이션 (Dry Run)
    python test_connection.py --mode paper --rebalance --dry_run
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from tabulate import tabulate

logger.remove()
logger.add(sys.stderr,
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
           level="INFO")


def test_paper_broker():
    """모의 브로커 기본 동작 테스트"""
    print("\n" + "="*55)
    print("  [1] 모의 브로커 테스트")
    print("="*55)

    from broker.paper_broker import PaperBroker

    broker = PaperBroker(initial_cash=10_000_000)
    broker.reset(initial_cash=10_000_000)   # 깨끗하게 시작

    # 잔고 확인
    bal = broker.get_balance()
    print(f"\n초기 잔고: {bal.cash:,.0f}원")

    # KODEX 200 매수 (가격 없으므로 직접 지정)
    print("\n--- KODEX 200 매수 테스트 (35,000원 가정) ---")
    r = broker.order_buy("069500", qty=10, price=35_000)
    print(f"  결과: {r}")

    # TIGER 미국S&P500 매수
    print("\n--- TIGER 미국S&P500 매수 테스트 (18,500원 가정) ---")
    r = broker.order_buy("360750", qty=20, price=18_500)
    print(f"  결과: {r}")

    # 잔고 확인
    bal = broker.get_balance()
    print(f"\n{bal}")

    # 매도 테스트
    print("\n--- KODEX 200 일부 매도 테스트 ---")
    r = broker.order_sell("069500", qty=5, price=35_500)
    print(f"  결과: {r}")

    # 거래 히스토리
    hist = broker.get_history()
    print(f"\n거래 히스토리 ({len(hist)}건):")
    if not hist.empty:
        print(hist[["datetime","name","side","qty","price","commission"]].to_string(index=False))

    print("\n[모의 브로커 테스트 완료]")


def test_kis_connection():
    """KIS API 연결 테스트"""
    print("\n" + "="*55)
    print("  [2] KIS API 연결 테스트")
    print("="*55)

    try:
        from broker.kis_client import KISClient
        from broker.kis_order import KISOrderManager

        client = KISClient()
        print(f"\n모드: {client.mode.upper()}")
        print(f"계좌: {client.acct_num}-{client.acct_prod}")

        # 토큰 발급
        token = client.token
        print(f"토큰 발급 성공 (앞 20자): {token[:20]}...")

        # 현재가 조회
        print("\n--- 현재가 조회 테스트 ---")
        test_tickers = ["069500", "360750", "132030"]
        for ticker in test_tickers:
            try:
                info = client.get_price(ticker)
                print(f"  [{ticker}] {info['name']}: {info['price']:,}원 ({info['change_rate']:+.2f}%)")
            except Exception as e:
                print(f"  [{ticker}] 조회 실패: {e}")

        # 잔고 조회
        print("\n--- 계좌 잔고 조회 ---")
        om  = KISOrderManager(client)
        bal = om.get_balance()
        print(bal)

        print("\n[KIS API 연결 테스트 완료]")

    except ValueError as e:
        print(f"\n설정 오류: {e}")
        print("\n.env 파일을 확인하세요:")
        print("  cp .env.example .env")
        print("  # .env 파일에 KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO 입력")
    except Exception as e:
        print(f"\n연결 실패: {e}")
        logger.exception("상세 오류")


def test_rebalance_dry_run(mode: str = "paper"):
    """리밸런싱 드라이런 테스트"""
    print("\n" + "="*55)
    print("  [3] 리밸런싱 Dry Run 테스트")
    print("="*55)

    from broker import create_broker
    from portfolio.rebalancer import PortfolioRebalancer
    from strategy import DualMomentumStrategy
    from data.fetcher import ETFDataFetcher
    from config import ALL_ETFS

    # 브로커 생성
    broker = create_broker(mode)

    if mode == "paper":
        # 모의 브로커에 초기 포트폴리오 설정
        broker.reset(initial_cash=10_000_000)
        # 임시 가격으로 초기 매수 (실제론 현재가 사용)
        sample_prices = {
            "069500": 35_000,   # KODEX 200
            "360750": 18_500,   # TIGER S&P500
            "157450": 102_500,  # TIGER 단기통안채
            "132030": 14_200,   # KODEX 골드
        }
        for ticker, price in sample_prices.items():
            broker.order_buy(ticker, qty=5, price=price)

    # 전략 준비
    strategy = DualMomentumStrategy(lookback_months=12, skip_months=1)

    # 가격 데이터 로드 (캐시 우선 사용)
    print("\n가격 데이터 로드 중...")
    from config import BACKTEST_START, BACKTEST_END
    end_dt   = BACKTEST_END    # 캐시에 있는 최신 날짜
    start_dt = (datetime.strptime(end_dt, "%Y-%m-%d")
                - timedelta(days=400)).strftime("%Y-%m-%d")

    fetcher  = ETFDataFetcher()
    tickers  = list(ALL_ETFS.keys())
    try:
        prices = fetcher.get_prices(tickers, start_dt, end_dt)
        print(f"로드 완료: {len(prices)}거래일 × {len(prices.columns)}종목")
    except Exception as e:
        print(f"가격 데이터 로드 실패: {e}")
        return

    # 현재 날짜 기준 전략 신호
    target_weights = strategy.get_weights(prices)
    print("\n전략 목표 비중:")
    for t, w in target_weights[target_weights > 0.01].sort_values(ascending=False).items():
        print(f"  {ALL_ETFS.get(t, t):25s}: {w*100:.1f}%")

    # 리밸런싱 실행 (DRY RUN)
    rebalancer = PortfolioRebalancer(
        broker              = broker,
        strategy_fn         = strategy.get_weights,
        price_data          = prices,   # 장외시간 fallback 가격 소스
        rebalance_threshold = 0.03,
        dry_run             = True,
    )
    result = rebalancer.run(prices_window=prices)
    print(result.summary())


def main():
    parser = argparse.ArgumentParser(description="KIS API 연결 테스트")
    parser.add_argument("--mode",      default="paper",
                        choices=["paper", "kis_paper", "kis_real"],
                        help="브로커 모드")
    parser.add_argument("--rebalance", action="store_true",
                        help="리밸런싱 드라이런 추가 실행")
    parser.add_argument("--dry_run",   action="store_true",
                        help="실제 주문 없이 계획만 출력")
    args = parser.parse_args()

    if args.mode == "paper":
        test_paper_broker()
    elif args.mode in ("kis_paper", "kis_real"):
        test_kis_connection()

    if args.rebalance:
        test_rebalance_dry_run(args.mode)


if __name__ == "__main__":
    main()
