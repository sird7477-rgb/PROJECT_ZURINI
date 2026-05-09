# Performance Completion Pack

Use this pack during onboarding only when the project has explicit performance,
latency, throughput, cost, scale, or resource-usage expectations. If no
performance target exists, record performance optimization as a non-goal and
avoid speculative tuning.

## Onboarding Questions

Clarify these before implementing performance work:

- target user action, API endpoint, job, query, or build step
- acceptable latency, throughput, memory, CPU, bundle size, or cost target
- expected data volume and concurrency
- baseline measurement command and environment
- profiling or tracing tools already available in the project
- tradeoffs the user accepts: freshness, accuracy, cost, complexity, or caching
- regression threshold that should fail verification

## Workflow Additions

When performance is in scope, add these steps to the project workflow:

1. record a baseline before optimizing
2. identify the bottleneck with measurement rather than guessing
3. make the smallest change that targets the measured bottleneck
4. compare before/after results in the same environment
5. keep correctness tests passing while optimizing
6. document any tradeoff introduced by caching, batching, indexing, or
   approximation
7. include baseline, after result, and verification command in the completion
   report

## Verification Patterns

Adapt `scripts/verify.sh` to the project stack. Prefer real project commands
over placeholders.

Common checks:

```bash
pytest
npm run build
npm run test:performance
python -m pytest tests/performance
```

Performance checks can be noisy. Only fail `scripts/verify.sh` on performance
thresholds that are stable enough for the project's local or CI environment.

## Completion Criteria

Performance work is complete only when:

- a baseline and after measurement are recorded
- the optimized path still passes correctness checks
- the measured result meets the target or the remaining gap is reported
- any added cache, index, batch, or concurrency behavior has invalidation or
  failure-mode expectations documented
- `./scripts/verify.sh` and `./scripts/review-gate.sh` pass, or any degraded
  trust state is reported explicitly

## Non-Goals

Do not optimize speculative bottlenecks, rewrite architecture, add caching, add
queues, or change infrastructure unless the project outcome requires it or the
user explicitly requests it.
