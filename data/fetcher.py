"""
ETF 가격 데이터 수집 모듈
- pykrx: 한국거래소 ETF OHLCV
- FinanceDataReader: 보조 / 장기 히스토리 보완
- 로컬 캐시(Parquet)로 API 호출 최소화
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

# ── 선택적 임포트 ─────────────────────────────────────
try:
    from pykrx import stock as pykrx_stock
    PYKRX_AVAILABLE = True
except ImportError:
    PYKRX_AVAILABLE = False
    logger.warning("pykrx not installed. run: pip install pykrx")

try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except ImportError:
    FDR_AVAILABLE = False
    logger.warning("FinanceDataReader not installed. run: pip install finance-datareader")

from config import DATA_DIR, ALL_ETFS


class ETFDataFetcher:
    """
    한국 상장 ETF 가격 데이터 수집 및 캐시 관리

    사용법:
        fetcher = ETFDataFetcher()
        prices = fetcher.get_prices(
            tickers=["069500", "360750"],
            start="2018-01-01",
            end="2024-12-31",
        )
    """

    CACHE_DIR = DATA_DIR
    CACHE_MAX_AGE_DAYS = 1          # 1일 이상 된 캐시는 재수집
    REQUEST_DELAY_SEC = 0.3         # pykrx 과부하 방지

    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── 공개 인터페이스 ────────────────────────────────

    def get_prices(
        self,
        tickers: list[str],
        start: str,
        end: str,
        field: str = "Close",
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        여러 종목의 종가(또는 지정 필드) DataFrame 반환
        index: DatetimeIndex, columns: ticker
        """
        frames: list[pd.Series] = []
        for ticker in tickers:
            series = self._get_single(ticker, start, end, field, force_refresh)
            if series is not None:
                frames.append(series.rename(ticker))
            else:
                logger.warning(f"[{ticker}] 데이터 없음 - 스킵")

        if not frames:
            raise ValueError("수집된 데이터가 없습니다.")

        df = pd.concat(frames, axis=1)
        df = df.sort_index()
        df = df.loc[start:end]
        df = df.ffill().bfill()   # 휴장일 공백 채우기
        return df

    def get_ohlcv(
        self,
        ticker: str,
        start: str,
        end: str,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """단일 종목 OHLCV 반환"""
        return self._fetch_ohlcv(ticker, start, end, force_refresh)

    def get_universe_prices(
        self,
        start: str,
        end: str,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """config.ALL_ETFS 전체 가격 DataFrame"""
        return self.get_prices(
            tickers=list(ALL_ETFS.keys()),
            start=start,
            end=end,
            force_refresh=force_refresh,
        )

    # ── 내부 메서드 ────────────────────────────────────

    def _get_single(
        self,
        ticker: str,
        start: str,
        end: str,
        field: str,
        force_refresh: bool,
    ) -> Optional[pd.Series]:
        ohlcv = self._fetch_ohlcv(ticker, start, end, force_refresh)
        if ohlcv is None or ohlcv.empty:
            return None
        if field not in ohlcv.columns:
            logger.warning(f"[{ticker}] 컬럼 '{field}' 없음 (보유: {ohlcv.columns.tolist()})")
            return None
        return ohlcv[field]

    def _fetch_ohlcv(
        self,
        ticker: str,
        start: str,
        end: str,
        force_refresh: bool = False,
    ) -> Optional[pd.DataFrame]:
        """캐시 우선 → 없으면 pykrx → 실패 시 FDR fallback"""
        cache_path = self.CACHE_DIR / f"{ticker}.parquet"

        # 캐시 유효성 확인
        if not force_refresh and self._is_cache_valid(cache_path, end):
            df = pd.read_parquet(cache_path)
            return df.loc[start:end]

        # pykrx 수집
        df = self._fetch_pykrx(ticker, start, end)

        # fallback: FinanceDataReader
        if df is None or df.empty:
            df = self._fetch_fdr(ticker, start, end)

        if df is None or df.empty:
            return None

        # 캐시 저장
        self._save_cache(cache_path, df)
        return df.loc[start:end]

    def _fetch_pykrx(self, ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
        if not PYKRX_AVAILABLE:
            return None
        try:
            start_fmt = start.replace("-", "")
            end_fmt   = end.replace("-", "")
            df = pykrx_stock.get_market_ohlcv_by_date(
                start_fmt, end_fmt, ticker
            )
            if df is None or df.empty:
                return None
            df.index = pd.to_datetime(df.index)
            # pykrx 버전에 따라 5~6개 컬럼 반환 대응
            col_map = {
                0: "Open", 1: "High", 2: "Low", 3: "Close", 4: "Volume"
            }
            df.columns = [col_map.get(i, f"col{i}") for i in range(len(df.columns))]
            df = df[df["Close"] > 0]
            time.sleep(self.REQUEST_DELAY_SEC)
            logger.debug(f"[pykrx] {ticker} {start}~{end} {len(df)}행")
            return df
        except Exception as e:
            logger.warning(f"[pykrx] {ticker} 수집 실패: {e}")
            return None

    def _fetch_fdr(self, ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
        if not FDR_AVAILABLE:
            return None
        try:
            df = fdr.DataReader(ticker, start=start, end=end)
            if df is None or df.empty:
                return None
            df.index = pd.to_datetime(df.index)
            # FDR 컬럼 표준화
            rename_map = {
                "Open": "Open", "High": "High", "Low": "Low",
                "Close": "Close", "Volume": "Volume",
                "Adj Close": "Close",
            }
            df = df.rename(columns=rename_map)
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                if col not in df.columns:
                    df[col] = df.get("Close", 0)
            df = df[["Open", "High", "Low", "Close", "Volume"]]
            df = df[df["Close"] > 0]
            logger.debug(f"[FDR] {ticker} {start}~{end} {len(df)}행")
            return df
        except Exception as e:
            logger.warning(f"[FDR] {ticker} 수집 실패: {e}")
            return None

    def _is_cache_valid(self, path: Path, end: str) -> bool:
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        age   = datetime.now() - mtime

        # 요청 종료일이 오늘 이전이면 캐시 영구 유효
        if end < datetime.now().strftime("%Y-%m-%d"):
            return True

        return age.days < self.CACHE_MAX_AGE_DAYS

    def _save_cache(self, path: Path, df: pd.DataFrame) -> None:
        try:
            # 기존 캐시와 병합 (기간 확장)
            if path.exists():
                existing = pd.read_parquet(path)
                df = pd.concat([existing, df])
                df = df[~df.index.duplicated(keep="last")]
                df = df.sort_index()
            df.to_parquet(path)
        except Exception as e:
            logger.warning(f"캐시 저장 실패: {path} - {e}")


# ── 편의 함수 ──────────────────────────────────────────

_fetcher: Optional[ETFDataFetcher] = None

def get_fetcher() -> ETFDataFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = ETFDataFetcher()
    return _fetcher


def load_prices(
    tickers: list[str],
    start: str,
    end: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """최상위 편의 함수"""
    return get_fetcher().get_prices(tickers, start, end, force_refresh=force_refresh)
