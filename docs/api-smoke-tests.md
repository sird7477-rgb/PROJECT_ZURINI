# API Smoke Tests

API smoke tests are read-only connectivity and response-contract checks. They
are not trading features.

Safety boundary:

- Do not inspect or print `.env` values.
- Do not store API keys, tokens, account numbers, passwords, or secrets.
- Do not call live order, paper order, balance mutation, or account-action
  endpoints.
- Korea Investment Securities remains the future broker/API smoke target.
- The two-year historical 1-minute raw acquisition exception uses Daishin
  Securities CYBOS and is outside this API smoke command.

## Offline Plan

The current command writes an offline plan from environment-variable presence
only. It does not make network calls:

```bash
.venv/bin/python -m zurini.cli api-smoke \
  --output reports/api-smoke-plan.json
```

The JSON report contains probe names, required environment-variable names,
missing-variable names, and mode. It must not contain raw credential values.

## Network Contract Mode

When the owner explicitly wants real connectivity checks, use:

```bash
.venv/bin/python -m zurini.cli api-smoke \
  --allow-network \
  --output reports/api-smoke-plan.json
```

At this stage `--allow-network` only marks which probes are eligible. Actual
HTTP clients should be added later behind read-only tests in this order:

1. Telegram message send to the configured chat.
2. Gemini minimal request.
3. Korea Investment Securities paper token/auth check.
4. Korea Investment Securities market-data quote/minute-bar contract check.

Korea Investment Securities live account endpoints stay disabled until a later
owner-approved live-trading phase.
