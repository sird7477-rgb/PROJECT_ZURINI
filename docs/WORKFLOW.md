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

업로드된 API 관련 자료는 `references/api/`에 격납한다. 이 자료들은 실제
과거 1분봉 데이터 연동 단계에서 참고하되, 구현이 의존하는 계약은 먼저
`docs/`, `config/`, 코드, 테스트로 승격해 기록한다.
API 키, 토큰, 계좌번호, 비밀번호, 인증서 비밀번호 등 실제 자격증명 값은
저장소에 기록하지 않는다. 필요한 이름만 `.env.example`과
`references/api/credentials-inventory.md`에 placeholder로 남긴다.

## 과거 데이터 수집

1차는 deterministic dummy data를 기본 검증 fixture로 유지하고, `sample/`
CSV는 실제 파일 형식이 DB 스키마에 맞게 변환될 수 있는지 확인하는 용도로
쓴다.

2차는 실제 알고리즘 검증 단계이므로 종목 1분봉만으로는 부족하다. 지수 기반
리스크 필터를 검증하려면 KOSPI/KOSDAQ 같은 지수 1분봉과 종목 메타데이터가
필요하다. stage/promoted 데이터와 이후 API 경계는 한국투자증권 기준을
유지한다. 단, 한국 증권사별 과거 데이터 제공 범위 제약 때문에 2년치 과거
1분봉 raw 취득은 예외적으로 대신증권 CYBOS를 사용한다.
`sample/collect_yearly/`의 대신증권 CYBOS 수집기는 이 unpromoted raw intake
예외 도구로 보존한다.

이 수집기는 1차 백테스트 범위를 실거래/API 연동으로 확장하는 것이 아니며,
주문 실행, 계좌 동작, 실거래 판단, broker secret 저장을 포함하지 않는다.
CYBOS 호출은 unpromoted 종목/지수/메타 시장데이터 raw 수집으로 제한한다.
raw 파일은 intake gate 통과 전까지 백테스트 정답 데이터나 promoted stage
데이터로 보지 않는다.

수집 산출물은 다음 구조를 기준으로 한다.

- `minute-bars/YYYYMM/<code>.csv`
- `index-bars/YYYYMM/<code>.csv`
- `symbols/*.csv`
- `manifests/*.jsonl`

raw 수집 파일은 곧바로 백테스트 정답 데이터로 보지 않는다. 2차 데이터셋으로
승격하기 전에 결측 분, 중복 `symbol + timestamp`, timezone 변환, OHLCV
무결성, 지수/종목 시간 정렬을 별도 품질검사로 통과해야 한다.

수집 후 첫 검사는 DB에 넣지 않는 CSV 스캔으로 한다.

```bash
.venv/bin/python -m zurini.cli scan-csv --root data/raw/daishin/minute-bars --output reports/csv-scan.json
```

2차 실제 데이터는 `docs/phase-2-real-data-runbook.md`의 intake gate를 먼저
통과해야 한다. 이 gate는 CSV 스캔 결과에 acceptance threshold를 붙여
`accepted` 또는 `rejected`를 명시한다. 실제 2년치 데이터가 준비되기 전까지는
이 문서와 명령을 유지보수하는 것이 다음 단계 대기 작업이다.

작은 smoke 검증은 일부 파일만 기존 백테스트 경로에 통과시킨다.

```bash
.venv/bin/python -m zurini.cli backtest-csv --root data/raw/daishin/minute-bars --limit-files 10 --output-dir reports/csv-smoke
```

API 연결은 `docs/api-smoke-tests.md`의 순서로 별도 smoke test에서만 다룬다.
현재 기본 명령은 환경변수 이름과 누락 여부만 보고하며 실제 네트워크 호출,
실주문, 계좌 동작, secret 출력은 하지 않는다.

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

## 자동화 기반 병합 정책

기존 프로젝트 업데이트는 재설치가 아니라 비교 후 병합이다. 최신 AI_AUTO
템플릿은 참고 원본으로만 사용하고, PROJECT_ZURINI의 `AGENTS.md`,
`docs/WORKFLOW.md`, `scripts/verify.sh`는 프로젝트 지침을 우선한다.

병합 순서:

