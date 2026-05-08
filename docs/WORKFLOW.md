# PROJECT_ZURINI 개발 워크플로우

이 저장소는 한국 시장 자동매매 시스템의 전략/아키텍처 문서와 Codex/OMX
자동화 베이스라인을 관리한다. 현재 기준 산출물은 문서이며, 실주문 가능한
트레이딩 엔진은 아직 저장소에 없다.

## 현재 기준

- 프로젝트 목적: 자동매매 전략, 리스크 제어, 실행/백테스트 아키텍처를
  보존하고 점진적으로 구현 가능한 형태로 정리한다.
- 핵심 설계: Universal Quant Core, 공통 `MarketState`, `SignalIntent`,
  Execution & Friction Layer, Optuna 최적화 흐름.
- 핵심 리스크 제어: 글로벌 베타 스로틀링, 비동기 블랙리스트 heartbeat,
  역변동성 사이징, 상관관계 cap, 일일 손실 circuit breaker, MDD kill switch,
  manual panic, IOC 비상 탈출.
- 현재 non-goal: 실거래 주문, API credential 관리, 배포 하드닝, 신규 의존성
  도입.

## 작업 루프

1. 요청 범위를 현재 문서/자동화 baseline 안에서 고정한다.
2. 변경 전 관련 문서와 스크립트를 확인한다.
3. 작은 diff로 수정한다.
4. 완료 전 diff를 확인한다.
5. `./scripts/verify.sh`를 실행한다.
6. 실패하면 수정 후 다시 검증한다.
7. 커밋 후보 전 `./scripts/review-gate.sh`를 실행한다.
8. 리뷰어가 제한되면 degraded 상태와 누락 리뷰어를 보고한다.
9. 검증과 review gate 증거가 있을 때만 커밋/푸시한다.

## 필수 검증

작업 완료 전 반드시 실행한다.

```bash
./scripts/verify.sh
```

현재 `verify.sh`는 다음을 확인한다.

- review summary fixture 테스트
- automation baseline 파일 상태
- PROJECT_ZURINI 필수 문서 존재 여부
- 자동매매 전략/아키텍처 핵심 anchor 텍스트
- `AGENTS.md`와 이 워크플로우 문서의 프로젝트 기준 문구

## 리뷰 게이트

커밋 후보 전 반드시 실행한다.

```bash
./scripts/review-gate.sh
```

이 명령은 `./scripts/verify.sh`를 먼저 실행한 뒤 Claude/Gemini/Codex fallback
리뷰와 verdict 요약을 실행한다. `proceed_degraded`는 진행 가능한 결과지만,
완료 보고에 degraded trust level과 누락 리뷰어 상태를 포함해야 한다.

## 허용 범위

허용:

- 프로젝트 온보딩 문서 정리
- 자동매매 전략 문서의 구조화 및 보존
- 워크플로우 명확화
- 검증 스크립트 개선
- 좁은 범위의 automation 안정성 수정

새 계획 없이 금지:

- 실거래 주문 코드
- broker API credential 처리
- 인증/권한/보안 민감 변경
- 데이터 모델 또는 마이그레이션 변경
- 신규 의존성 또는 외부 서비스 도입
- 대규모 구조 변경
- 리스크 제어 약화

## 커밋 규칙

커밋은 아래 조건을 만족한 뒤에만 진행한다.

- diff를 검토했다.
- `./scripts/verify.sh`가 통과했다.
- `./scripts/review-gate.sh`가 통과했다.
- 남은 warning을 기록했다.
- 커밋 메시지가 Lore protocol을 따른다.
- 사용자가 커밋을 명시적으로 요청했다.

## 운영 명령

자동화 진단:

```bash
./scripts/automation-doctor.sh
```

프로젝트 검증:

```bash
./scripts/verify.sh
```

리뷰 게이트:

```bash
./scripts/review-gate.sh
```
