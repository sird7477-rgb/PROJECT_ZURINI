# Data Completion Pack

Use this pack during onboarding only when the project owns persistent data,
database schema, migrations, seed/demo data, import/export flows, or recovery
requirements. If the project is stateless, calculation-only, or source-only,
record data persistence as a non-goal.

## Onboarding Questions

Clarify these before implementing data-related work:

- source of truth: database, files, external API, user upload, generated data,
  or in-memory state
- schema ownership and migration tool
- seed, fixture, demo, or reference data requirements
- backup, restore, retention, and deletion expectations
- import/export formats and validation rules
- data volume and concurrency assumptions
- whether migrations must be reversible
- whether existing production data must be preserved

## Workflow Additions

When data is in scope, add these steps to the project workflow:

1. define the source of truth and data lifecycle
2. make schema changes through the project's migration mechanism
3. keep seed/demo/reference data separate from runtime-generated data
4. test empty, invalid, duplicate, and existing-data cases
5. document backup or rollback expectations before risky migrations
6. avoid direct production data manipulation without explicit approval
7. include migration, seed, and data integrity evidence in the completion report

## Verification Patterns

Adapt `scripts/verify.sh` to the project stack. Prefer real project commands
over placeholders.

Common checks:

```bash
pytest
python manage.py migrate --check
alembic check
docker compose run --rm app pytest
```

Use only commands that exist in the project. For frameworks without a migration
checker, a targeted smoke test that creates, reads, updates, and deletes a
representative record may be enough.

## Completion Criteria

Data work is complete only when:

- schema changes, seed data, and runtime data are clearly separated
- migrations or setup steps are reproducible from documented commands
- existing-data and empty-data behavior is covered
- destructive data operations are approval-gated and have a rollback plan when
  realistic
- import/export validation is tested when relevant
- `./scripts/verify.sh` and `./scripts/review-gate.sh` pass, or any degraded
  trust state is reported explicitly

## Non-Goals

Do not add a database, migration framework, data warehouse, backup system, or
bulk import/export pipeline unless the project outcome requires it or the user
explicitly requests it.
