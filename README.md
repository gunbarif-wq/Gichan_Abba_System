# Gichan Abba System

국내 주식 자동매매 시스템

## 개요

완전히 확장 가능한 구조로 설계된 주식 자동매매 시스템입니다.

- **Paper 모드**: 가상 계좌로 즉시 테스트 가능
- **Mock 모드**: KIS 모의투자 API (구현 대기)
- **Live 모드**: KIS 실계좌 (기본 비활성화)
- **Vision 학습**: 3분봉 차트 이미지 분석 (구현 대기)

## 핵심 원칙

1. **AI는 분석만 한다** - 직접 주문하지 않음
2. **Risk Guard는 우회 불가** - 모든 주문의 최종 게이트키퍼
3. **Council만 매수 후보를 만든다** - 점수 종합 및 추천
4. **실제 주문은 Order Manager만 생성** - 중앙 집중식 관리
5. **실제 주문 전송은 Broker Interface만 수행** - 느슨한 결합
6. **모든 거래는 기록된다** - 감시 및 복기

## 설치 및 실행

### 사전 요구사항

- Python 3.11+
- pip

### 설치

```bash
# 의존성 설치
pip install -r requirements.txt
```

### 실행

#### Paper 모드 (권장)

```bash
# 가상 계좌로 매수→매도→손익 리포트 실행
python run.py
```

**예상 출력**:
```
[2024-01-15 14:30:00] Gichan Abba System - Paper Mode Demo
...
✓ 주문 생성: [order_id]
✓ 포지션 생성: 005930 삼성전자
✓ 최종 리포트

📊 매매 결과
═══════════════════════════
종목: 삼성전자 (005930)
모드: paper

매입 정보
───────────────────────────
수량: 10주
평균가: 70,000원
총금액: 700,000원

매도 정보
───────────────────────────
수량: 10주
평균가: 72,000원
총금액: 720,000원

손익 계산
───────────────────────────
매수금액:        700,000원
매도금액:        720,000원
매수수수료:        105원
매도수수료:        108원
거래세:        1,296원
───────────────────────────
순손익금:       18,491원
순손익률:         2.64%
═══════════════════════════
```

## 구조

```
/Gichan_Abba_System
├── shared/              # 공통 스키마 및 상수
├── config/              # 설정 파일
├── account/             # 계좌 관리
├── trade/               # 주문 및 브로커
├── risk/                # 리스크 관리
├── ops/                 # 운영 (시간, 상태)
├── strategy/            # 신호 생성
├── agents/              # 분석 에이전트
├── control/             # 텔레그램 명령 (구현 대기)
├── report/              # 손익 리포트
├── datasets/            # 학습 데이터
├── models/              # AI 모델
├── storage/             # 실행 데이터 및 로그
└── tests/               # 테스트
```

## 모드 설정

### Paper 모드 (`config/paper_config.yaml`)

```yaml
mode: paper
live_trading: false
initial_cash: 10000000  # 1천만원
commission_rate: 0.00015  # 0.015%
tax_rate: 0.0018  # 0.18%
pyramiding_enabled: false
time_check_enabled: false  # 시간 제한 없음
```

### Mock 모드 (`config/mock_config.yaml`)

KIS 모의투자 API 연동 준비
- 실제 API 호출은 TODO
- 나중에 API 키 설정 후 구현 가능

### Live 모드 (`config/live_config.yaml`)

KIS 실계좌 API 연동
- **기본 비활성화** (`live_trading: false`)
- `live_trading: true`일 때만 실주문 가능
- 2단계 확인 필요

## 거래 흐름

```
거래 신호 생성
    ↓
신호 검증 (Signal Engine)
    ↓
시장 시간 확인 (Market Clock)
    ↓
리스크 검사 (Risk Guard) ← 최종 게이트키퍼
    ↓
주문 생성 (Order Manager)
    ↓
브로커 전송 (Broker Interface)
    ↓
체결 확인 (Paper/Mock/Live)
    ↓
포지션 업데이트 (Position Manager)
    ↓
계좌 반영 (Account Manager)
    ↓
손익 계산 (PnL Calculator)
    ↓
리포트 생성 (Reporter)
```

## 에이전트

### 1. Vision Agent (구현 대기)
- 3분봉 차트 이미지 분석
- PyTorch 기반 CNN 모델
- 돌파/풀백 패턴 인식

### 2. Supply Agent (구현 대기)
- 외인/기관/프로그램 매매 분석
- 거래량 및 거래대금 분석
- 수급 강도 판정

