"""
utils/market.py 단위 테스트
"""
import pytest
from utils.market import tick_price, TICK_SIZE_TABLE


class TestTickPrice:
    def test_under_2000_tick_1(self):
        # tick=1 구간: 모든 정수가 이미 호가에 맞으므로 올림/내림 모두 원래 값
        assert tick_price(1_500, "up") == 1_500
        assert tick_price(1_501, "up") == 1_501
        assert tick_price(1_501, "down") == 1_501
        assert tick_price(1_999, "up") == 1_999

    def test_2000_to_5000_tick_5(self):
        assert tick_price(2_001, "up") == 2_005
        assert tick_price(2_005, "up") == 2_005
        assert tick_price(2_004, "down") == 2_000

    def test_5000_to_10000_tick_10(self):
        assert tick_price(5_001, "up") == 5_010
        assert tick_price(5_010, "up") == 5_010
        assert tick_price(5_009, "down") == 5_000

    def test_10000_to_50000_tick_50(self):
        assert tick_price(10_001, "up") == 10_050
        assert tick_price(10_050, "up") == 10_050
        assert tick_price(10_049, "down") == 10_000

    def test_50000_to_100000_tick_100(self):
        assert tick_price(50_001, "up") == 50_100
        assert tick_price(50_100, "up") == 50_100

    def test_100000_to_500000_tick_500(self):
        assert tick_price(100_001, "up") == 100_500
        assert tick_price(100_500, "up") == 100_500

    def test_above_500000_tick_1000(self):
        assert tick_price(500_001, "up") == 501_000
        assert tick_price(501_000, "up") == 501_000

    def test_exact_boundary_up(self):
        # 경계값 자체는 틱 조정 불필요
        assert tick_price(2_000, "up") == 2_000
        assert tick_price(5_000, "up") == 5_000
        assert tick_price(10_000, "up") == 10_000

    def test_tick_size_table_sorted(self):
        # 테이블이 내림차순 정렬되어 있는지 확인
        thresholds = [t for t, _ in TICK_SIZE_TABLE]
        assert thresholds == sorted(thresholds, reverse=True)
