# Domain Pack Authoring Guide

This guide defines how to write reusable domain packs. `docs/DOMAIN_PACKS.md`
owns the lifecycle and application rules; this file owns authoring quality.

## Authoring Contract

A domain pack is an AI-readable domain knowledge package, not a project policy
dump. It should help the agent decide whether the pack applies, ask narrow
questions, set module boundaries, choose verification evidence, and identify
domain-specific review risks.

Good packs are:

- reusable across projects in the same domain
- explicit about when not to apply the pack
- safe to copy into `.omx/domain-packs/` without secrets or production access
- concise enough to inspect during onboarding
- concrete enough to turn into `AGENTS.md`, `docs/WORKFLOW.md`, and
  `scripts/verify.sh` changes

## Required Decisions

Every pack README should answer these decisions:

- applicability: what local evidence or interview answer selects the pack
- rejection: what evidence means the pack must not be applied
- deferral: what missing fact keeps the pack in a deferred state
- risk tier: which domain actions are low, standard, strict, or fail-closed
- project-specific exclusions: what must remain outside the reusable pack

## Standard Files

Use the standard layout from `docs/DOMAIN_PACKS.md`. Add optional files only
when the domain needs them and the README explains why.

Recommended optional files:

- `risk-boundaries.md`: domain-critical boundaries and fail-closed cases
- `interview.md`: narrow onboarding and checkpoint questions
- `split-rules.json`: conservative Python split proposals for `ai-split-plan`

Keep `README.md` as the index. Do not require agents to read every optional file
unless the pack is selected or the task touches that area.

## Interview Design

Questions should be narrow and mapped to plan fields. Prefer several concrete
questions over one broad question when a wrong answer could change execution.

Each interview item should include:

- trigger: onboarding, rebuild planning, migration, risky checkpoint, or user
  request
- question: the exact fact needed
- answer shape: short text, boolean, enum, path, command, version, or evidence
- plan field: where the answer is recorded
- required_when: what condition makes the question mandatory
- assumption_allowed: whether the agent may infer the answer from local files

Mandatory questions are appropriate when the answer can affect production,
credentials, real data, financial/order execution, destructive operations,
security, or a major module boundary.

## Risk Boundaries

Domain packs should name domain-specific boundaries that must not be crossed by
ordinary automation. Examples include:

- real-money order placement, payment, settlement, or inventory movement
- production credentials, secrets, private endpoints, or customer data
- migrations, schema rewrites, destructive cleanup, or irreversible deploys
- regulatory, accounting, localization, tax, or audit-critical behavior

For each boundary, define:

- what counts as touching the boundary
- what evidence is required before execution
- whether `review-gate` is required
- what rollback or recovery evidence is needed

## Verification Patterns

`verify-patterns.md` should provide examples that can be converted into real
project checks. It must not pretend examples are verified commands.

Good patterns include:

- static checks that catch common domain mistakes
- runtime smoke checks for the smallest meaningful domain workflow
- sandbox-vs-real-network evidence rules
- fixtures or sample commands that are clearly labeled as examples
- fail-closed conditions for production, real data, or destructive paths

After applying a pack, the target project must still own real verification in
`scripts/verify.sh`.

## Split Rules

`split-rules.json` is optional and only for stable, conservative module
boundaries. It feeds `ai-split-plan` and creates proposals, not execution
approval.

Rules should be explainable by symbol names and kinds:

```json
{
  "module_rules": [
    {
      "name": "orders",
      "destination": "{source_dir}/orders.py",
      "name_contains": ["order"],
      "kinds": ["function", "class"]
    }
  ]
}
```

Do not use split rules to encode speculative call-graph assumptions. If a
boundary is uncertain, leave it for interview or rebuild planning.

## Forbidden Content

Do not put these in reusable packs:

- credentials, tokens, private URLs, SSH hosts, production IPs, or customer names
- branch routing, deployment approvals, or access rules for one project
- commands that require private services unless clearly marked as examples
- generic baseline automation rules that belong in `automation-base`
- large prose copied from project-specific docs

Project-specific facts belong in the target repo after interview, not in the
source pack.

## Review Checklist

Before adding or changing a pack, verify:

- the README has select/reject/defer criteria
- questions are narrow and mapped to plan fields
- risk boundaries name fail-closed conditions
- verification examples are labeled and project-adaptable
- optional split rules are conservative and dry-run only
- no secrets or project-specific operational details are present
- `docs/DOMAIN_PACKS.md` remains the lifecycle source of truth
