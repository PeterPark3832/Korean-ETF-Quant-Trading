# Korean ETF Quant Trading Bot

한국 ETF 기반 퀀트 자동매매 시스템 — 멀티 전략 포트폴리오 + 실시간 리스크 관리

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-53%20passed-brightgreen.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **6종 전략** | **KR GEM(기본)**, DualMomentum, VAA-KR, RiskParity, FactorMomentum, MultiStrategy |
| **시장 국면 감지** | S&P500 200일 MA 기반 강세/약세장 자동 전환 |
| **리스크 관리** | MDD 12%/18% 경보·하드스탑, 일간 손실 3% 한도 |
| **KIS API 연동** | 한국투자증권 실전·모의 투자, OAuth2 토큰 자동 갱신 |
| **페이퍼 트레이딩** | 수수료·슬리피지·틱 가격 시뮬레이션 |
| **백테스트** | 2015년~현재, Walk-Forward 검증 지원 |
| **Telegram 봇** | 실시간 알림 + `/status`, `/rebalance`, `/halt`, `/resume` 등 명령 |
| **Web 대시보드** | FastAPI 기반 실시간 포트폴리오 현황 + 수동 리밸런싱 (port 8080, 비밀번호 로그인) |

---

## 빠른 시작

### 1. 환경 설정

```bash
git clone https://github.com/peterpark3832/korean-etf-quant-trading.git
cd Korean-ETF-Quant-Trading
pip install -r requirements.txt
cp .env.example .env
# .env 파일에 KIS API 키 입력
```

### 2. 페이퍼 트레이딩 (즉시 시작)

```bash
# 기본 전략(KR GEM)으로 페이퍼 트레이딩 시작
python run_bot.py --mode paper

# 전략 지정도 가능
python run_bot.py --strategy multi --mode paper

# 즉시 리밸런싱 시뮬레이션 (주문 없이 확인)
python run_bot.py --now --dry_run
```

### 3. 백테스트

```bash
# 전체 전략 비교 (2015~현재)
python run_backtest.py

# 단일 전략 + Walk-Forward 검증
python run_backtest.py --strategy multi --walk_forward
```

### 4. 실전 매매

```bash
# KIS API 키 설정 후 (기본 전략 KR GEM)
python run_bot.py --mode kis_real

# 다른 전략으로 실전 운용
python run_bot.py --strategy multi --mode kis_real
```

---

## 아키텍처

```
Korean-ETF-Quant-Trading/
├── strategy/          # 투자 전략 (BaseStrategy + 5개 구현체)
│   ├── base.py        #   추상 기반 클래스 + 공통 유틸리티
│   ├── dual_momentum.py
│   ├── vaa.py         #   VAA 한국형 (단기채 방어)
│   ├── risk_parity.py #   역변동성 + 변동성 타겟팅
│   ├── multi_strategy.py  # 시장 국면별 전략 배합
│   └── factor_engine.py   # 매크로 팩터 + 변동성 조정
├── broker/            # 거래소 연동 추상화
│   ├── kis_client.py  #   KIS REST API + Rate Limiter
│   ├── kis_order.py   #   주문 실행 + 계좌 관리
│   └── paper_broker.py    # 로컬 페이퍼 트레이딩
├── portfolio/         # 리밸런싱 실행기
├── risk/              # MDD·일간손실·연속손실 감시
├── backtest/          # 백테스트 엔진 + 성과 지표 + Walk-Forward
├── data/              # pykrx/FinanceDataReader + 캐시
├── utils/             # 공유 유틸리티 (KRX 호가단위 등)
├── reports/           # 성과 리포트 + 차트
├── tests/             # pytest 유닛 테스트 (53개)
├── scheduler.py       # APScheduler 오케스트레이션
├── dashboard.py       # FastAPI 웹 대시보드
├── notifier.py        # Telegram 알림
└── config.py          # 전역 설정 + ETF 유니버스
```

자세한 아키텍처 설명은 [ARCHITECTURE.md](ARCHITECTURE.md)를 참조하세요.

---

## 전략 설명

### KR GEM (한국·미국 멀티에셋 모멘텀) — 기본 전략
KOSPI200·미국S&P500·나스닥100·금·반도체 5개 위험자산의 **블렌드 모멘텀(3·6·12개월 평균)** 상위 3개를 동일비중으로 편입합니다(상대 모멘텀). 각 슬롯의 모멘텀이 현금성 ETF(단기채권)보다 낮으면 그 슬롯을 **국고채 3년**으로 대체합니다(절대 모멘텀 → 약세장 채권 도피). 월간 리밸런싱. ETF 가격만 사용하므로 재무 미래참조·생존자 편향이 없습니다.
백테스트(2015~현재, 참고용): CAGR ≈ +17.0% / MDD ≈ -21.6% / Sharpe ≈ 0.86

### DualMomentum (게리 안토나치)
자산군별 **상대 모멘텀**(상위 N개 선택) + **절대 모멘텀**(현금 대비 양수 여부) 필터를 조합합니다. 음수 모멘텀 자산은 자동으로 현금성 ETF로 대체됩니다.

### VAA-KR (한국형 Vigilant Asset Allocation)
카나리아 자산(KODEX200, TIGER S&P500)이 음수 신호를 보내면 즉시 전액 단기채/KOFR로 전환합니다. 원본 VAA의 장기채 방어 자산을 단기채로 교체하여 **2022년 금리인상 구간 손실을 최소화**합니다.

