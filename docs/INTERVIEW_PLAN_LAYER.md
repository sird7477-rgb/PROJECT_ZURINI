# Interview And Plan Layer

This document defines the reusable AI_AUTO interview and planning contract. It
is not rebuild-specific. Project onboarding, rebuild planning, domain-pack
adoption, migration planning, risky feature design, and operational planning
should share this layer.

## Core Principle

The goal is not to minimize the number of questions. The goal is to minimize the
decision width of each question.

AI should not reduce user interaction by filling important blanks with
assumptions. Narrow, concrete questions are acceptable even when they increase
the number of turns, because they keep the final output aligned with the user's
intent.

## Initial Project Setup Behavior

During initial project setup, the agent should behave as follows:

1. Run or confirm `aiinit` only when template installation is requested.
   Existing initialized projects may start this interview layer without
   reinstalling the template.
2. Inspect local evidence first: README, docs, scripts, package files, existing
   automation, domain notes, and git status.
3. Start an onboarding interview as a sequence of narrow decisions.
4. Map every answer to durable project files, usually `AGENTS.md`,
   `docs/WORKFLOW.md`, `scripts/verify.sh`, and relevant linked docs.
5. Track ambiguity instead of hiding assumptions.
6. Stop at a plan/report boundary before commits, pushes, destructive actions,
   credentials, production, or materially scope-changing execution.

The onboarding interview should not ask one broad question such as "What kind of
project is this?" and then infer the rest. Use the concrete onboarding checklist
in `docs/AUTOMATION_OPERATING_POLICY.md`; this document defines how each
question is shaped, mapped, and gated.

## Activation Points

Start an interview/planning lane when user decisions are needed to change
outcome, risk, cost, durability, approval boundary, or execution scope and any
of these are true:

- project initial environment setup begins
- the user explicitly requests interview, planning, or no-assumption work
- a rebuild plan is requested
- migration, architecture, production, deployment, data, trading, credential, or
  irreversible behavior may be affected
- a choice may create critical failure risk
- a choice may create unusually positive project leverage and would materially
  change project direction, long-term maintenance cost, or accepted risk

Routine, low-risk, reversible edits may proceed without interview unless the
user asks otherwise.

Recommendation, review, and brainstorming requests are answer-only by default.
They start an interview/planning lane only when a user decision is required to
change outcome, risk, cost, durability, or execution scope.

Important checkpoints must be tied to at least one explicit category:

- irreversible or expensive-to-undo action
- credentialed, production-facing, deployment, trading, or real-data behavior
- domain meaning or business-rule interpretation
- risk appetite or safety boundary
- scope boundary, non-goal, or ownership split
- verification, rollback, or stop-condition ownership
- migration, schema, persistence, or external contract change
- high-leverage option that materially changes project direction or long-term
  maintenance cost

A generally useful improvement idea is not high-leverage by itself.

## Question Rules

- Prefer many narrow, concrete questions over a few broad questions.
- Each question should cover one decision.
- If answering a question requires the user to decide multiple things at once,
  split the question.
- Default to objective choices with 2-4 options and a free-form escape hatch.
- Before asking, inspect local evidence that can reasonably answer or narrow the
  question.
- Do not ask internal implementation trivia unless it changes project outcome,
  risk, verification, or maintenance burden.
- Do not repeat questions already answered unless new evidence invalidates the
  old answer.

AI may summarize local evidence and low-risk facts. AI must not infer execution
direction, risk appetite, domain meaning, or priority unless the user explicitly
permits inference.

## Mandatory Plan Schema

Every interview answer must be written into a concrete plan field instead of
remaining only in chat history.

The full schema in this section is mandatory for initial onboarding, `deep`
interviews, rebuild planning, migration planning, production/credentialed/data
work, and other high-risk plan-first lanes.

For `light` interviews, record the user decision, assumption, and verification
impact in the response or local plan note; the full schema is optional unless
the answer turns the task into a high-risk or long-lived change.

For `standard` interviews, use a short plan with the fields that materially
affect execution. Escalate to the full schema when open decisions affect safety,
scope, verification, rollback, production, credentials, data, or long-term
maintenance.

