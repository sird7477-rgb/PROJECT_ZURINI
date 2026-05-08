# API Reference Vault

This directory is the project-local vault for API materials that will be used
later by PROJECT_ZURINI.

## Rules

- Store uploaded API documents here instead of mixing them into active product
  docs.
- Treat these files as reference material until an implementation task explicitly
  promotes a detail into `docs/`, `config/`, `src/`, or tests.
- Do not place secrets, account numbers, API keys, tokens, certificates, or
  private credentials in this directory.
- Track credential names and handling rules only in
  `references/api/credentials-inventory.md`; never track actual values.
- When implementing real 1-minute data acquisition, extract the required API
  contract into current docs and tests before writing production code against it.

## Current Use

Phase 1 still uses deterministic dummy 1-minute bars. The API materials in this
vault are for the later real historical-data ingestion step after the dummy
multi-symbol backtest path is complete.

## Index

Credential categories have been recorded without secret values. Add API
documents below when they are placed in this directory:

| File | Source/System | Purpose | Notes |
| --- | --- | --- | --- |
| `credentials-inventory.md` | Project credentials | Lists required environment variable names only | No raw secrets stored. |
