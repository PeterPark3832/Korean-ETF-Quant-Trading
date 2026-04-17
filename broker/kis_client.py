"""
한국투자증권 KIS API 클라이언트
────────────────────────────────────────────────────────────────
KIS Developers (https://apiportal.koreainvestment.com) REST API 연동

주요 기능:
  - OAuth2 Access Token 발급 / 자동 갱신
  - 실전투자 / 모의투자 도메인 자동 전환
  - 요청 제한(초당 20회) 준수를 위한 Rate Limiter 내장
  - 재시도 로직 (일시적 오류 자동 복구)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import requests
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

# ── 도메인 ────────────────────────────────────────────
REAL_DOMAIN  = "https://openapi.koreainvestment.com:9443"
PAPER_DOMAIN = "https://openapivts.koreainvestment.com:29443"

# 토큰 캐시 경로
TOKEN_CACHE = Path(__file__).parent.parent / "data" / "cache" / ".kis_token.json"


class RateLimiter:
    """초당 최대 N회 요청 제한"""

    def __init__(self, max_per_second: float = 18.0):
        self._min_interval = 1.0 / max_per_second
        self._last_call    = 0.0
        self._lock         = Lock()

    def wait(self) -> None:
        with self._lock:
            now     = time.time()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()


class KISClient:
    """
    KIS REST API 클라이언트

    사용법:
        client = KISClient()                    # .env에서 자동 로드
        client = KISClient(mode="paper")        # 모의투자 강제 지정
        balance = client.get_balance()
        client.order_buy("069500", qty=10)
    """

    def __init__(
        self,
        app_key:    str | None = None,
        app_secret: str | None = None,
        account_no: str | None = None,
        mode:       str | None = None,          # "real" | "paper"
    ):
        self.app_key    = app_key    or os.getenv("KIS_APP_KEY",    "")
        self.app_secret = app_secret or os.getenv("KIS_APP_SECRET", "")
        self.account_no = account_no or os.getenv("KIS_ACCOUNT_NO", "")
        self.mode       = (mode or os.getenv("KIS_MODE", "paper")).lower()

        if not self.app_key or not self.app_secret:
            raise ValueError(
                "KIS_APP_KEY / KIS_APP_SECRET 미설정\n"
                ".env 파일에 키를 입력하거나 환경 변수로 설정하세요."
            )

        self.domain      = REAL_DOMAIN if self.mode == "real" else PAPER_DOMAIN
        self._token:     str | None = None
        self._token_exp: datetime   = datetime.min
        self._rate       = RateLimiter(max_per_second=18)

        # 계좌번호 파싱: "12345678-01" 또는 "1234567801"
        parts = self.account_no.replace("-", "")
        self.acct_num  = parts[:8]   # 계좌번호 8자리
        self.acct_prod = parts[8:]   # 상품코드 2자리 (기본 "01")
        if not self.acct_prod:
            self.acct_prod = "01"

        logger.info(
            f"KIS 클라이언트 초기화 | 모드={self.mode.upper()} | "
            f"계좌={self.acct_num}-{self.acct_prod}"
        )

    # ── 인증 ──────────────────────────────────────────

    @property
    def token(self) -> str:
        """Access Token (만료 5분 전 자동 갱신)"""
        if self._token is None or datetime.now() >= self._token_exp - timedelta(minutes=5):
            self._refresh_token()
        return self._token  # type: ignore

    def _refresh_token(self) -> None:
        """캐시 토큰 사용 → 없거나 만료면 신규 발급"""
        cached = self._load_token_cache()
        if cached:
            self._token     = cached["access_token"]
            self._token_exp = datetime.fromisoformat(cached["expires_at"])
            if datetime.now() < self._token_exp - timedelta(minutes=5):
                logger.debug("토큰 캐시 사용")
                return

        # 신규 발급
        url  = f"{self.domain}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey":     self.app_key,
            "appsecret":  self.app_secret,
        }
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if "access_token" not in data:
            raise RuntimeError(f"토큰 발급 실패: {data}")

        self._token     = data["access_token"]
        expires_in      = int(data.get("expires_in", 86400))
        self._token_exp = datetime.now() + timedelta(seconds=expires_in)

        self._save_token_cache(self._token, self._token_exp)
        logger.info(f"KIS 토큰 발급 완료 (만료: {self._token_exp:%Y-%m-%d %H:%M})")

    def _load_token_cache(self) -> dict | None:
        try:
            if TOKEN_CACHE.exists():
                data = json.loads(TOKEN_CACHE.read_text())
                if data.get("mode") == self.mode and data.get("app_key") == self.app_key:
                    return data
        except Exception:
            pass
        return None

    def _save_token_cache(self, token: str, expires: datetime) -> None:
        try:
            TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_CACHE.write_text(json.dumps({
                "access_token": token,
                "expires_at":   expires.isoformat(),
                "mode":         self.mode,
                "app_key":      self.app_key,
            }))
        except Exception as e:
            logger.warning(f"토큰 캐시 저장 실패: {e}")

    # ── 공통 요청 헬퍼 ────────────────────────────────

    def _get(
        self,
        path: str,
        tr_id: str,
        params: dict[str, Any],
        retries: int = 3,
    ) -> dict:
        url     = f"{self.domain}{path}"
        headers = self._build_headers(tr_id)
        for attempt in range(retries):
            self._rate.wait()
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if data.get("rt_cd") == "0":
                    return data
                # 토큰 만료 시 재발급 후 재시도
                if data.get("msg_cd") in ("EGW00123", "EGW00121"):
                    logger.warning("토큰 만료 → 재발급")
                    self._token = None
                    headers     = self._build_headers(tr_id)
                    continue
                logger.error(f"API 오류: {data.get('msg1', '')} ({data.get('msg_cd', '')})")
                return data
            except requests.RequestException as e:
                logger.warning(f"요청 실패 [{attempt+1}/{retries}]: {e}")
                time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"API 요청 {retries}회 실패: {path}")

    def _post(
        self,
        path: str,
        tr_id: str,
        body: dict[str, Any],
        retries: int = 3,
    ) -> dict:
        url     = f"{self.domain}{path}"
        headers = self._build_headers(tr_id)
        for attempt in range(retries):
            self._rate.wait()
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if data.get("rt_cd") == "0":
                    return data
                if data.get("msg_cd") in ("EGW00123", "EGW00121"):
                    self._token = None
                    headers     = self._build_headers(tr_id)
                    continue
                logger.error(f"API 오류: {data.get('msg1', '')} ({data.get('msg_cd', '')})")
                return data
            except requests.RequestException as e:
                logger.warning(f"요청 실패 [{attempt+1}/{retries}]: {e}")
                time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"API 요청 {retries}회 실패: {path}")

    def _build_headers(self, tr_id: str) -> dict:
        return {
            "Content-Type":  "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token}",
            "appkey":        self.app_key,
            "appsecret":     self.app_secret,
            "tr_id":         tr_id,
            "custtype":      "P",   # 개인
        }

    # ── 현재가 조회 ───────────────────────────────────

    def get_price(self, ticker: str) -> dict:
        """
        주식/ETF 현재가 조회

        Returns:
            {
                "ticker": "069500",
                "name": "KODEX 200",
                "price": 35000,
                "change_rate": 0.5,
                "volume": 123456,
            }
        """
        tr_id  = "FHKST01010100"
        params = {
            "fid_cond_mrkt_div_code": "J",   # 주식/ETF
            "fid_input_iscd":         ticker,
        }
        data   = self._get("/uapi/domestic-stock/v1/quotations/inquire-price", tr_id, params)
        output = data.get("output", {})
        return {
            "ticker":      ticker,
            "name":        output.get("hts_kor_isnm", ""),
            "price":       int(output.get("stck_prpr", 0)),
            "change_rate": float(output.get("prdy_ctrt", 0)),
            "volume":      int(output.get("acml_vol", 0)),
            "raw":         output,
        }

    def get_prices_bulk(self, tickers: list[str]) -> dict[str, dict]:
        """여러 종목 현재가 일괄 조회"""
        result = {}
        for ticker in tickers:
            try:
                result[ticker] = self.get_price(ticker)
            except Exception as e:
                logger.warning(f"[{ticker}] 현재가 조회 실패: {e}")
        return result