1. 현재 프로젝트 루트와 git 상태를 확인한다.
2. 기존 `AGENTS.md`, `docs/WORKFLOW.md`, `scripts/verify.sh`,
   `scripts/automation-doctor.sh`, `scripts/review-gate.sh`를 먼저 읽는다.
3. `/root/workspace/ai-lab/templates/automation-base`의 최신 템플릿과 비교한다.
4. 프로젝트 지침, 보안/secret 정책, 데이터 경계, 커밋/검증 규칙은 유지한다.
5. 빠진 reusable 자동화 문서와 helper script만 추가한다.
6. 충돌나는 규칙은 프로젝트 지침을 우선한다.
7. `./scripts/automation-doctor.sh`, `./scripts/verify.sh`, 필요 시
   `./scripts/review-gate.sh`로 검증한다.

현재 유지하는 reusable 자동화 문서:

- `docs/AUTOMATION_OPERATING_POLICY.md`
- `docs/AI_MODEL_ROUTING.md`
- `docs/SESSION_QUALITY_PLAN.md`
- `docs/DATA_COMPLETION.md`
- `docs/SECURITY_COMPLETION.md`
- `docs/DEPLOYMENT_COMPLETION.md`
- `docs/PERFORMANCE_COMPLETION.md`
- `docs/OBSERVABILITY_COMPLETION.md`
- `docs/UI_COMPLETION.md`

완료팩 적용 판단:

- 유지: `DATA_COMPLETION.md`
  - 이유: 1분봉 DB 스키마, CSV intake, raw/stage 승격, 백테스트 데이터 검증이
    프로젝트 핵심이다.
- 유지: `SECURITY_COMPLETION.md`
  - 이유: API 키, 계좌, 토큰, 인증서 등 secret 경계가 프로젝트 품질 기준에
    직접 포함된다.
- 유지/인터뷰 대상: `DEPLOYMENT_COMPLETION.md`
  - 이유: 필드 테스트 성공 후 실전 전환 가능성이 있으므로, 실행 환경,
    시작/중지/헬스체크, 롤백, secret 주입 방식은 초기에 기준을 잡는다.
- 유지/인터뷰 대상: `PERFORMANCE_COMPLETION.md`
  - 이유: 2년치 1분봉, 다종목 백테스트, 향후 실시간 처리 경로는 CPU/메모리,
    처리시간, 회귀 기준을 요구한다. 단, 성능 튜닝은 정확성 검증 이후에 한다.
- 유지/인터뷰 대상: `OBSERVABILITY_COMPLETION.md`
  - 이유: 필드/실전 단계에서는 주문 판단 근거, 데이터 품질, 장애 원인,
    secret 비노출 로그, 헬스체크 evidence가 필요하다.
- 유지/제안 후 승인: `UI_COMPLETION.md`
  - 이유: 운영자는 사용자가 직접이며, 직관적인 대시보드형 운영 콘솔이 필요하다.
    AI가 1차 UI 제안을 작성하고 사용자가 컨펌한 뒤 구현한다.
  - 1차 UI 예상 구성: 기본 조작 버튼, 로그창, 매매기록, 계좌현황(보유종목,
    수량, 수익률 등).
  - 1차 허용 버튼: 시작, 중지, 일시정지, 재개, 상태 새로고침, 로그 열기,
    리포트 열기.
  - 확인 필요 버튼: 모의매매 시작, 전략 파라미터 변경, 데이터 재검증 실행.
  - 초기 금지/잠금 버튼: 실전매매 시작, 실전 주문 전송, 계좌/키 변경,
    자동 청산. 실전 주문 관련 버튼은 표시하더라도 잠금 상태여야 하며, 사용자
    명시 승인 전에는 활성화하지 않는다.
- 도메인팩: Odoo 등 프로젝트 외 도메인팩은 `AGENTS.md`나 이 문서에 병합하지
  않는다. 존재하더라도 `.omx/domain-packs/` 아래 ignored 참고자료로만 둔다.

현재 유지하는 reusable helper script:

- `scripts/archive-omx-artifacts.sh`
- `scripts/record-feedback.sh`
- `scripts/record-project-memory.sh`
- `scripts/write-session-checkpoint.sh`
