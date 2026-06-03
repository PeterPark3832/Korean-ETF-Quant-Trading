# 아키텍처 문서

Korean ETF Quant Trading Bot의 기술 아키텍처 및 설계 원칙을 설명합니다.

---

## 전체 구조

```
┌─────────────────────────────────────────────────────────────┐
│                        run_bot.py                            │
│                    (CLI 진입점)                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    ETFQuantBot (scheduler.py)                 │
│   APScheduler + Telegram 폴링 + FastAPI 대시보드             │
│                                                              │
│  09:05 job_morning_reset()    → RiskGuard.reset_daily()      │
│  09:10 job_risk_check()       → RiskGuard.check()            │
│  1일(영업) job_monthly_rebalance() → PortfolioRebalancer.run()│
│  15:35 job_daily_close()      → PerformanceReporter.record() │
└─────┬────────────┬────────────┬──────────────────────────────┘
      │            │            │
      ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────────────┐
│ Strategy │ │  Broker  │ │   RiskGuard       │
│ (전략)   │ │ (브로커) │ │   (리스크 관리)   │
└──────────┘ └──────────┘ └──────────────────┘
```

---

## 레이어별 역할

### 1. 진입점 레이어

| 파일 | 역할 |
|------|------|
| `run_bot.py` | CLI 파싱 → ETFQuantBot 초기화 → 스케줄러 시작 |
| `run_backtest.py` | 백테스트 실행, 차트 생성, Walk-Forward 검증 |
| `test_connection.py` | 브로커/API 통합 테스트 |

### 2. 오케스트레이션 레이어

`scheduler.py`의 `ETFQuantBot`이 전체 생명주기를 관리합니다:
- APScheduler로 시간 기반 작업 스케줄링
- 백그라운드 스레드: Telegram 명령 폴링, FastAPI 대시보드
- 상태 의존성: 브로커 → 전략 → 리스크 감시 → 리밸런서

### 3. 전략 레이어 (`strategy/`)

**핵심 설계: Strategy Pattern**

```python
class BaseStrategy(ABC):
    @abstractmethod
    def get_weights(self, prices: pd.DataFrame) -> pd.Series: ...

    # 공통 유틸리티 (리팩토링 v2에서 추가)
    def _all_cash(self, tickers, preferred_order=None) -> pd.Series: ...
    @staticmethod
    def normalize_weights(weights) -> pd.Series: ...
```

모든 전략은 `get_weights(prices) → Series(합계=1)`만 구현하면 됩니다.
`BacktestEngine`과 `PortfolioRebalancer`는 이 인터페이스만 사용합니다.

**전략 팩토리** (`strategy/__init__.py`):
```python
create_strategy(name: str, **kwargs) -> BaseStrategy
```

### 4. 브로커 레이어 (`broker/`)

**Factory Pattern으로 환경 추상화:**

```
create_broker(mode) →  "paper"     → PaperBroker
                       "kis_paper" → KISOrderManager(paper_domain)
                       "kis_real"  → KISOrderManager(real_domain)
```

모든 브로커는 다음 인터페이스를 공유합니다:
- `get_balance()` → `AccountBalance`
- `order_buy(ticker, qty, price, order_type)` → `OrderResult`
- `order_sell(ticker, qty, price)` → `OrderResult`

`KISClient`는 KIS REST API 저수준 래퍼이며, `_request_with_retry()`로 GET/POST 재시도 로직을 통합합니다.

### 5. 포트폴리오 레이어 (`portfolio/`)

`PortfolioRebalancer.run(prices_window)`:

```
잔고 조회 → 현재 비중 계산 → 전략 신호 → 비중 비교
→ 주문 계획 (임계값 3%) → 매도 먼저 → 매수
→ RebalanceResult 반환
```

**핵심 상수** (리팩토링으로 명명화):
- `_BUY_CASH_RATIO = 0.99` — 매수 시 가용 현금의 99%만 사용
- `_KIS_AVAILABLE_RATIO = 0.98` — KIS 조회 가용현금의 98%
- `_DEFAULT_AVAILABLE_RATIO = 0.95` — 브로커 기본 현금 비율

