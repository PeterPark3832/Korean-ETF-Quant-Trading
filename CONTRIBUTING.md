# 기여 가이드

Korean ETF Quant Trading Bot에 기여해주셔서 감사합니다.

---

## 개발 환경 설정

```bash
git clone https://github.com/peterpark3832/korean-etf-quant-trading.git
cd Korean-ETF-Quant-Trading
pip install -r requirements.txt
cp .env.example .env
```

---

## 브랜치 전략

| 브랜치 | 용도 |
|--------|------|
| `main` | 안정 릴리스 |
| `develop` | 통합 개발 |
| `feature/이름` | 신규 기능 |
| `fix/이름` | 버그 수정 |
| `refactor/이름` | 리팩토링 |

```bash
# 기능 개발 시작
git checkout -b feature/my-strategy develop
```

---

## 코드 스타일

- **타입 힌트**: 모든 public 메서드에 타입 어노테이션 필수
- **docstring**: 한 줄 요약 (Why가 명확하지 않은 경우만 작성)
- **전략 구현 시**: `BaseStrategy` 상속, `get_weights()` 반환값은 합계=1 보장
- **로거**: `print` 금지, `loguru.logger` 사용

```python
# 좋은 예
from loguru import logger
logger.info(f"[MyStrategy] 국면={regime}")

# 나쁜 예
print(f"국면: {regime}")
```

---

## 테스트 작성 규칙

모든 PR에는 새로운 로직에 대한 단위 테스트가 포함되어야 합니다.

```bash
# 테스트 실행
python -m pytest tests/ -v

# 특정 파일만
python -m pytest tests/test_strategies.py -v
```

### 전략 테스트 체크리스트

새 전략을 추가할 때 다음 항목을 검증하세요:

```python
def assert_valid_weights(weights, prices):
    assert (weights >= 0).all()           # 음수 없음
    assert abs(weights.sum() - 1.0) < 1e-6  # 합계 = 1
    assert set(weights.index).issubset(set(prices.columns))  # 유효한 티커
```

---

## PR 체크리스트

PR 제출 전 확인:

- [ ] `python -m pytest tests/ -v` 전체 통과
- [ ] 새 기능에 대한 단위 테스트 포함
- [ ] `strategy/` 변경 시 `test_strategies.py` 업데이트
- [ ] 공개 API 변경 시 ARCHITECTURE.md 업데이트
- [ ] `requirements.txt` 신규 의존성 추가 시 이유 명시

---

## 이슈 리포트

버그 리포트에는 다음을 포함해주세요:

1. 파이썬 버전: `python --version`
2. 운영 모드: `paper` / `kis_paper` / `kis_real`
3. 에러 로그 전문 (`logs/bot_YYYY-MM.log`)
4. 재현 방법

---

## 새 전략 추가 방법

1. `strategy/my_strategy.py` 파일 생성
2. `BaseStrategy` 상속, `get_weights()` 구현
3. `strategy/__init__.py`의 `create_strategy()` 팩토리에 등록
4. `tests/test_strategies.py`에 테스트 클래스 추가
5. `config.py`에 필요한 파라미터 상수 추가

```python
# strategy/my_strategy.py
from strategy.base import BaseStrategy

class MyStrategy(BaseStrategy):
    name = "MyStrategy"

    def get_weights(self, prices: pd.DataFrame) -> pd.Series:
        # ... 로직 구현
        return self.normalize_weights(weights)
```
