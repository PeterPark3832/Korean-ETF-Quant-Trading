"""
ETF 퀀트봇 실행 진입점

사용 방법:
─────────────────────────────────────────────────────────────
# 1. 스케줄러 시작 (상시 실행)
python run_bot.py

# 2. 전략 변경
python run_bot.py --strategy vaa
python run_bot.py --strategy risk_parity
python run_bot.py --strategy multi    # 멀티 전략 (DM+VAA+RP + 시장 국면 감지)

# 3. 즉시 리밸런싱 (수동 실행, 실제 주문)
python run_bot.py --now

# 4. 드라이런 (주문 없이 계획만 출력)
python run_bot.py --now --dry_run

# 5. 현재 포트폴리오 상태 확인
python run_bot.py --status

# 6. 리스크 중단 해제 (수동 재개)
python run_bot.py --resume

# 7. KIS 모의투자 API 사용
python run_bot.py --mode kis_paper

# 8. 실전 투자 (충분한 검증 후)
python run_bot.py --mode kis_real
─────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from scheduler import ETFQuantBot, setup_logger


def main():
    parser = argparse.ArgumentParser(
        description="ETF 퀀트봇",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--strategy", default="dual_momentum",
        choices=["dual_momentum", "vaa", "risk_parity", "multi", "factor_momentum"],
        help="전략 선택 (기본: dual_momentum)",
    )
    parser.add_argument(
        "--mode", default=None,
        choices=["paper", "kis_paper", "kis_real"],
        help="브로커 모드 (기본: .env KIS_MODE)",
    )
    parser.add_argument(
        "--now", action="store_true",
        help="즉시 리밸런싱 실행",
    )
    parser.add_argument(
        "--dry_run", action="store_true",
        help="실제 주문 없이 계획만 출력",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="현재 포트폴리오 상태 출력",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="리스크 중단 해제",
    )
    args = parser.parse_args()

    setup_logger()
    Path("logs").mkdir(exist_ok=True)

    # 봇 생성
    bot = ETFQuantBot(
        broker_mode   = args.mode,
        strategy_name = args.strategy,
        dry_run       = args.dry_run,
    )

    # ── 명령별 실행 ──────────────────────────────────────

    if args.status:
        bot.status()

    elif args.resume:
        bot.guard.resume()
        logger.info("거래 재개 완료")

    elif args.now:
        bot.rebalance_now(dry_run=args.dry_run)

    else:
        # 스케줄러 상시 실행
        print(f"""
╔══════════════════════════════════════════════╗
║        ETF 퀀트봇 - 자동 매매 시작           ║
╠══════════════════════════════════════════════╣
║  전략:   {args.strategy:<35} ║
║  모드:   {(args.mode or '(.env 설정 사용)'):<35} ║
║  종료:   Ctrl+C                              ║
╚══════════════════════════════════════════════╝
        """)
        bot.run()


if __name__ == "__main__":
    main()
