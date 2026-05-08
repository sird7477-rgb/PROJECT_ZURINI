# Project ZURINI Agent Instructions

This repository is the planning and automation baseline for PROJECT_ZURINI, a
Korean-market automated trading system design. The current repository state is
documentation-first: it contains strategy, architecture, flow, and sequence
documents under `(old)/`, plus Codex/OMX automation scripts.

There is no executable trading engine in this baseline yet.

## Project Scope

Allowed without a new plan:

- documentation cleanup that preserves the trading rules and diagrams
- workflow clarification
- verification script improvements
- narrow automation reliability fixes
- repository hygiene for git, review, and CI-style checks

Not allowed without an explicit new plan:

- live trading code that can place real orders
- broker API credential handling
- authentication, authorization, or security-sensitive changes
- data model, migration, or destructive storage changes
- new dependencies or external services
- large architecture rewrites
- changes that weaken risk controls, kill switches, or verification language

## Domain Rules

- Treat `(old)/` as the current source material until a replacement docs layout is
  approved.
- Preserve Korean strategy details, thresholds, and risk controls unless the user
  explicitly asks to revise them.
- Keep live-order behavior out of scope until sandbox, backtest, and paper-trade
  verification are defined.
- Prefer small, reviewable diffs. Do not summarize away detailed trading rules.

## Required References

- `(old)/# [자동매매 전략 기획서].md`
- `(old)/# [자동매매 전략 기획서_고도화].md`
- `(old)/# [자동매매 플로우 차트].md`
- `(old)/[자동매매_시퀀스_다이어그램].md`
- `(old)/[자동매매_통합_아키텍처_설계서].md`
- `docs/WORKFLOW.md`
- `scripts/verify.sh`
- `scripts/review-gate.sh`

## Verification Rule

Before claiming a task is complete, run:

```bash
./scripts/verify.sh
```

Before presenting a commit candidate, run:

```bash
./scripts/review-gate.sh
```

If `./scripts/verify.sh` fails, the task is not complete.
If `./scripts/review-gate.sh` fails or returns a decision other than `proceed`
or `proceed_degraded`, do not present the change as ready to commit.

`proceed_degraded` may continue only when the degraded trust level and missing
reviewer state are reported clearly.

## Completion Report Format

When reporting completion, include:

- changed files
- diff summary
- verification command
- verification result
- review-gate result when a commit candidate is involved
- known warnings or limitations
