# 개발 로드맵

Korean ETF Quant Trading Bot의 향후 개발 계획입니다.

---

## 현재 버전 (v1.x) — 완료된 기능

- [x] 6종 전략 구현 (KR GEM, DualMomentum, VAA-KR, RiskParity, FactorMomentum, MultiStrategy)
- [x] KR GEM 한국·미국 멀티에셋 모멘텀 전략 + 기본 전략 채택 (SECTOR 자산군 추가)
- [x] S&P500 200일 MA 기반 시장 국면 감지
- [x] KIS API 연동 (실전·모의, OAuth2 자동 갱신)
- [x] 페이퍼 트레이딩 (수수료·슬리피지·틱 시뮬레이션)
- [x] Walk-Forward 백테스트 검증
- [x] Telegram 명령 인터페이스
- [x] FastAPI 웹 대시보드 + 비밀번호 토큰 인증(`DASHBOARD_SECRET`) + 수동 리밸런싱 버튼
- [x] KIS 토큰 캐시 보안 강화 (원자적 쓰기·`chmod 0600`·Content-Type 검증)
- [x] 리스크 관리 (MDD, 일간손실, 연속손실, 출금 방어)
- [x] 유닛 테스트 78개 (strategy, rebalancer, metrics, risk_guard, backtest_engine, utils)
- [x] kr_gem 전략 테스트 (기본 전략 채택과 동시에 누락됐던 갭 해소)
- [x] CI 파이프라인 (GitHub Actions, Python 3.10/3.11 매트릭스)
- [x] KIS 재시도 로직 통합 (`_request_with_retry`)
- [x] KRX 호가단위 유틸리티 분리 (`utils/market.py`)
- [x] BaseStrategy 공통 유틸리티 (`_all_cash`, `normalize_weights`)
- [x] MDD 기간 계산 벡터화

---

## 단기 계획 (v1.x 패치)

### 테스트 커버리지 확장
- [x] `portfolio/rebalancer.py` 주문 계획 로직 단위 테스트
- [x] CI 파이프라인 설정 (GitHub Actions)
- [ ] `broker/paper_broker.py` 시뮬레이션 정확도 테스트
- [ ] `data/fetcher.py` 캐시 만료·fallback 테스트

### 코드 품질
- [ ] 브로커 프로토콜 클래스 도입 (`typing.Protocol`로 `get_balance`, `order_buy`, `order_sell` 정의)
- [ ] `config.py` 사이드이펙트 제거 (디렉터리 생성을 lazy init으로 이동)
- [ ] 전략 파라미터 민감도 분석 스크립트 추가
- [ ] `factor_engine.py` 미완성 Phase 4 로직 완성 및 통합 테스트

### 운영 안정성
- [ ] KIS API 일일 요청 횟수 모니터링 추가
- [ ] 환경변수 검증 로직 (`run_bot.py` 시작 시 필수 키 확인)
- [ ] 로그 레벨 정책 표준화 (ERROR/WARNING/INFO/DEBUG 기준 명문화)

---

## 중기 계획 (v2.0)

### 멀티 계좌 지원
- [ ] 계좌별 전략 독립 운용 (ISA / 일반 / 연금)
- [ ] 계좌 간 자산 배분 최적화
- [ ] 통합 리스크 뷰 (계좌 합산 MDD 감시)

### 신호 고도화
- [ ] 모멘텀 지표 다양화: 12-1 외에 3-1, 6-1 모멘텀 앙상블
- [ ] 매크로 팩터 완성: 한국은행 기준금리 RSS/API 연동
- [ ] 변동성 레짐 감지: VIX 연계 (TIGER VIX 선물 활용)
- [ ] 크로스 자산 상관관계 모니터링 (급등 상관 시 방어 전환)

### 실행 품질 개선
- [ ] 분할 매수: 대형 주문을 TWAP으로 분할 (가격 충격 최소화)
- [ ] 지정가/시장가 혼용: 유동성 낮은 ETF는 지정가
- [ ] 호가창 분석: 매수/매도 스프레드 반영한 슬리피지 추정

### 대시보드 고도화
- [ ] 실시간 WebSocket 포트폴리오 업데이트
- [ ] 전략별 기여도 분해 (Attribution Analysis)
- [ ] 백테스트 결과 웹에서 인터랙티브 차트 시각화
- [ ] HTTPS 지원 (Let's Encrypt 자동 인증서)

---

## 장기 계획 (v3.0)

### 전략 연구
- [ ] 머신러닝 신호: 시장 국면 분류에 XGBoost/LightGBM 적용
- [ ] 대안 데이터 통합: 공매도 잔고, 외국인 순매수 흐름
- [ ] 옵션 활용: 커버드콜 전략으로 수익 향상 (TIGER 커버드콜)

### 플랫폼 확장
- [ ] 해외 브로커 지원: Interactive Brokers API 추가
- [ ] 암호화폐 ETF 통합: 비트코인 현물 ETF (국내 상장 시)
- [ ] 사용자 친화 GUI: Streamlit 기반 전략 파라미터 튜닝 툴

### 리스크 관리 고도화
- [ ] Expected Shortfall (CVaR) 기반 리스크 예산
- [ ] 스트레스 테스트: 2008·2020·2022 시나리오 실시간 시뮬레이션
- [ ] 유동성 리스크: ETF 거래량 기반 최대 주문 가능 금액 제약

---

## 기여 우선순위

현재 가장 도움이 필요한 항목:

1. **테스트** — `portfolio/rebalancer.py` 단위 테스트 작성
2. **문서** — 전략 수리 공식 및 파라미터 설명 보강
3. **버그 리포트** — 실전 운용 중 발견한 엣지 케이스 이슈 등록
4. **전략 아이디어** — 한국 시장에 적합한 새로운 모멘텀/팩터 제안

기여 방법은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참조하세요.
