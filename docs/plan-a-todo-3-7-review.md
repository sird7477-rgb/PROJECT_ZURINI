# Plan A TODO 3-7 Review

Date: 2026-05-15

Scope: post-market Ralph pass for TODO 3-7. This review does not enable live
orders, account reads, balance reads, credential persistence, or strategy
meaning changes.

## Decision Summary

| TODO | Decision | Reason |
| --- | --- | --- |
| 3. 장중 수집 구조 개선 | Pre-split architecture is documented; full bounded parallel collection is deferred until module separation. | The current monolithic field-run path can be safely guarded, but changing it into producer/consumer collection before the split would broaden the frozen module surface. |
| 4. 운영 편의/안전 | Applied narrowly. | Main `field-run` now computes local KST wake targets instead of coarse 30-second polling for token prewarm and pre-open market wait. |
| 5. KIS WebSocket 검토 | Do not adopt as the main monitor path yet. | Official KIS samples show WebSocket domestic stock price and quote/depth subscriptions, but adoption requires proven field parity with the current monitor inputs and timestamp pairing. |
| 6. API 예비 한도 정책 검토 | Applied narrowly. | Normal total operating budget is raised from 12/sec to 15/sec while scouter speed remains 10/sec. This expands reserve from 2/sec to 5/sec without accelerating 장중감시 polling. Critical windows remain 7/sec total and 5/sec scouter. |
| 7. 차주 추가 검토 | Defined below. | These are review/test items, not immediate runtime behavior changes. |

## TODO 3: Intraday Collection Structure

Current safe state:

- price and quote-depth collection remains in the existing no-order KIS
  read-only path;
- there is no post-cycle sleep in the 장중감시모듈 path;
- degraded quote/depth cycles fail closed after the configured bounded retry
  limit;
- report writing is still on the same field-run loop, so it must not be
  mistaken for the final target architecture.

Target after module separation:

- bounded worker pool for quote/depth collection;
- strict per-second API budget enforcement;
- per-symbol timeout and error classification;
- paired price/depth freshness evidence;
- raw snapshot persistence before strategy judgment;
- strategy judgment/report writing consumes the prior accepted snapshot while
  the collector can start the next bounded collection cycle.

Stop condition before implementation: module split/rebuild must be explicitly
started. Until then, do not broaden `src/zurini/cli.py` or the KIS collection
surface beyond verified dry-run blockers.

## TODO 4: Operating Convenience And Safety

Applied behavior:

- token prewarm waits until the exact local KST `08:30` target instead of
  checking every 30 seconds;
- market-open waiting targets `08:59:30` first, then the local market-open
  boundary;
- local time is only the wake trigger. KIS quote/depth payload validity remains
  the operating evidence before a market-session dry-run can be accepted.

Remaining operator-safety work:

- hard-stop control;
- heartbeat/alert visibility;
- visible run-state dashboard;
- module-level session trace IDs.

## TODO 5: KIS WebSocket Review

Official KIS open-trading-api samples include WebSocket domestic-stock examples
for real-time quote/depth subscription. That is enough to keep WebSocket on the
candidate list, but not enough to replace the current REST polling path.

Adoption gate:

- price/current value;
- open/high/low;
- accumulated volume;
- accumulated traded value or same-stream fields sufficient to compute it;
- previous-day change rate;
- bid/ask quantities needed for bid/ask ratio;
- per-symbol receive timestamp;
- price-depth freshness pairing;
- reconnect and stale-heartbeat behavior;
- deterministic degraded-symbol reporting.

If any required monitor input is missing, stale, or must be filled by a separate
REST call with a different timestamp, WebSocket is rejected as the main
장중감시 path because mixed-source recovery can create timestamp mismatch and
strategy drift.

## TODO 6: API Reserve Policy

Normal window:

- provider ceiling: 20/sec;
- operating total: 15/sec;
- scouter/장중감시 read speed: 10/sec;
- reserved capacity: 5/sec.

Critical windows:

- 09:00-09:10: 7/sec total, 5/sec scouter;
- 15:10-15:20: 7/sec total, 5/sec scouter.

Reason: reserve capacity is for future order-precheck, risk-control, and
order-stage calls. It is not permission to speed up the no-order scouter.

## TODO 7: Next-Week Review Items

1. Monday market-session quote/depth validation: confirm that live KIS
   quote/depth data is non-placeholder and fresh before accepting no-order
   strategy evidence.
2. Universe exception rules: verify per-symbol exclusion reasons for new
   listings, suspensions, and insufficient 60-trading-day histories.
3. Rolling daily-bar backfill: verify multi-business-day gap recovery after PC
   downtime or user stop.
4. Bounded parallel collection design: implement only after module separation.
5. WebSocket parity experiment: compare WebSocket payloads against the required
   monitor field list before any replacement decision.
6. News defense ON/OFF comparison: run OFF baseline, ON healthy heartbeat, and
   ON stale/fail-close simulations.
7. Session traceability: add module-level run IDs and session linkage during
   the module-split rebuild.

## Verification Targets

- targeted tests for API budget and field-run wait scheduling;
- full `./scripts/verify.sh`;
- review gate with Claude disabled if unavailable and GPT/Gemini-compatible
  reviewers used where available;
- Plan A index reconciled in the same change.
