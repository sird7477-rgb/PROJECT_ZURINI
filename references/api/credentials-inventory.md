# Credentials Inventory

This file records which credential categories PROJECT_ZURINI may need later.
It intentionally does not contain real secrets, account numbers, tokens, keys,
passwords, or certificate passwords.

## Security Status

Real credential values were provided in chat on 2026-05-09. Treat those values
as exposed and rotate/reissue them before connecting any real API or account.
Do not copy the raw values into this repository.

## Required Environment Variables

| System | Environment Variables | Phase | Notes |
| --- | --- | --- | --- |
| Gemini | `GEMINI_API_KEY`, `GEMINI_PROJECT_NAME`, `GEMINI_PROJECT_NUMBER` | Tooling/reference | Use only from local `.env` or OS secret store. |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Future notifications | Not part of phase-1 backtest execution. |
| Korea Investment Securities live | `KIS_LIVE_ACCOUNT_NO`, `KIS_LIVE_APP_KEY`, `KIS_LIVE_APP_SECRET` | Deferred live/API work | Live account credentials are forbidden in phase 1. |
| Korea Investment Securities paper | `KIS_PAPER_ACCOUNT_NO`, `KIS_PAPER_APP_KEY`, `KIS_PAPER_APP_SECRET` | Deferred paper/API work | Paper trading is outside phase 1. |
| Daishin Securities | `DAISHIN_ID`, `DAISHIN_PASSWORD`, `DAISHIN_CERT_PASSWORD` | Deferred broker/API work | Store certificate material outside the repo. |

## Local Handling Rules

- Put actual values only in `.env`, OS keychain, password manager, or broker
  tooling outside git.
- `.env` is ignored by git and must stay local.
- Never paste raw secrets into docs, tests, config, commits, issues, PRs, logs,
  screenshots, or review prompts.
- Before implementing broker/API integration, add tests that fail if required
  secrets are committed or if live trading is reachable from phase-1 code.