Required fields:

- Goal
- Non-goals
- Success criteria
- Constraints
- Risk gates
- Assumptions
- User decisions
- Open questions
- Execution boundaries
- Verification plan
- Rollback or stop condition
- Ambiguity index
- Evidence references
- Ready-to-execute gate

For full-schema lanes, before execution these fields must be non-empty: Goal, Non-goals, Success
criteria, Constraints, Risk gates, User decisions, Execution boundaries,
Verification plan, Rollback or stop condition, Ambiguity index, Evidence
references, and Ready-to-execute gate.

Open questions may be non-empty only when each item is explicitly excluded from
the execution scope. Assumptions may be non-empty only when each item has local
evidence, user approval, or an explicit scope exclusion.

## Ambiguity Index

Plans must track ambiguity as open decisions over total decisions:

- Critical ambiguity = critical_open_decisions / total_critical_decisions.
- Overall ambiguity = overall_open_decisions / overall_total_decisions.
- Percentages round up to the nearest whole percent.
- If a total decision count is 0 and the corresponding open decision count is 0,
  the ambiguity percentage is 0% and non-blocking.
- If a total decision count is 0 and the corresponding open decision count is
  greater than 0, the artifact is invalid and `ready_to_execute` must be false.
- Critical-risk ambiguity must be 0% before execution.
- Overall execution ambiguity should be 10% or lower before execution.
- Remaining ambiguity must be written as open questions and excluded from the
  execution scope.

Ambiguity should decrease through narrow questions, local evidence, and explicit
plan fields. It should not decrease merely because AI made an assumption.

## Plan/Run Boundary

Interview and planning may inspect files, ask questions, summarize evidence, and
write plan artifacts. They must stop before execution.

For full-schema lanes, execution requires an approved execution gate in the plan
artifact. A separate user execution request may create that gate only when it
names or clearly refers to the current plan artifact and authorized scope. A
completed plan is not execution approval.

For safe, reversible `light` or `standard` tasks, an explicit user execution
request plus a clear local plan is sufficient. Do not require the full execution
gate unless the task crosses into destructive, credentialed, production,
real-data, material scope-change, rebuild-run, migration, or other high-risk
execution.

An approved execution gate must include:

- approved_by: user or named authority
- approved_at: timestamp or explicit current-turn approval reference
- approved_scope: exact scope authorized for execution
- plan_artifact: path to the reviewed plan
- readiness: ready_to_execute true
- exclusions: scope that remains forbidden

Old approval, broad approval, "go ahead" without plan/scope reference, or
approval from a different plan artifact does not satisfy this gate.

The ready-to-execute gate must include:

- ready_to_execute: true or false
- blocking_reasons
- critical_ambiguity_percent
- overall_ambiguity_percent
- approved_execution_gate
- verification_commands
- stop_conditions

For full-schema lanes, `ready_to_execute` must be false when there are
unresolved critical decisions, missing required fields, unexcluded open
questions, missing evidence references, or no approved execution gate.

For safe, reversible `light` or `standard` tasks that do not use the full
schema, do not evaluate `ready_to_execute`; use the local plan, explicit user
request, and normal verification instead.

## Local Status Tools

AI_AUTO includes small local helpers for making this contract observable without
adding external dependencies:

- `ai-plan-status`: read-only computed status for a plan artifact. It reports
  `ready_to_execute`, ambiguity, blockers, missing fields, open questions, stale
  evidence, and the next action. `ready_to_execute` is computed by the tool; it
  is not a user-editable approval field.
- `ai-interview-record`: appends one interview answer to a JSON plan artifact.
  User decisions and AI assumptions remain separate. Recording an answer does
  not approve execution.
- `ai-plan-review`: read-only quality review using the same status calculation.
  A passing review means the plan shape is acceptable; it is not execution
  approval.
- `ai-plan-export`: writes a concise execution summary for handoff. Exporting a
  plan does not approve execution.

These helpers are the first local status layer. External tools may later provide
evidence, but they must not own readiness, ambiguity, or approval decisions.
