# UI Completion Pack

Use this pack during onboarding only when the final project outcome includes a
user-facing or operator-facing UI. If the project is API-only, CLI-only,
library-only, or a backend service with no required UI, record UI as a non-goal
in `AGENTS.md` and `docs/WORKFLOW.md`.

## Onboarding Questions

Clarify these before implementing UI work:

- who will use the UI
- what primary workflow must be completed on the first screen
- whether the UI is customer-facing, internal operations, admin, dashboard, or
  prototype-only
- required viewports: desktop, mobile, tablet, kiosk, embedded, or responsive
- required states: empty, loading, success, validation error, server error,
  permission denied, offline, and destructive confirmation
- required data freshness and real-time behavior
- accessibility expectations, at minimum keyboard navigation and readable
  contrast
- visual source of truth: existing design system, brand guide, screenshots, or
  local product conventions
- frontend stack and package commands
- screenshot or browser smoke checks that prove completion

## Workflow Additions

When UI is in scope, add these steps to the project workflow:

1. define the primary user journey and expected completion state
2. inspect existing design and component patterns before adding new UI
3. implement the smallest end-to-end slice that proves the journey
4. cover important empty/loading/error/success states
5. run frontend lint/typecheck/build/test commands when available
6. run browser or screenshot smoke checks for the main journey
7. inspect the UI at the required viewports before claiming completion
8. include screenshots, browser check results, or exact smoke evidence in the
   completion report

## Verification Patterns

Adapt `scripts/verify.sh` to the project stack. Prefer real project commands
over placeholders.

Common checks:

```bash
npm run lint
npm run typecheck
npm test
npm run build
npx playwright test
```

Use only the commands that exist and are meaningful for the project. Do not add
frontend dependencies during onboarding unless the user approves them.

For static HTML or simple browser apps, a lighter smoke check may be enough:

```bash
test -f index.html
```

For apps with a dev server, verify at least one real page:

```bash
npm run build
npx playwright test --project=chromium
```

## Completion Criteria

UI work is complete only when:

- the primary workflow works without relying on hidden manual steps
- text fits its containers at required viewport sizes
- interactive controls have visible disabled, hover/focus, loading, and error
  states where applicable
- the implementation follows the existing design system or explicitly recorded
  project UI rules
- browser console errors are checked when a browser test or manual browser smoke
  is part of the project workflow
- screenshots or browser test results are captured for the changed main path
- `./scripts/verify.sh` and `./scripts/review-gate.sh` pass, or any degraded
  trust state is reported explicitly

## Non-Goals

Do not create a landing page, marketing page, animation layer, design system, or
new frontend stack unless the project outcome requires it or the user explicitly
requests it.
