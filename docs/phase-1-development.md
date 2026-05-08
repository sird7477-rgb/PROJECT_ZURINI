# 1차 개발 기준

## 목적

1차 개발은 자동매매 시스템의 실거래 구현이 아니라, 전략을 반복 검증할 수
있는 로컬 백테스트 기반을 만든다.

도착지:

- 로컬 PC에서 실행 가능
- Docker Compose Postgres 사용
- 1분봉 데이터 스키마와 계약 정의
- deterministic dummy data 생성
- validator로 데이터 정합성 검사
- dummy data를 DB에 적재
- 단순 전략을 백테스트
- 최소 리포트를 출력
- `./scripts/verify.sh`로 재현
- `(old)/` 문서의 트레이딩 조건, 시퀀스, 리스크 기준을 초기 구현 기준으로 사용

## 비목표

1차 개발에서 하지 않는다.

- 실거래 주문
- broker API 연동
- API key, 계좌번호, secret 처리
- paper trading
- 운영 서버 배포
- 실제 과거 1분봉 데이터 취득
- 수익성 검증을 완료 목표로 삼기

실제 과거 1분봉 데이터는 2차 데이터 ingestion 단계에서 다룬다. 1차의 dummy
data는 시장 수익성을 보증하지 않고, 스키마와 백테스트 프레임워크의 동작을
보증한다.

## 과거 문서 사용 원칙

`(old)/`는 편집하지 않는 과거 이력 원본이다. 다만 1차 개발의 트레이딩 조건,
시스템 시퀀스, 리스크 제어, 아키텍처 판단은 이 파일들을 기준으로 시작한다.

이 기준을 둔 이유는 1차 구현이 빈 템플릿에서 출발하지 않도록 하기 위해서다.
과거 문서는 최종 정답은 아니지만, 이미 정리된 전략 조건과 운영 흐름을
초기 가설로 삼으면 Ralph가 백테스트 기반을 만들 때 도착지와 테스트 데이터를
더 구체적으로 잡을 수 있다.

초기 구현 기준으로 읽을 항목:

- 전략 조건과 진입/청산 룰
- 단타/스윙/하락장 우회 같은 전략 구분
- 글로벌 베타 스로틀링과 kill switch
- 1분봉/시장 상태 처리 시퀀스
- DB atomic commit, execution/friction layer 같은 아키텍처 방향

old 문서끼리 충돌하거나 현재 1차 범위를 넘는 항목은 바로 구현하지 말고,
`docs/`에 해석과 보류 사유를 남긴 뒤 진행한다.

이 기준은 출발점이지 절대 조건이 아니다. 구현 중 테스트, 데이터 계약, DB
스키마, 또는 사용자 판단에 의해 방향 조정이 필요하면 현재 문서와 테스트
기준을 먼저 갱신하고 진행한다.

## 데이터 계약 원칙

dummy data와 실제 과거 1분봉 데이터는 같은 DB 스키마와 validator를 통과해야
한다.

초기 1분봉 bar 계약은 다음 필드를 기준으로 설계한다.

```text
symbol
timestamp
open
high
low
close
volume
value
source
ingested_at
```

필수 규칙:

- `symbol + timestamp`는 unique
- timestamp 기준은 KST 장중 1분봉으로 명시
- `open`, `high`, `low`, `close`는 null 불가
- `high >= low`
- `high >= open`, `high >= close`
- `low <= open`, `low <= close`
- `volume >= 0`
- `value >= 0`
- 동일 seed의 dummy data는 항상 같은 결과
- 데이터는 `symbol`, `timestamp` 기준으로 정렬 가능해야 함

향후 실제 데이터 단계에서 추가 검토할 항목:

- 수정주가와 raw price 분리
- 거래정지/무거래 표현
- corporate action 처리
- 데이터 출처별 versioning
- 대량 적재 성능과 partitioning

## 백테스트 기준

1차 백테스트는 단순 전략으로 충분하다. 전략의 성과보다 프레임워크의
재현성이 중요하다.

최소 요구:

- dummy 1분봉 데이터를 읽는다.
- 전략이 buy/sell/hold 같은 신호를 만든다.
- 체결/포지션/현금 흐름을 기록한다.
- 수수료와 슬리피지는 임시 기본값으로 주입 가능해야 한다.
- 최소 리포트에 다음 필드가 포함된다.

```text
trade_count
gross_pnl
net_pnl
max_drawdown
start_equity
end_equity
```

## 검증 기준

1차 코드가 추가되면 `./scripts/verify.sh`는 최소한 다음을 실행해야 한다.

```bash
pytest
docker compose up -d db
```

그리고 다음 smoke를 포함해야 한다.

- Postgres healthcheck
- 스키마 생성
- validator positive/negative test
- deterministic dummy data test
- dummy data insert row count test
- 백테스트 smoke test
- 금지선 검사: 실거래/API/secret 관련 파일이나 호출 없음

현재 온보딩 단계에서는 위 구현이 아직 없으므로, `verify.sh`는 이 문서와 운영
기준이 존재하는지 먼저 검증한다.
