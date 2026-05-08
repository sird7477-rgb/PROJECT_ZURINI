# PROJECT_ZURINI 개발 워크플로우

이 저장소는 자동매매 시스템을 전략 단계부터 새로 구현하기 위한 개발
저장소다. `(old)/` 디렉터리는 과거 이력 원본으로 보존하되, 1차 개발의
트레이딩 조건, 시퀀스, 리스크 제어, 아키텍처 판단은 이 파일들을 출발
기준으로 삼는다.

즉 1차 개발의 출발 기준은 `(old)/` 문서다.

단, 이는 절대 기준이 아니다. 진행 중 테스트 결과, DB 스키마 설계, 구현 제약,
또는 사용자의 새 판단으로 더 나은 방향이 확인되면 `docs/`에 이유를 남기고
방향을 조정할 수 있다.

## 현재 목표

1차 개발의 도착지는 실거래가 아니라 **재현 가능한 로컬 백테스트**다.

기준:

- 실행 위치: 개인 로컬 PC
- 언어/테스트: Python + pytest
- DB: Docker Compose Postgres
- 데이터: deterministic dummy 1분봉 데이터
- 핵심 산출물: 1분봉 DB 스키마/계약, validator, dummy data loader, 단순 전략,
  백테스트 실행 흐름, 최소 리포트
- 전략/시퀀스/리스크 초기 기준: `(old)/` 문서에서 추출

실제 과거 1분봉 데이터 취득, broker API, paper trading, live trading, 서버
배포는 1차 범위 밖이다.

## 작업 루프

1. 요청 범위를 phase-1 목표 안에서 고정한다.
2. 변경 전 `AGENTS.md`, 이 문서, `docs/phase-1-development.md`,
   `docs/phase-1-prd.md`, `docs/phase-1-test-spec.md`, `scripts/verify.sh`를
   확인한다.
3. `(old)/`는 원본 그대로 보존하고, 필요한 트레이딩 조건/시퀀스/리스크
   기준은 새 문서나 코드로 추출한다.
4. 작은 diff로 수정한다.
5. 완료 전 diff를 확인한다.
6. `./scripts/verify.sh`를 실행한다.
7. 실패하면 수정 후 다시 검증한다.
8. 커밋 후보 전 `./scripts/review-gate.sh`를 실행한다.
9. 리뷰어가 제한되면 degraded 상태와 누락 리뷰어를 보고한다.
10. 검증과 review gate 증거가 있을 때만 커밋/푸시한다.

## 1차 개발 완료 기준

Ralph 또는 자동 실행 루프가 1차 개발을 완료했다고 말하려면 다음 증거가
필요하다.

- Docker Compose Postgres가 로컬에서 실행 가능하다.
- 표준 1분봉 스키마가 생성된다.
- dummy data generator가 같은 seed로 같은 데이터를 만든다.
- validator가 정상 dummy data를 통과시키고 잘못된 data를 거부한다.
- dummy 1분봉 데이터가 Postgres에 적재된다.
- 단순 전략 하나 이상이 백테스트 프레임워크에서 실행된다.
- 백테스트 결과가 최소 지표를 출력한다.
- `./scripts/verify.sh` 하나로 관련 검증을 재현할 수 있다.
- 실거래 주문, broker API 호출, 계좌 정보, secret 파일이 없다.

전략 수익성은 1차 완료 기준이 아니다. 1차의 목적은 전략을 반복 검증할 수
있는 기반을 만드는 것이다.

## 엄격한 것과 유연한 것

엄격하게 지킬 것:

- 실거래 금지
- broker API와 계좌 정보 금지
- 로컬 Docker Compose Postgres 기준
- 1분봉 데이터 계약 존재
- deterministic dummy data
- schema/data validator
- 재현 가능한 백테스트 실행
- `./scripts/verify.sh` 통과

유연하게 둘 것:

- 전략 조건
- 종목 선정 필터
- 손절/익절 수치
- 수수료/슬리피지 가정
- 리포트 상세 지표
- 내부 모듈/파일 구조
- dummy data 패턴

## 필수 검증

작업 완료 전 반드시 실행한다.

```bash
./scripts/verify.sh
```

현재 온보딩 단계의 `verify.sh`는 다음을 확인한다.

- automation baseline 파일 상태
- review summary fixture 테스트
- phase-1 문서 존재와 핵심 anchor
- `(old)/`가 reference archive로만 정의되어 있는지
- shell script 실행 권한

향후 phase-1 코드가 추가되면 같은 명령에 pytest, Docker Compose Postgres
스키마 생성, dummy data 적재, 백테스트 smoke test를 포함해야 한다.

## 리뷰 게이트

커밋 후보 전 반드시 실행한다.

```bash
./scripts/review-gate.sh
```

이 명령은 `./scripts/verify.sh`를 먼저 실행한 뒤 Claude/Gemini/Codex fallback
리뷰와 verdict 요약을 실행한다. `proceed_degraded`는 진행 가능한 결과지만,
완료 보고에 degraded trust level과 누락 리뷰어 상태를 포함해야 한다.

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
