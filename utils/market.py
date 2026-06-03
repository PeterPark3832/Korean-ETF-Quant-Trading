"""
KRX 시장 관련 유틸리티
"""
from __future__ import annotations

# KRX 호가단위 테이블 (가격 하한, 틱 크기)
TICK_SIZE_TABLE: tuple[tuple[int, int], ...] = (
    (500_000, 1_000),
    (100_000,   500),
    ( 50_000,   100),
    ( 10_000,    50),
    (  5_000,    10),
    (  2_000,     5),
    (      0,     1),
)


def tick_price(price: int, direction: str = "up") -> int:
    """
    KRX 호가단위 기준으로 가격을 조정한다.

    Args:
        price:     원본 가격 (원)
        direction: "up" → 매수용 올림, "down" → 매도용 내림

    Returns:
        호가단위에 맞게 조정된 가격
    """
    tick = _get_tick_size(price)
    if direction == "up":
        return ((price + tick - 1) // tick) * tick
    return (price // tick) * tick


def _get_tick_size(price: int) -> int:
    for threshold, size in TICK_SIZE_TABLE:
        if price >= threshold:
            return size
    return 1
