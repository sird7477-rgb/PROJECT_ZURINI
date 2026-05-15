# Candidate Workflow Guidance: KIS Domestic Stock

## Standard Flow

1. Identify execution mode: no-order, paper, or live.
2. Validate credential boundary without printing secrets.
3. Validate source freshness and market calendar assumptions.
4. Validate warm-up/history inputs before universe selection and strategy
   evaluation.
5. Validate market-data timestamp freshness and per-symbol degradation.
6. Run strategy in no-order mode first.
7. Record reason counts, near misses, and fail-closed blockers.
8. Only after explicit approval, plan paper/live order boundaries.

## Module Split Workflow

Before editing:

- list current modules and responsibilities;
- write or select tests that lock strategy outputs;
- define public interfaces between data, strategy, risk, and broker layers.

During edits:

- move one responsibility at a time;
- keep broker calls behind adapter interfaces;
- keep strategy parameter defaults unchanged unless the task is strategy
  validation;
- preserve existing artifact schemas or provide migrations.

After edits:

- run project verification;
- run review gate when available;
- summarize changed boundaries, preserved behavior, and residual risk.

## Field-Test Evidence

A no-order dry-run is valid operating evidence only when:

- required warm-up/source history is present and fresh;
- quote/depth data is timestamped and within budget;
- degraded symbols are classified per symbol;
- order transmission remains hard-blocked;
- status artifacts distinguish live collection, replay, and analysis-only
  evidence.
