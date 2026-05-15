# AI_AUTO Patch Notes

This file records template-level changes by AI_AUTO template version. Review it
before patching an existing project, then use `ai-auto-template-status` to check
which files are template-owned, hybrid, or project-owned.

## Upstream Improvement Queue

- 2026-05-15: 리뷰어 관련 컨텍스트주입을 폐지하고 직접 읽게 만드는거
  AI_AUTO 본진에 개선 큐 넣어줘
  - Intent: replace large review-context injection with a repository-reading
    reviewer mode.
  - Target shape: pass a short brief, changed-file list, verification result,
    and required policy files, then let Claude/Gemini/Codex reviewers inspect
    files directly from the repo in read-only mode.
  - Reason: reduce token use and avoid prompt-size/OOM failures on large diffs.
- 2026-05-15: 지침경량화는 본진에 큐 남기고 직접 행동하지 말 것
  - Intent: reduce default AI_AUTO guidance/context weight upstream without
    rewriting project-local `AGENTS.md` or local operating rules during an
    active project task.
  - Target shape: keep only durable safety, verification, routing, and
    ownership rules in the default always-loaded guidance; move long examples,
    procedural detail, and optional completion-pack explanations into linked
    docs loaded on demand.
  - Constraint: project-specific guidance must remain authoritative and must
    not be overwritten by an automated template refresh.

## 2026.05.15.1

- Added ownership and patch-policy columns to `ai-auto-template-status` output.
- Classified managed files as `template-owned`, `hybrid`, or `project-owned`.
- Marked `AGENTS.md` and `docs/WORKFLOW.md` as `review-merge` so project-specific
  rules are preserved during patch review.
- Marked `scripts/verify.sh` as `inspect-only` because target projects are
  expected to replace the onboarding placeholder with project-specific checks.
- Documented that generated/runtime `.omx/` artifacts are outside the managed
  patch manifest.
- Added this patch-note file so projects can inspect version changes before
  applying template updates.
- Added automatic lightweight AI review context for small tracked diffs. The
  default review context now stays diff-centered for small changes and omits
  planning/reference-file bodies unless `REVIEW_CONTEXT_DETAIL=full` is set.

## 2026.05.14.1

- Initial managed automation template version marker.
