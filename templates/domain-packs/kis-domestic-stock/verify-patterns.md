# KIS Domestic Stock Verification Patterns

These are examples. Convert them into real project-local commands before
claiming completion.

## Static Boundary Checks

- Search for real credential literals and account numbers.
- Search for direct KIS order/account/balance calls outside broker adapters.
- Search for live endpoint usage in no-order or paper paths.

## No-Order Smoke

Example shape:

```bash
python -m <project>.cli field-run --no-order --cycle-limit 1
```

Evidence should show:

- order hard block enabled;
- no order/account/balance calls;
- market-data source freshness;
- warm-up/history readiness;
- per-symbol degradation flags.

## Paper/Live Separation

Example assertions:

- no-order mode cannot construct an order transmission request;
- paper mode cannot use live profile;
- live mode requires explicit confirmation;
- missing kill switch blocks startup.

## Duplicate Order Prevention

Example scenarios:

- same signal emitted twice;
- API timeout during order submit;
- retry after uncertain response;
- process restart with pending intent.

Expected result: one durable order intent or fail-closed state, never duplicate
transmission.

## Maximum Loss

Example scenarios:

- daily loss limit breached;
- per-symbol stop breached;
- stale PnL/account evidence;
- missing market price for open position.

Expected result: new entries blocked and risk state recorded.
