# Observability Completion Pack

Use this pack during onboarding only when the project must be monitored,
debugged in operation, audited, or supported after handoff. If the project is a
short-lived local tool or prototype, record observability as a non-goal beyond
basic error messages.

## Onboarding Questions

Clarify these before implementing observability work:

- operational owner and support workflow
- health checks, readiness checks, and failure signals
- log format, log level, retention, and redaction expectations
- metrics, traces, audit events, or error reporting tools already in use
- user-visible and operator-visible error handling requirements
- incident diagnosis questions the system should answer
- whether dry-run/field-test anomaly handling should use
  `docs/INCIDENT_OPS.md`
- heartbeat, quiet, and active-incident status reporting intervals
- what must never be logged or exported

## Workflow Additions

When observability is in scope, add these steps to the project workflow:

1. define the operational questions the system must answer
2. add health or readiness checks before adding heavier telemetry
3. keep logs structured enough to diagnose failures and redacted enough to avoid
   leaking secrets or personal data
4. cover expected error paths with useful, non-sensitive messages
5. verify observability output with a local smoke check when practical
6. for dry-run/field-test monitoring, write incident logs with action class,
   decision, pre/post evidence, next approval boundary, and periodic status
   report cadence
7. include the relevant log, health, metric, trace, incident, or audit evidence in the
   completion report

## Verification Patterns

Adapt `scripts/verify.sh` to the project stack. Prefer real project commands
over placeholders.

Common checks:

```bash
curl -fsS http://localhost:5000/health
pytest
docker compose logs --tail=100
```

Do not require external monitoring accounts in local verification unless the
project already depends on them. Local health and log smoke checks are often
enough for early-stage projects.

## Completion Criteria

Observability work is complete only when:

- health or readiness behavior is documented when the project runs as a service
- logs or errors help diagnose the target failure without leaking secrets
- expected failure paths produce useful operator or user feedback
- external observability services are optional unless explicitly required
- `./scripts/verify.sh` and `./scripts/review-gate.sh` pass, or any degraded
  trust state is reported explicitly

## Non-Goals

Do not add full monitoring stacks, dashboards, tracing systems, alerting
pipelines, or log aggregation unless the project outcome requires it or the user
explicitly requests it.