### RiskParity-VT (변동성 타겟팅)
각 자산이 포트폴리오 총 리스크에 동등하게 기여하도록 배분(역변동성 또는 ERC)합니다. **목표 연 변동성 10%**에 맞게 전체 비중을 스케일링합니다.

### MultiStrategy (시장 국면 배합)

| 국면 | DualMomentum | RiskParity | VAA |
|------|:---:|:---:|:---:|
| 강세장 (200일 MA 위) | 50% | 30% | 20% |
| 약세장 (200일 MA 아래) | 25% | 15% | 60% |

Phase 4 매크로 팩터(금리·환율) 조정 및 변동성 타겟팅이 추가 적용됩니다.

---

## ETF 유니버스

| 자산군 | 대표 ETF | 비중 상한 |
|--------|---------|---------|
| 한국주식 | KODEX 200, TIGER 코스피, KODEX 200TR | 40% |
| 해외주식 | TIGER S&P500, KODEX 나스닥100TR, KODEX 유럽 | 50% |
| 채권 | KODEX 국고채3년, TIGER 국고채10년, KODEX 미국채10년 | 60% |
| 원자재 | KODEX 골드, TIGER 원유, KODEX 은 | 20% |
| 섹터 | KODEX 반도체 (KR GEM 모멘텀 슬롯) | 15% |
| 현금성 | KODEX KOFR액티브, TIGER 단기통안채 | 40% |

---

## 리스크 관리

```
MDD ≥ 8%    → 포지션 축소 경보
MDD ≥ 12%   → Warn (텔레그램 알림)
MDD ≥ 18%   → Hard Stop (전액 현금화, 자동 거래 중단)
일간 손실 ≥ 3% → 당일 거래 중단
연속 손실 5일  → 포지션 축소
자산 급감 15%  → 출금 의심, 수동 확인 요청
```

---

## Telegram 명령어

| 명령어 | 설명 |
|--------|------|
| `/status` | 현재 포트폴리오 + 리스크 상태 |
| `/rebalance` | 다음 리밸런싱 일정 확인 |
| `/rebalance_now` | 즉시 리밸런싱 실행 |
| `/report` | 성과 리포트 |
| `/halt` | 거래 중단 |
| `/resume` | 거래 재개 |
| `/resetmdd` | MDD 기준점 재설정 |

---

## 환경 변수 (.env)

```bash
# KIS API (필수 — 실전/모의 모두 동일 설정)
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=12345678-01   # 계좌번호-상품코드
KIS_MODE=paper               # paper | kis_paper | kis_real

# Telegram (선택)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Web 대시보드 (선택 — 미설정 시 시작 로그에 임시 비밀번호 출력)
DASHBOARD_SECRET=your_dashboard_password
```

> **대시보드 로그인**: `http://서버IP:8080` 접속 시 비밀번호 입력 → 토큰 발급(httpOnly).
> 미인증 상태에서는 API(`/api/status` 등)가 401을 반환합니다.
> 8080 포트는 방화벽에서 본인 IP로만 제한하는 것을 권장합니다.

---

## 실행 옵션

```bash
# 봇 실행 (라이브 스케줄러)
python run_bot.py [--strategy STRATEGY] [--mode MODE]

# 즉시 리밸런싱
python run_bot.py --now [--dry_run]

# 포트폴리오 현황 확인
python run_bot.py --status

# 거래 재개
python run_bot.py --resume

# 백테스트
python run_backtest.py [--strategy all|kr_gem|dual_momentum|vaa|risk_parity]
                       [--start 2015-01-01] [--end 2025-12-31]
                       [--walk_forward] [--refresh]
```

---

## 테스트

```bash
# 전체 유닛 테스트 (53개)
python -m pytest tests/ -v

# 특정 모듈만 테스트
python -m pytest tests/test_strategies.py -v
python -m pytest tests/test_metrics.py -v
python -m pytest tests/test_risk_guard.py -v

# KIS/Broker 연동 테스트 (API 키 필요)
python test_connection.py --mode paper
python test_connection.py --mode kis_paper
```

---

## 배포 (Linux systemd)

```bash
sudo nano /etc/systemd/system/etf-bot.service
```

```ini
[Unit]
Description=ETF Quant Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/Korean-ETF-Quant-Trading
ExecStart=/usr/bin/python3 run_bot.py --mode kis_real --strategy kr_gem
Restart=always
RestartSec=30
StandardOutput=append:/home/ubuntu/Korean-ETF-Quant-Trading/logs/service.log
StandardError=append:/home/ubuntu/Korean-ETF-Quant-Trading/logs/service.log
Environment=PYTHONUNBUFFERED=1
Environment=DASHBOARD_SECRET=your_dashboard_password

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable etf-bot
sudo systemctl start etf-bot
```

---

## 개발 로드맵

단기/중기/장기 개발 계획은 [ROADMAP.md](ROADMAP.md)를 참조하세요.

---

## 기여

[CONTRIBUTING.md](CONTRIBUTING.md)를 참조하세요.

---

## 주의사항

- 이 소프트웨어는 교육 및 연구 목적으로 제공됩니다.
- 실제 투자 손실에 대해 개발자는 책임을 지지 않습니다.
- 실전 사용 전 충분한 페이퍼 트레이딩 테스트를 권장합니다.
- KIS API 일일 요청 한도에 유의하세요.

---

## 라이선스

MIT License
