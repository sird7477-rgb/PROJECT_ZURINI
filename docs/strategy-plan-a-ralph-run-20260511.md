# Plan A Ralph Run: 2026-05-11

## Objective

Validate the preferred Plan A portfolio:

- day `C-IDMOM-D3-U1-S1`: at least two concurrent KRW `10,000,000` slots;
- swing `F-SUP-U1-S1`: up to five concurrent KRW `10,000,000` slots;
- shared-slot portfolio with KRW `70,000,000` start equity and KRW `100,000`
  weekly external contribution;
- base and 2x transaction-cost checks;
- exact-bar continuity audit.

## Key Finding

The earlier variable-slot day failures were over-expansion stress results, not
clean fixed two-slot failures. With `--max-open-positions 2`, the current day
strategy passes the 2x-cost standalone gate.

## Results

| Run | Trades | Net PnL | Max Drawdown | Continuity | Verdict |
| --- | ---: | ---: | ---: | --- | --- |
| Day exact two-slot 2x cost | 127 | 891223.5614224796360000000000 | -0.03262582970855858591154413330 | passed; 254 checked, 0 failed, 0 missing | Pass |
| Plan A portfolio base cost | 155 | 3113880.235951499359875000000 | -0.02041719768857436654081391471 | passed; 310 checked, 0 failed, 0 missing | Pass |
| Plan A portfolio 2x cost | 155 | 797425.2753183808390000000000 | -0.02391565633831140121910706709 | passed; 310 checked, 0 failed, 0 missing | Pass |

## Artifacts

- `reports/phase2/strategy-ralph/plan-a/c-idmom-d3-u1s1-70m-exact2slot-cost2x-observed/report.json`
- `reports/phase2/strategy-ralph/plan-a/portfolio-idmom-d3-fsup-u1s1-daycap2-swingcap5-70m-base-observed/report.json`
- `reports/phase2/strategy-ralph/plan-a/portfolio-idmom-d3-fsup-u1s1-daycap2-swingcap5-70m-cost2x-observed/report.json`

## Operating Interpretation

Plan A is the preferred validated portfolio inside the current historical
OHLCV and conservative slippage-assumption boundary. Plan B remains the
conservative fallback if field slippage, fill quality, continuity, or drawdown
deviates from the assumptions used here.

The current validated ceiling is KRW `70,000,000`. Capital above this boundary
stays idle/reserve until a new or diversified strategy passes the same
strategy-level and portfolio-level gates.
