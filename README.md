# ETF 퀀트봇

한국 ETF 유니버스 기반 퀀트 자동매매 봇입니다.  
한국투자증권(KIS) API를 사용해 매월 첫 영업일에 자동 리밸런싱합니다.

## 주요 기능

- **4가지 전략**: Dual Momentum / VAA / Risk Parity / Multi(멀티 전략)
- **시장 국면 감지**: S&P500 200일 이동평균 기준 강세/약세 자동 전환 (Multi 전략)
- **리스크 관리**: MDD 한도 초과 시 자동 포지션 축소 / 거래 중단
- **텔레그램 알림**: 리밸런싱 결과, 리스크 경고, 일일 리포트
- **백테스트**: 2015년부터 Walk-Forward 분석 지원

## 전략 설명

| 전략 | 설명 | 특징 |
|---|---|---|
| `dual_momentum` | 듀얼 모멘텀 (Antonacci) | 상대 + 절대 모멘텀 |
| `vaa` | Vigilant Asset Allocation | 방어적, 현금 비중 높음 |
| `risk_parity` | 리스크 패리티 | 변동성 기반 균등 배분 |
| `multi` | 멀티 전략 **(권장)** | 시장 국면별 3전략 혼합 |

## ETF 유니버스

| 자산군 | 종목 |
|---|---|
| 한국주식 | KODEX 200, TIGER 코스피, KODEX 200TR |
| 해외주식 | TIGER 미국S&P500, KODEX 미국나스닥100TR, KODEX 유럽선진국MSCI 등 |
| 채권 | KODEX 국고채3년, TIGER 국고채10년, KODEX 미국채10년선물 등 |
| 원자재 | KODEX 골드선물, TIGER 원유선물, KODEX 은선물 |
| 현금성 | KODEX KOFR금리액티브, TIGER 단기통안채 |

## 설치 및 실행

### 1. 환경 설정

```bash
git clone https://github.com/your-id/etf-quant-bot.git
cd etf-quant-bot

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. API 키 설정

```bash
cp .env.example .env
# .env 파일을 열어 KIS API 키, 계좌번호, 텔레그램 정보 입력
```

KIS API 키 발급: https://apiportal.koreainvestment.com

### 3. 봇 실행

```bash
# 스케줄러 시작 (24시간 상시 운용)
python run_bot.py --mode kis_real --strategy multi

# 즉시 리밸런싱 (드라이런)
python run_bot.py --mode kis_real --strategy multi --now --dry_run

# 현재 포트폴리오 상태 확인
python run_bot.py --status
```

### 4. 서버 24시간 운용 (Linux systemd)

```bash
sudo nano /etc/systemd/system/etf-bot.service
```

```ini
[Unit]
Description=ETF Quant Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/etf-quant-bot
ExecStart=/root/etf-quant-bot/venv/bin/python run_bot.py --mode kis_real --strategy multi
Restart=always
RestartSec=30
StandardOutput=append:/root/etf-quant-bot/logs/service.log
StandardError=append:/root/etf-quant-bot/logs/service.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable etf-bot
sudo systemctl start etf-bot
```

## 백테스트

```bash
python run_backtest.py --strategy multi
python run_backtest.py --strategy all   # 전략 비교
```

## 프로젝트 구조

```
etf-quant-bot/
├── strategy/
│   ├── dual_momentum.py     # 듀얼 모멘텀
│   ├── vaa.py               # VAA
│   ├── risk_parity.py       # 리스크 패리티
│   └── multi_strategy.py    # 멀티 전략 + 국면 감지
├── broker/
│   ├── kis_client.py        # KIS API 클라이언트
│   ├── kis_order.py         # 주문 / 잔고 관리
│   └── paper_broker.py      # 로컬 모의 브로커
├── portfolio/
│   └── rebalancer.py        # 리밸런싱 실행기
├── risk/
│   └── guard.py             # 리스크 감시 (MDD, 손실 한도)
├── backtest/
│   ├── engine.py            # 백테스트 엔진
│   └── walk_forward.py      # Walk-Forward 분석
├── data/
│   └── fetcher.py           # pykrx 가격 데이터 수집
├── reports/
│   └── plotter.py           # 백테스트 차트
├── config.py                # 전역 설정
├── scheduler.py             # APScheduler 자동매매
├── notifier.py              # 텔레그램 알림
├── run_bot.py               # 실행 진입점
└── run_backtest.py          # 백테스트 진입점
```

## 주의사항

- 이 봇은 투자 손실을 보장하지 않습니다. 실전 투자 전 충분한 모의투자 검증을 권장합니다.
- KIS API 일일 요청 한도에 유의하세요.
- ISA 중개형 계좌 사용 시 정상 동작이 확인되어 있습니다.

## 라이선스

MIT License
