# KIS Domestic Stock Automated Trading Domain Pack

This pack is for Korean domestic-stock automated-trading projects that use
Korea Investment & Securities (KIS) market-data or trading APIs.

## Preserved User Request

```text
국내주식 KIS 기반 자동매매 프로젝트용 AI_AUTO 도메인팩을 만들어줘.
  목표는 모듈 분리 리팩터링이고, 실거래 API 호출/credential 유출/전략 의미 변경은 금지.
  Repomix는 읽기 전용 context pack, Aider는 제한된 파일 수정 보조로만 허용.
  paper/live 분리, 중복 주문 방지, kill switch, 최대 손실 제한 검증 체크리스트를 포함해줘.
  AI_AUTO 템플릿에 재사용 가능한 domain pack 형태로 추가해줘.
```

## Select This Pack

Select this pack when local evidence shows all of the following:

- the project targets Korean domestic equities;
- KIS APIs are used or planned;
- automated trading, paper trading, or no-order dry-run operation is in scope;
- module separation, broker-boundary hardening, or strategy validation is being
  planned.

## Reject This Pack

Reject this pack when the project is not financial/trading software, does not
touch Korean domestic equities, or uses unrelated broker/platform APIs.

## Defer This Pack

Defer when the broker, market, credential boundary, or execution mode
(`no-order`, `paper`, `live`) is unknown.

## Files

- `AGENTS.patch.md`: candidate agent guidance.
- `WORKFLOW.md`: candidate workflow guidance.
- `risk-boundaries.md`: fail-closed trading/API boundaries.
- `interview.md`: onboarding and rebuild questions.
- `verify-patterns.md`: project-adaptable verification examples.
- `review-checklist.md`: review gate checklist.
- `split-rules.json`: conservative split proposal hints.

## Non-Goals

- This pack does not enable live trading.
- This pack does not define profitable strategy parameters.
- This pack does not store credentials, account numbers, private endpoints, or
  production access rules.
- This pack does not authorize real orders, account reads, balance reads, or
  live broker actions.

## Risk Tier

- Low: read-only docs, static analysis, no-order local fixtures.
- Standard: read-only market-data smoke checks with explicit network gates.
- Strict: paper/live execution boundaries, order construction, risk controls,
  credential handling, strategy-meaning changes.
- Fail-closed: missing credentials contract, missing market-data freshness,
  missing warm-up/source data, duplicate order risk, disabled kill switch, max
  loss control not evidenced.
