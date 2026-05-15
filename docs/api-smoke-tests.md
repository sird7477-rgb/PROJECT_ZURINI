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

The generic `api-smoke` network mode runs only these probes:

1. Telegram `getMe` bot-token check.
2. Gemini minimal request.
3. Korea Investment Securities paper token/auth check.
4. Korea Investment Securities paper market-data quote contract check.

KIS access tokens are held in memory for the current smoke run only. They
must not be printed, written to reports, or persisted as files.

KIS response diagnostics classify early integration failures into operator
flags:

- `api_auth_error`: token/auth failed or unauthorized response.
- `api_command_error`: endpoint, TR ID, symbol, or parameter contract appears
  wrong.
- `api_schema_mismatch`: HTTP response succeeded but required read-only fields
  are missing.
- `api_rate_limit_risk`: rate-limit response observed.
- `api_timeout`: timeout or network failure.

These flags are safe to feed into the field monitor because they contain only
sanitized status metadata, not credentials or raw tokens.

## Read-Only Universe Smoke

Before a full field dry-run, collect KIS stock master files and refresh the
local DB / market-wide candidate symbol source. Then collect the 60 completed
trading days of KIS read-only daily bars required by the prior-only field
universe, build the universe from that KIS source root, then run read-only KIS
quote smoke against the generated symbol list:

The stock master refresh is a hard prerequisite for universe data collection.
It must record collection time, source files, market classification, symbol
count, and applied exclusions. Missing, stale, malformed, or unrefreshed stock
master input blocks KIS daily-bar collection and universe selection.

```bash
.venv/bin/python -m zurini.cli kis-stock-master-refresh \
  --allow-network \
  --run-network \
  --report-output reports/dry-run/kis-stock-master.json \
  --symbol-list-output reports/dry-run/kis-source-symbols.txt
```

```bash
.venv/bin/python -m zurini.cli kis-daily-bars \
  --allow-network \
  --run-network \
  --symbol-list reports/dry-run/kis-source-symbols.txt \
  --start-date <oldest-required-trading-date> \
  --end-date <expected-prior-trading-date> \
  --endpoint-profile prod \
  --confirm-prod-readonly \
  --rate-profile prod \
  --min-trading-days 60 \
  --output-root data/raw/kis/daily-bars \
  --report-output reports/dry-run/kis-daily-bars.json
```

The KIS daily-bar command consumes `output2` from the domestic
period-price response. Required fields are `stck_bsop_date`, `stck_oprc`,
`stck_hgpr`, `stck_lwpr`, `stck_clpr`, `acml_vol`, and `acml_tr_pbmn`. A symbol
with missing required fields, duplicate daily dates, fewer than 60 distinct
daily rows, or a latest row older than the expected prior trading day fails
closed. The command writes local CSVs shaped as
`date,time,open,high,low,close,volume,value` under
`data/raw/kis/daily-bars/YYYYMM/`.

After each market close, collect the new expected prior trading day from KIS,
verify the rolling 60-trading-day window remains complete, then clear the
oldest retained prior date. Refresh the KIS stock master and local DB /
candidate symbol source before this daily-bar maintenance step. Do not delete
the old date before the new KIS data is accepted.

```bash
.venv/bin/python -m zurini.cli build-daily-field-universe \
  --target-date 2026-05-12 \
  --root data/raw/kis/daily-bars \
  --source kis-daily-bars \
  --latest-months 4 \
  --kis-symbol-list-output reports/dry-run/field-universe-kis-symbols.txt \
  --output reports/dry-run/field-universe-2026-05-12.json
```

For a small offline contract check, a manual explicit symbol list is also
allowed:

```bash
.venv/bin/python -m zurini.cli kis-readonly-universe \
  --symbol 005930 \
  --symbol 000660 \
  --output reports/dry-run/kis-readonly-universe-plan.json
```

The offline command normalizes symbols and writes the intended universe plan
without network calls. When explicitly approved for network smoke:

The resulting KIS market-data artifact is a freshness-bound input. Downstream
`field-dry-run-monitor` runs default to `--market-data-max-age-seconds 120`.
For historical replay of a saved artifact, pass `--now` that matches the
artifact's intended observation time; for field runs, do not use an old artifact
as if it were current market data.

```bash
.venv/bin/python -m zurini.cli kis-readonly-universe \
  --allow-network \
  --run-network \
  --symbol-list reports/dry-run/field-universe-kis-symbols.txt \
  --endpoint-profile prod \
  --confirm-prod-readonly \
  --rate-profile prod \
  --include-quote-depth \
  --output reports/dry-run/kis-readonly-universe.json
```

Use this single artifact as the live field-monitoring market-data input when
depth is required. Do not join a separate `kis-readonly-depth` artifact into
operating `field-dry-run-monitor` evidence; depth-only reports remain
diagnostic. With `--include-quote-depth`, a degraded network result exits
non-zero because missing bid/ask pressure or a stale price/depth pair is not a
valid operating input.

The network command calls only KIS token and domestic stock quote
endpoints. It includes symbols with successful quote contracts and excludes
symbols with a sanitized reason such as schema mismatch, command error, auth
error, timeout, or rate-limit risk. `--endpoint-profile prod` uses
`KIS_LIVE_APP_KEY` and `KIS_LIVE_APP_SECRET` against the production read-only
market-data endpoint and is never the CLI default. It requires
`--confirm-prod-readonly` as an explicit
operator acknowledgement that the call remains inside the approved dry-run
infrastructure scope. This path is limited to token issuance plus quote reads;
it does not authorize order placement, account reads, balance reads, paper/live
execution, or real-fill measurement. `--endpoint-profile paper` uses the
mock-server endpoint and `KIS_PAPER_*` credentials, and remains the default
network endpoint profile unless `prod` is explicitly requested. This endpoint selection is separate from
`--rate-profile`, which controls only pacing. Field dry-run uses the `prod`
pacing profile by default because dry-run promotion targets the field
environment, not the stricter mock server. The `prod` rate profile uses the
lower internal field budget, currently 12 requests/second, while treating 20
requests/second as the provider ceiling only. The `paper` rate profile uses a
slower 0.5 second interval for mock-server checks. If
`api_rate_limit_risk` appears while using `prod`, treat it as an account,
endpoint, or credential-scope mismatch until the KIS response is classified; do
not make production polling slower by default from a mock-server observation.
This is a connectivity and universe construction smoke artifact, not a final
production universe ranking model.

Separate limiter: token issue/refresh must not be retried in a tight loop. The
official KIS sample README documents token reissue as limited to once per
minute, so auth retry logic must use a separate one-minute cooldown. The CLI
stores this local cooldown in `.omx/state/kis-auth-cooldown.json`; records are
keyed by endpoint profile (`paper` or `prod`) and contain only status metadata,
not app keys, tokens, or account data. Delete that file only when an operator has
confirmed the previous auth failure was transient and an immediate retry is
intentional.

Korea Investment Securities live account endpoints stay disabled until a later
owner-approved live-trading phase.
