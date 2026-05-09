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

## Scope Approval

On 2026-05-09, after a manual read-only API smoke attempt, the owner approved
preparing the token/update path in advance. This scope is limited to API smoke
clients that prove connectivity and response contracts. It does not authorize
trading clients, account/balance reads, order placement, paper trading loops,
live trading, or token persistence.

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

`--allow-network` without `--run-network` only marks which probes are eligible.
To run the read-only smoke clients, use:

```bash
.venv/bin/python -m zurini.cli api-smoke \
  --allow-network \
  --run-network \
  --output reports/api-smoke-network.json
```

The network mode runs only these probes:

1. Telegram `getMe` bot-token check.
2. Gemini minimal request.
3. Korea Investment Securities paper token/auth check.
4. Korea Investment Securities market-data quote contract check.

KIS paper access tokens are held in memory for the current smoke run only. They
must not be printed, written to reports, or persisted as files.

Korea Investment Securities live account endpoints stay disabled until a later
owner-approved live-trading phase.
