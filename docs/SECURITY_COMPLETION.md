# Security Completion Pack

Use this pack during onboarding only when the project handles authentication,
authorization, secrets, personal data, payments, privileged operations, or
external integrations. If the project has no security-sensitive surface beyond
basic local development, record security hardening as a non-goal while still
keeping normal secret hygiene.

## Onboarding Questions

Clarify these before implementing security-sensitive work:

- protected actors: anonymous users, authenticated users, admins, operators,
  service accounts, or external systems
- authentication method and session/token lifetime expectations
- authorization boundaries and roles
- sensitive data classes: credentials, personal data, financial data, business
  confidential data, or customer content
- secret storage and rotation expectations
- audit/logging requirements and what must never be logged
- destructive or privileged actions that require confirmation
- required security tests, reviews, or compliance constraints

## Workflow Additions

When security is in scope, add these steps to the project workflow:

1. define the trust boundaries before implementation
2. keep secrets out of source, logs, review prompts, screenshots, and durable
   memory files
3. implement authorization checks at the server or authoritative boundary
4. cover denied, expired, missing, and malformed credential cases
5. review logs and error output for accidental secret or personal-data exposure
6. include security-relevant test evidence in the completion report

## Verification Patterns

Adapt `scripts/verify.sh` to the project stack. Prefer real project commands
over placeholders.

Common checks:

```bash
npm audit --audit-level=high
python -m pip check
pytest
```

Use dependency audit commands only when the package manager exists and the
project accepts their noise level. For access-control features, targeted tests
for allowed and denied paths are usually more valuable than broad scanner
output.

## Completion Criteria

Security-sensitive work is complete only when:

- authentication and authorization expectations are explicitly recorded
- allowed and denied paths are tested or manually smoke-checked
- secrets are not committed, printed, logged, or stored in `.omx/` memory
- error messages do not expose sensitive internals or credentials
- destructive operations require an intentional confirmation path when relevant
- `./scripts/verify.sh` and `./scripts/review-gate.sh` pass, or any degraded
  trust state is reported explicitly

## Non-Goals

Do not invent enterprise security architecture, compliance programs, SSO, RBAC,
or encryption layers unless the project outcome requires them or the user
explicitly requests them.
