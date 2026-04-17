from .kis_client import KISClient
from .kis_order import KISOrderManager, AccountBalance, OrderResult
from .paper_broker import PaperBroker


def create_broker(mode: str = "paper", **kwargs):
    """
    브로커 팩토리 함수

    Args:
        mode: "paper" = 모의 브로커 (기본)
              "kis_paper" = KIS 모의투자 API
              "kis_real"  = KIS 실전투자 API

    사용법:
        broker = create_broker("paper")                  # 로컬 모의
        broker = create_broker("kis_paper")              # KIS 모의투자
        broker = create_broker("kis_real")               # KIS 실전
    """
    if mode == "paper":
        return PaperBroker(**kwargs)
    elif mode in ("kis_paper", "kis_real"):
        kis_mode = "paper" if mode == "kis_paper" else "real"
        client   = KISClient(mode=kis_mode)
        return KISOrderManager(client)
    else:
        raise ValueError(f"지원하지 않는 브로커 모드: {mode}")
