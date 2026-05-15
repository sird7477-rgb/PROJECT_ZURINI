# Incident Ops For Dry-run And Field-test

Use this layer when an agent, Ralph loop, QA run, or field-test session monitors
an operational workflow and may need to respond to anomalies before the user can
inspect every log line.

## Purpose

Incident Ops is a policy layer, not a replacement for Ralph. Ralph owns the
goal-completion loop. Incident Ops owns anomaly monitoring, evidence capture,
safe automatic response, escalation boundaries, and status reporting during
dry-run, field-test, and operational rehearsal phases.

## Phases

- `dry-run`: verify logic, sandbox/read-only API behavior, generated artifacts,
  schedulers, and failure handling without accepted external side effects.
- `field-test`: run in the real execution shape, including operator UI and
  approved read-only external paths, while blocking trading, payment, deletion,
  production writes, and other external mutations.
- `operational-rehearsal`: run long enough to test monitoring, checkpointing,
  restart behavior, incident logs, and periodic status reporting before
  production or promotion claims.

## Action Classes

- `observe`: collect logs, screenshots, DOM state, process status, route,
  viewport, network status, and local health evidence.
- `diagnose`: classify the failure, inspect recent diffs, compare sandbox and
  approved real-network evidence, or retry one read-only probe.
- `safe_recover`: restart a local service, clear local cache, refresh a UI
  session, or repeat a local smoke check when reversible.
- `guarded_recover`: refresh a sandbox token, regenerate a fixture, or restore a
  test-only setting once when project policy allows it.
- `ask_required`: credential changes, production DB writes, deployment changes,
  repeated external API calls, or other sensitive actions.
- `blocked`: orders, order cancellation, position changes, payments, destructive
  operations, or unknown side-effectful actions during dry-run/field-test.

Default posture:

- `observe`, `diagnose`, and `safe_recover` may run automatically.
- `guarded_recover` may run once only when the project policy says so.
- `ask_required` stops for user approval with evidence.
- `blocked` must not run in dry-run/field-test.

## Incident Log Contract

Every anomaly response must leave an incident log entry. The log may be
markdown, JSON, or a project-native status artifact, but it must include:

- timestamp and phase
- monitored command or workflow
- trigger, symptom, severity, and impact
- action class and decision
- exact automatic action taken, if any
- pre-action evidence and post-action evidence
- sandbox evidence and approved real-network evidence when external APIs are
  involved
- UI route, viewport, screenshot path, console status, network status, and
  operator flow step when UI field-test is involved
- next approval boundary and remaining risk
- periodic reporting cadence used for the run

Do not log secrets, raw tokens, personal data, account numbers, or full payloads
that are not needed for diagnosis. Redact before writing durable artifacts.

## Periodic Status Reporting

Long-running dry-runs and field tests must report monitoring status on a
project-specific cadence. Do not hardcode one global interval.

Recommended policy fields:

```yaml
incident_ops:
  heartbeat_interval_seconds: 900
  quiet_interval_seconds: 1800
  incident_escalation_interval_seconds: 300
```

- `heartbeat_interval_seconds`: normal "still monitoring" report cadence.
- `quiet_interval_seconds`: maximum silence when no incidents occur.
- `incident_escalation_interval_seconds`: update cadence while an incident is
  active or recovery is being verified.

The report should include current phase, monitored surface, last successful
check, active incident count, automatic actions taken, blocked/ask-required
actions, and next planned check. During UI field-test, include current route,
viewport, console/network status, and whether the operator can continue the
workflow.

## UI Field-test Evidence

When field-test includes UI, the incident log must capture operator-facing
evidence, not just backend success:

- route or URL
- viewport
- screenshot or browser-smoke artifact
- console error status
- network request status for the relevant flow
- loading/empty/error/success state
- operator workflow step and whether the next action is possible
- mobile/desktop evidence when both are required

UI refresh, local session restart, or another reversible UI-only recovery may be
automatic. Data mutation, credential change, production deploy, or repeated
external calls still require approval.

## Ralph Integration

Use Incident Ops as a helper policy inside Ralph:

```text
$ralph Run the field test to completion.
If anomalies appear, use Incident Ops: observe/diagnose/safe_recover can run
automatically, guarded_recover can run once if configured, and ask_required or
blocked actions must stop with evidence.
```

Ralph completion must not rely on passing tests alone when an incident occurred.
The final report should cite the incident log, periodic status reports, recovery
evidence, and any skipped or blocked action.