### 6. 리스크 레이어 (`risk/`)

`RiskGuard.check(balance)` → `RiskCheckResult(action: str)`

```
action 종류:
  "normal"  → 정상, 거래 허용
  "warn"    → 경보, 거래 허용하되 Telegram 알림
  "reduce"  → 포지션 축소 (soft-stop)
  "halt"    → 거래 전면 중단 (hard-stop)
```

상태는 `data/cache/risk_state.json`에 영속화되어 봇 재시작 후에도 유지됩니다.

### 7. 유틸리티 레이어 (`utils/`)

`utils/market.py`:
- `tick_price(price, direction)` — KRX 호가단위 보정
- `TICK_SIZE_TABLE` — 가격 구간별 틱 크기 테이블

---

## 데이터 흐름

```
pykrx/FinanceDataReader
    │  (0.3s 딜레이, 1일 TTL Parquet 캐시)
    ▼
data/fetcher.py → prices: pd.DataFrame(index=date, columns=ticker)
    │
    ├─► BacktestEngine.run() → 과거 시뮬레이션
    │
    └─► PortfolioRebalancer.run()
            │
            ├─ strategy.get_weights(prices_window) → target_weights
            ├─ broker.get_balance() → current_weights
            └─ 주문 실행 → broker.order_buy/sell()
```

---

## 스케줄링

| 시간 | 주기 | 작업 |
|------|------|------|
| 09:05 | 평일 | 일간 리스크 기준점 초기화 (`reset_daily`) |
| 09:10 | 평일 | 리스크 체크, 필요 시 포지션 축소 |
| 매월 첫 영업일 15:15 | 월 1회 | 리밸런싱 실행 |
| 15:35 | 평일 | NAV 기록, 일일 리포트 Telegram 발송 |

---

## 캐시 및 영속화

| 파일 | 내용 | TTL |
|------|------|-----|
| `data/cache/*.parquet` | ETF OHLCV 가격 | 1일 |
| `data/cache/risk_state.json` | 리스크 상태 (peak, MDD, halt) | 영구 |
| `data/cache/performance.json` | NAV 이력 | 90일 롤링 |
| `data/cache/.kis_token.json` | KIS OAuth2 토큰 | 24시간 |

---

## 테스트 전략

```
tests/
├── conftest.py           # 공통 픽스처 (샘플 가격 데이터)
├── test_utils.py         # utils/market.py — KRX 호가단위
├── test_metrics.py       # backtest/metrics.py — 성과 지표
├── test_strategies.py    # 5개 전략 — 공통 계약 검증
├── test_risk_guard.py    # risk/guard.py — 리스크 상태 머신
└── test_backtest_engine.py  # backtest/engine.py — 시뮬레이션
```

**테스트 원칙:**
- 모든 전략의 `get_weights()`는 `합계=1, 음수없음, 올바른인덱스`를 보장
- `_calculate_mdd` 벡터화 구현이 루프 구현과 동일한 결과를 생성하는지 검증
- 리스크 상태는 임시 경로에 영속화하여 격리 (`tmp_path` fixture)

---

## 설계 원칙

1. **전략 인터페이스 단일화** — `get_weights(prices)` 하나만 구현하면 백테스트·라이브 모두 동작
2. **브로커 추상화** — 모드만 바꾸면 페이퍼/모의/실전 자동 전환
3. **리스크 우선** — 모든 거래 전 `RiskGuard.check()` 통과 필요
4. **방어적 현금 배분** — 데이터 부족·전략 오류 시 항상 현금성 ETF로 폴백
5. **DRY** — 중복 로직은 기반 클래스 또는 공유 유틸리티로 통합

---

## 의존성 그래프

```
config.py ←── strategy/*.py
             ├── broker/*.py
             ├── portfolio/rebalancer.py
             ├── backtest/engine.py
             └── risk/guard.py

utils/market.py ←── portfolio/rebalancer.py

strategy/base.py ←── strategy/dual_momentum.py
                 ←── strategy/vaa.py
                 ←── strategy/risk_parity.py
                 ←── strategy/multi_strategy.py
                 ←── strategy/factor_momentum.py
```
