# Deployment Completion Pack

Use this pack during onboarding only when the project must be deployed,
packaged, released, or operated outside a local development environment. If the
project is local-only, prototype-only, or a library with no release target,
record deployment as a non-goal in `AGENTS.md` and `docs/WORKFLOW.md`.

## Onboarding Questions

Clarify these before implementing deployment-related work:

- target environment: local server, cloud, container host, PaaS, app store, or
  customer-managed infrastructure
- release artifact: container image, static build, package, binary, migration,
  script bundle, or source-only handoff
- required environment variables and which values are secrets
- build, start, stop, health check, and rollback commands
- whether deployment is manual, CI/CD-driven, or triggered by git push
- expected smoke checks after deployment
- downtime tolerance and rollback criteria
- who owns credentials, DNS, certificates, and production access

## Workflow Additions

When deployment is in scope, add these steps to the project workflow:

1. define the target environment and release artifact
2. separate build-time settings, runtime settings, and secrets
3. document the deploy command and the post-deploy smoke check
4. verify that local build output matches the deployable artifact
5. record rollback or recovery steps before changing production-like systems
6. treat production deploys, credential changes, DNS changes, and irreversible
   migrations as approval-gated actions
7. include deploy target, artifact, smoke result, and rollback status in the
   completion report

## Verification Patterns

Adapt `scripts/verify.sh` to the project stack. Prefer real project commands
over placeholders.

Common checks:

```bash
docker compose config
docker compose build
npm run build
python -m build
```

For deployed services, include a smoke check against the deployed or staging
endpoint only when credentials and environment access are explicitly available.
Do not make production-changing commands part of `scripts/verify.sh` by default.

## Completion Criteria

Deployment work is complete only when:

- the release artifact is reproducible from documented commands
- required environment variables are listed without exposing secret values
- at least one health or smoke check proves the deployed artifact can start
- rollback or recovery expectations are documented
- production-impacting actions were approved before execution
- `./scripts/verify.sh` and `./scripts/review-gate.sh` pass, or any degraded
  trust state is reported explicitly

## Non-Goals

Do not add CI/CD, hosting, DNS, certificates, monitoring, or production deploy
automation unless the project outcome requires it or the user explicitly
requests it.
