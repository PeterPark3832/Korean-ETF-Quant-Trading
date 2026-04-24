"""
KIS API 연결 테스트 및 모의 브로커 동작 확인 스크립트

[개선] 드라이런 시 실제 호가 틱 단위(Tick Price)를 반영하여
계산된 이론적 목표 비중과 실제 체결 예상 비중 간의 괴리를 시뮬레이션 합니다.

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
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

logger.remove()
logger.add(sys.stderr,
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
           level="INFO")


def _simulate_tick_price(price: int, direction: str = "up") -> int:
    """KRX 호가단위 틱 보정 (rebalancer.py 로직 복제)"""
    if price < 2_000:        tick = 1
    elif price < 5_000:      tick = 5
    elif price < 10_000:     tick = 10
    elif price < 50_000:     tick = 50
    elif price < 100_000:    tick = 100
    elif price < 500_000:    tick = 500
    else:                    tick = 1_000
    if direction == "up":
        return ((price + tick - 1) // tick) * tick
    return (price // tick) * tick


def test_paper_broker():
    """모의 브로커 기본 동작 테스트"""
    print("\n" + "="*55)
    print("  [1] 모의 브로커 테스트")
    print("="*55)

    from broker.paper_broker import PaperBroker

    broker = PaperBroker(initial_cash=10_000_000)
    broker.reset(initial_cash=10_000_000)   # 깨끗하게 시작

    bal = broker.get_balance()
    print(f"\n초기 잔고: {bal.cash:,.0f}원")

    print("\n--- KODEX 200 매수 테스트 (35,000원 가정) ---")
    r = broker.order_buy("069500", qty=10, price=35_000)
    print(f"  결과: {r}")

    print("\n--- TIGER 미국S&P500 매수 테스트 (18,500원 가정) ---")
    r = broker.order_buy("360750", qty=20, price=18_500)
    print(f"  결과: {r}")

    bal = broker.get_balance()
    print(f"\n{bal}")

    print("\n--- KODEX 200 일부 매도 테스트 ---")
    r = broker.order_sell("069500", qty=5, price=35_500)
    print(f"  결과: {r}")

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

        token = client.token
        print(f"토큰 발급 성공 (앞 20자): {token[:20]}...")

        print("\n--- 현재가 조회 테스트 ---")
        test_tickers = ["069500", "360750", "132030"]
        for ticker in test_tickers:
            try:
                info = client.get_price(ticker)
                print(f"  [{ticker}] {info['name']}: {info['price']:,}원 ({info['change_rate']:+.2f}%)")
            except Exception as e:
                print(f"  [{ticker}] 조회 실패: {e}")

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
    """리밸런싱 드라이런 테스트 (틱 보정 시뮬레이션 포함)"""
    print("\n" + "="*55)
    print("  [3] 리밸런싱 Dry Run & 틱(Tick) 오차 시뮬레이션")
    print("="*55)

    from broker import create_broker
    from portfolio.rebalancer import PortfolioRebalancer
    from strategy import DualMomentumStrategy
    from data.fetcher import ETFDataFetcher
    from config import ALL_ETFS, BACKTEST_END, validate_etf_universe

    # 1. 포트폴리오 유니버스 검증
    print("\n--- ETF 유니버스 검증 ---")
    validate_etf_universe()

    # 2. 브로커 준비
    broker = create_broker(mode)

    if mode == "paper":
        broker.reset(initial_cash=10_000_000)
        sample_prices = {
            "069500": 35_000,   
            "360750": 18_500,   
            "157450": 102_500,  
            "132030": 14_200,   
        }
        for ticker, price in sample_prices.items():
            broker.order_buy(ticker, qty=5, price=price)

    strategy = DualMomentumStrategy(lookback_months=12, skip_months=1)

    print("\n가격 데이터 로드 중...")
    end_dt   = BACKTEST_END
    start_dt = (datetime.strptime(end_dt, "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")

    fetcher  = ETFDataFetcher()
    tickers  = list(ALL_ETFS.keys())
    try:
        prices = fetcher.get_prices(tickers, start_dt, end_dt)
        print(f"로드 완료: {len(prices)}거래일 × {len(prices.columns)}종목")
    except Exception as e:
        print(f"가격 데이터 로드 실패: {e}")
        return

    # 3. 전략 목표 비중 산출
    target_weights = strategy.get_weights(prices)
    print("\n--- 이론적 목표 비중 ---")
    for t, w in target_weights[target_weights > 0.01].sort_values(ascending=False).items():
        print(f"  {ALL_ETFS.get(t, t):20s}: {w*100:5.1f}%")

    # 4. 리밸런싱 실행 (단순 드라이런 결과 수집)
    rebalancer = PortfolioRebalancer(
        broker              = broker,
        strategy_fn         = strategy.get_weights,
        price_data          = prices,
        rebalance_threshold = 0.03,
        dry_run             = True,
    )
    result = rebalancer.run(prices_window=prices)
    
    # 5. [핵심] 실제 호가 틱(Tick) 단위 적용 시 오차 분석
    total_assets = result.total_assets
    if result.orders and total_assets > 0:
        print("\n" + "="*55)
        print(" 🔍 실제 호가(Tick) 적용 시 예상 체결 단가 및 비중 오차")
        print("="*55)
        print(f"  {'종목명':14s} | {'단순가':>7s} → {'실제호가(틱)':>10s} | {'이론비중'} → {'실제비중'}")
        print("-" * 55)
        
        for o in result.orders:
            # 매수는 호가 올림, 매도는 내림
            direction = "up" if o.side == "buy" else "down"
            real_price = _simulate_tick_price(o.price, direction)
            
            # 틱 보정으로 인해 변경되는 실제 체결 예정 금액
            real_exec_amount = o.qty * real_price
            
            # 매수/매도 후 최종 예상 비중 (단순 시뮬레이션)
            if o.side == "buy":
                est_final_amount = (o.current_weight * total_assets) + real_exec_amount
            else:
                est_final_amount = max(0, (o.current_weight * total_assets) - real_exec_amount)
                
            real_weight = (est_final_amount / total_assets) * 100
            target_w_percent = o.target_weight * 100
            
            # 틱에 의한 오차(%)
            diff = real_weight - target_w_percent
            
            color = "\033[91m" if abs(diff) > 1.0 else "" # 1% 이상 차이나면 빨간색 (터미널 지원 시)
            reset = "\033[0m"
            
            print(f"  {o.name[:14]:14s} | {o.price:>7,} → {real_price:>10,}원 | {target_w_percent:>6.1f}% → {color}{real_weight:>6.1f}%{reset} (오차: {diff:+.1f}%)")
        print("="*55)
        print("※ 호가 단위가 큰 종목일수록, 또는 소액 계좌일수록 실제 체결 비중과 퀀트 모델의 이론적 비중 간의 오차가 커질 수 있습니다.")


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