### 3. News Agent (구현 대기)
- 뉴스/공시 분석
- 외신 직역
- 테마 지속성 판단

### 4. Critic Agent (구현 대기)
- 다른 에이전트의 분석 검토
- 위험 신호 감지
- 감점 적용

### 5. Council (구현 대기)
- 모든 에이전트 점수 종합
- 매수 후보 선정
- 신뢰도 판정

### 6. Ops Agent (구현 대기)
- 시장 시간 확인
- 시스템 상태 모니터링
- 토큰/서버/데이터 지연 확인

### 7. Command Agent (구현 대기)
- 텔레그램 명령 수신
- 수동 매수/매도 처리
- 권한 검사

### 8. Evolution Coach (구현 대기)
- 매매 결과 복기
- 개선안 생성
- 모델 학습 제안

## 리스크 관리

### Risk Guard (최종 게이트키퍼)

모든 주문은 다음을 통과해야 함:

1. **실계좌 거래 확인**
   - `live_trading: false` → 실계좌 거래 불가

2. **긴급 중단 확인**
   - 긴급 중단 시 신규 매수 중단

3. **UNKNOWN 상태 확인**
   - UNKNOWN 상태 주문이 있으면 신규 주문 불가

4. **중복 주문 방지**
   - 같은 종목 중복 매수 금지
   - 같은 종목 중복 매도 금지

5. **자금 검사**
   - 주문가능금액 확인
   - 수수료 포함 검사

6. **비중 제한**
   - 종목당 최대 20% 비중
   - 최소 20% 현금 비율 유지
   - 최대 5개 종목

## 설정

### `config/risk_rules.yaml`

```yaml
max_position_ratio_per_stock: 0.20  # 종목당 최대 비중
min_cash_ratio: 0.20                # 최소 현금 비율
max_positions: 5                    # 최대 보유 종목
max_daily_loss_ratio: 0.03          # 최대 일일 손실률
allow_live_trading: false           # 실계좌 거래 활성화
new_buy_allowed: true               # 신규 매수 허용
emergency_stop: false               # 긴급 중단
```

### `config/agent_weights.yaml`

```yaml
agent_weights:
  vision_agent: 0.30      # 30%
  supply_agent: 0.25      # 25%
  news_agent: 0.20        # 20%
  critic_agent: 0.25      # 25%

thresholds:
  buy_recommendation: 70.0    # 매수 추천 점수
  strong_buy: 80.0            # 강한 매수
```

## 테스트

```bash
# 모든 테스트 실행
pytest tests/ -v

# 특정 테스트만 실행
pytest tests/test_paper_broker.py -v

# 커버리지 포함
pytest tests/ --cov=. --cov-report=html
```

### 주요 테스트

- `test_paper_broker.py`: Paper 브로커 매수/매도 체결
- `test_risk_guard.py`: 리스크 검사
- `test_order_manager.py`: 주문 관리
- `test_position_manager.py`: 포지션 관리
- `test_pnl_calculator.py`: 손익 계산

## 로그

- **위치**: `storage/logs/gichan_abba.log`
- **레벨**: INFO (조정 가능)
- **포맷**: `[시간] 모듈 - 레벨 - 메시지`

## 다음 단계

### 단기 (Week 1-2)

- [ ] Mock 모드 KIS API 연동
- [ ] 텔레그램 명령어 구현
- [ ] 기본 에이전트 스켈레톤 완성

### 중기 (Week 3-4)

- [ ] Vision 모델 학습
- [ ] Supply/News Agent 구현
- [ ] Live 모드 테스트

### 장기 (Month 2+)

- [ ] Evolution Coach 구현
- [ ] NXT 거래소 지원
- [ ] 성능 최적화

## 주의사항

⚠️ **반드시 숙지하세요**

1. **Paper 모드로 충분히 테스트한 후 Mock 모드 사용**
2. **Mock 모드에서 검증 후 Live 모드 진입**
3. **Live 모드는 절대 자동화된 매수 추천 받지 않음** (수동 승인만)
4. **API 키는 환경 변수로 관리** (`.env` 파일 사용)
5. **모든 거래는 기록되므로 정기적으로 복기**

## 라이선스

MIT License

## 지원

문제가 있거나 개선 제안이 있으면:

1. 로그 파일 확인: `storage/logs/gichan_abba.log`
2. 코드 리뷰
3. 단위 테스트 실행

## 참고

- **설정**: `config/` 디렉토리 참고
- **스키마**: `shared/schemas.py` 참고
- **상수**: `shared/constants.py` 참고
- **에러**: `shared/errors.py` 참고
