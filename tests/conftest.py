"""
테스트 공통 픽스처
"""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_prices() -> pd.DataFrame:
    """28개 ETF × 300 거래일 샘플 가격 데이터 (랜덤 워크)"""
    tickers = [
        "069500", "102110", "278540",               # KR_EQUITY
        "360750", "379800", "195970", "192090", "381170",  # GLOBAL_EQUITY
        "114820", "148070", "308620", "136340",     # BOND
        "132030", "261220", "144600",               # COMMODITY
        "449170", "157450",                         # CASH
    ]
    np.random.seed(42)
    n_days = 300
    dates = pd.bdate_range("2023-01-01", periods=n_days)
    prices = pd.DataFrame(
        index=dates,
        columns=tickers,
        data=np.cumprod(1 + np.random.randn(n_days, len(tickers)) * 0.01, axis=0) * 10_000,
    )
    return prices.round(0).astype(float)


@pytest.fixture
def long_prices() -> pd.DataFrame:
    """전략 모멘텀 계산에 충분한 3년치 가격 데이터"""
    tickers = [
        "069500", "102110", "278540",
        "360750", "379800", "195970", "192090", "381170",
        "114820", "148070", "308620", "136340",
        "132030", "261220", "144600",
        "449170", "157450",
    ]
    np.random.seed(7)
    n_days = 800
    dates = pd.bdate_range("2021-01-01", periods=n_days)
    prices = pd.DataFrame(
        index=dates,
        columns=tickers,
        data=np.cumprod(1 + np.random.randn(n_days, len(tickers)) * 0.008, axis=0) * 10_000,
    )
    return prices.round(0).astype(float)
