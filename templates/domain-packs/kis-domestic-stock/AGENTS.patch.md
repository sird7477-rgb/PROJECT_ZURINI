# Candidate AGENTS.md Guidance: KIS Domestic Stock

Apply only after confirming this project uses KIS for Korean domestic-stock
automation.

## Domain Boundary

Default to no-order or read-only operation. Do not add or enable real broker
orders, account reads, balance reads, live fills, or paper/live execution
without explicit project approval and a separate plan.

Never store credentials, account numbers, app keys, app secrets, tokens, or
private broker endpoints in the repository. Use environment variable names and
placeholders only.

## Module Separation Goal

When refactoring, preserve strategy meaning and separate these concerns:

- broker/KIS adapter
- auth/token handling
- market-data collection
- source freshness and warm-up validation
- strategy signal generation
- risk controls
- order intent construction
- order transmission adapter
- paper/live mode boundary
- observability/status artifacts

Refactors must keep behavior locked by tests before moving code.

## Tool Boundary

Repomix may be used only as read-only context packaging.

Aider may be used only as a constrained file-edit assistant with an explicit
write scope. Do not allow it to broaden strategy meaning, broker permissions, or
credential handling.

## Trading Safety Rules

- Keep paper and live modes separate in config, code paths, artifacts, and
  tests.
- Duplicate-order prevention must be explicit before any order-capable mode.
- A kill switch must be visible, testable, and fail-closed.
- Maximum loss limits must be enforced and covered by tests before any
  order-capable rehearsal.
- Missing or stale required operating input must block downstream strategy or
  order decisions.
