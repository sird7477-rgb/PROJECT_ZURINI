# Domain Packs

Domain packs are optional onboarding reference packs for domain- or
framework-specific project guidance. They do not replace the generic
`automation-base` template, and they are never merged into project instructions
automatically.

Use `docs/DOMAIN_PACK_AUTHORING_GUIDE.md` when creating or changing a pack. This
file owns lifecycle and application rules; the authoring guide owns pack quality,
question design, risk boundaries, verification examples, and optional split-rule
standards.

## Baseline, Completion Packs, And Domain Packs

- `templates/automation-base/` is the always-installed generic baseline. It owns
  the common workflow, review gate, operating policy, verification placeholder,
  and onboarding structure.
- `docs/*_COMPLETION.md` files are cross-cutting completion packs. They apply
  when a project has a UI, deployment, security, data, performance, or
  observability requirement.
- `templates/domain-packs/<name>/` directories are concrete domain packs. They
  apply only when local evidence and onboarding answers confirm that the project
  matches the domain.

There is no generic domain pack. Generic guidance belongs in
`automation-base`; domain packs are for concrete domains or frameworks such as
Odoo.

## Lifecycle

1. Source packs live under `templates/domain-packs/<name>/`.
2. `aiinit` copies available packs into the target repository under
   `.omx/domain-packs/<name>/`.
3. `.omx/` is ignored, so installed domain packs are onboarding references, not
   commit candidates.
4. During onboarding, inspect local evidence first, then select, reject, or
   defer each installed pack.
5. If a pack applies, merge only the applicable guidance into project files such
   as `AGENTS.md`, `docs/WORKFLOW.md`, and `scripts/verify.sh`.
6. Record rejected packs as non-goals so generic projects do not inherit
   unrelated domain rules.

`aiinit` preserves an existing installed pack reference instead of overwriting
it. A target repository's `.omx/domain-packs/` copy may therefore lag behind the
AI_AUTO source pack and should be treated as onboarding context, not a managed
template file.

## Standard Pack Layout

A domain pack should use this structure unless the domain needs a documented
exception:

```text
templates/domain-packs/<name>/
  README.md
  AGENTS.patch.md
  WORKFLOW.md
  verify-patterns.md
  review-checklist.md
  split-rules.json       # optional, only when the domain has stable module boundaries
```

- `README.md`: when to use the pack, pack files, and onboarding questions.
- `AGENTS.patch.md`: candidate guidance for the target project's `AGENTS.md`.
- `WORKFLOW.md`: candidate guidance for the target project's
  `docs/WORKFLOW.md`.
- `verify-patterns.md`: example verification shapes for `scripts/verify.sh`.
- `review-checklist.md`: review-gate or manual review checklist.
- `split-rules.json`: optional `ai-split-plan` rules for proposing Python
  top-level function/class moves during rebuild planning. These rules generate
  proposals only; dry-run review and an explicit apply gate are still required.

## Authoring Rules

- Follow `docs/DOMAIN_PACK_AUTHORING_GUIDE.md` before adding or changing a pack.
- Keep reusable domain guidance in the pack.
- Keep project names, credentials, private URLs, production hosts, customer
  workflows, branch routing, SSH details, and deployment access rules out of
  reusable packs.
- Prefer prompts, constraints, verification patterns, and review criteria over
  mandatory commands.
- Label command examples as examples unless they were verified in the target
  project.
- Do not put generic baseline rules in `templates/domain-packs/`.
- Keep split rules conservative and explainable. Prefer name-based rules such as
  `name_contains`, `name_prefixes`, `name_suffixes`, and optional `kinds` over
  speculative dependency or call-graph assumptions.

## Application Rules

- Confirm the project domain before applying a pack.
- Read the installed copy from `.omx/domain-packs/<name>/` inside the target
  repository.
- Merge only applicable content.
- Remove unused checklist items and example commands from final project docs.
- Convert verification examples into real executable project commands before
  claiming completion.
- Keep the target project's final `AGENTS.md`, `docs/WORKFLOW.md`, and
  `scripts/verify.sh` project-specific.

## Verification Expectations

After applying a domain pack, `scripts/verify.sh` must still run real
project-local checks. Runtime checks are preferred when available. Static checks
may be used as fallback evidence, but they must be reported as fallback rather
than full runtime proof.

Completion reports should include:

- selected domain packs
- rejected or deferred domain packs
- applied guidance
- skipped pack sections and why
- verification evidence

## Current Packs

- `templates/domain-packs/odoo/`: Odoo module development and customization
  guidance, including version discipline, addon scope, localization prompts,
  verification examples, and review checklist.
- `templates/domain-packs/kis-domestic-stock/`: Korean domestic-stock KIS
  automated-trading guidance for module-separation refactors with strict
  no-real-order, no-credential, no-strategy-meaning-change boundaries;
  Repomix/Aider usage limits; paper/live separation; duplicate-order
  prevention; kill switch; and maximum-loss verification checklists.
