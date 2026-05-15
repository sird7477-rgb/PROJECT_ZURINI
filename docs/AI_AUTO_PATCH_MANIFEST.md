# AI_AUTO Patch Manifest

This manifest classifies AI_AUTO managed paths before template refresh work.
It prevents data loss by separating template-owned files from project-owned,
hybrid, and generated/runtime paths.

## Ownership Rules

| Ownership | Patch Policy | Meaning |
| --- | --- | --- |
| `template-owned` | `update` | AI_AUTO common file. Compare to the latest template and update unless a local safety patch is intentionally stronger. |
| `hybrid` | `review-merge` | Started from AI_AUTO but now carries PROJECT_ZURINI rules. Do not overwrite; inspect template drift and merge only compatible additions. |
| `project-owned` | `inspect-only` | Project-specific control surface. Do not overwrite from AI_AUTO. Report relevant upstream changes only. |
| `generated` | `ignore` | Runtime/cache/report artifacts. Exclude from patch comparison and never delete during template refresh. |

## Managed Path Manifest

| Path | Ownership | Patch Policy |
| --- | --- | --- |
| `AI_AUTO_TEMPLATE_VERSION` | template-owned | update |
| `docs/AI_MODEL_ROUTING.md` | template-owned | update |
| `docs/AUTOMATION_OPERATING_POLICY.md` | hybrid | review-merge |
| `docs/DATA_COMPLETION.md` | template-owned | update |
| `docs/DEPLOYMENT_COMPLETION.md` | template-owned | update |
| `docs/DOMAIN_PACK_AUTHORING_GUIDE.md` | template-owned | update |
| `docs/DOMAIN_PACKS.md` | template-owned | update |
| `docs/INCIDENT_OPS.md` | template-owned | update |
| `docs/INTERVIEW_PLAN_LAYER.md` | template-owned | update |
| `docs/OBSERVABILITY_COMPLETION.md` | template-owned | update |
| `docs/PATCH_NOTES.md` | template-owned | update |
| `docs/PERFORMANCE_COMPLETION.md` | template-owned | update |
| `docs/SECURITY_COMPLETION.md` | template-owned | update |
| `docs/SESSION_QUALITY_PLAN.md` | hybrid | review-merge |
| `docs/UI_COMPLETION.md` | hybrid | review-merge |
| `docs/WORKFLOW.md` | hybrid | review-merge |
| `AGENTS.md` | hybrid | review-merge |
| `scripts/archive-omx-artifacts.sh` | hybrid | review-merge |
| `scripts/automation-doctor.sh` | hybrid | review-merge |
| `scripts/collect-review-context.sh` | template-owned | update |
| `scripts/discover-ai-models.sh` | template-owned | update |
| `scripts/make-review-prompts.sh` | template-owned | update |
| `scripts/record-feedback.sh` | template-owned | update |
| `scripts/record-project-memory.sh` | hybrid | review-merge |
| `scripts/resolve-feedback.sh` | template-owned | update |
| `scripts/review-gate.sh` | hybrid | review-merge |
| `scripts/run-ai-reviews.sh` | template-owned | update |
| `scripts/summarize-ai-reviews.sh` | hybrid | review-merge |
| `scripts/test-review-summary.sh` | hybrid | review-merge |
| `scripts/verify.sh` | project-owned | inspect-only |
| `scripts/write-session-checkpoint.sh` | template-owned | update |

## Generated And Runtime Exclusions

| Path | Ownership | Patch Policy |
| --- | --- | --- |
| `.omx/**` | generated | ignore |
| `.pytest_cache/**` | generated | ignore |
| `reports/**` | generated | ignore |
| `data/raw/**` | generated | ignore |
| `data/derived/**` | generated | ignore |
| `sample/collect_yearly/**` | project-owned | inspect-only |
| local database volumes and runtime caches | generated | ignore |

## Current Refresh Decision

- `missing` AI_AUTO managed files were added from template version
  `2026.05.14.1`.
- Template-owned review/model-routing scripts were updated to the latest
  template.
- Hybrid files were not overwritten. Compatible upstream additions were merged
  only where they did not weaken PROJECT_ZURINI rules.
- Project-owned `scripts/verify.sh` remains project-specific and only gained
  checks for newly adopted AI_AUTO files.
- Generated/runtime paths were not patched or deleted.

## 2026.05.15.1 Refresh Decision

- `AI_AUTO_TEMPLATE_VERSION` was updated to `2026.05.15.1`.
- `docs/PATCH_NOTES.md` was added from the AI_AUTO template.
- `scripts/collect-review-context.sh` received the template lightweight-review
  context controls:
  `REVIEW_CONTEXT_DETAIL`, `REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES`, and
  `REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES`.
- `scripts/run-ai-reviews.sh` now forwards those lightweight-review controls to
  context collection and external reviewer reruns.
- Existing PROJECT_ZURINI safety additions were preserved, including stricter
  artifact deletion confirmation, timestamped review-gate logging, Codex
  fallback focused-context support, local hardware constraints, fail-closed
  operating-input rules, and trading-specific workflow guidance.
- `ai-auto-template-status` reports installed and current version both as
  `2026.05.15.1`; remaining `different` rows are intentional customized or
  project-owned/hybrid drift, not missing template files.
