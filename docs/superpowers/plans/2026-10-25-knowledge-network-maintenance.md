# Knowledge Network Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, evidence-first knowledge-network maintenance assistant that audits the library, auto-applies only high-confidence reversible repairs, schedules model work during spare quota, and exposes a polished problem-first workbench.

**Architecture:** Extend the existing FastAPI/SQLAlchemy knowledge services with persistent maintenance runs and issues. Reuse `BackgroundResearchWorker` as the single scheduler, adding a maintenance queue that obeys the same reading-presence, foreground-task, quota, hourly-call and single-concurrency gates. The model receives bounded suspicious neighborhoods and returns typed proposals; the application validates evidence, computes eligibility, applies mutations through existing curation functions, and records inverse snapshots in `KnowledgeChange`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, SQLite, existing OpenAI-compatible provider and Codex subscription provider, React/TypeScript/Vite, existing warm editorial CSS, pytest, Playwright.

---

## File map

Create:

- `backend/app/services/knowledge_maintenance.py` — deterministic audit, bounded neighborhood assembly, evidence validation, proposal classification, apply/undo orchestration.
- `backend/app/api/knowledge_maintenance.py` — maintenance run, issue, apply, reject and undo routes.
- `backend/app/maintenance_schemas.py` — request and response models for runs and issues.
- `backend/migrations/versions/0015_knowledge_maintenance.py` — additive run and issue tables.
- `backend/tests/test_knowledge_maintenance.py` — deterministic checks, confidence gates, apply/undo and stale protection.
- `backend/tests/test_knowledge_maintenance_api.py` — route persistence, scope and partial-run behavior.
- `prompts/knowledge_maintenance.txt` — bounded JSON audit contract.
- `frontend/src/components/KnowledgeMaintenance.tsx` — A-style issue-first workbench.
- `frontend/src/components/knowledge-maintenance.css` — focused styling and responsive detail panel.
- `frontend/tests/knowledge-maintenance.spec.ts` — Playwright coverage of the workbench and repair flow.
- `docs/superpowers/evidence/2026-10-25-knowledge-network-maintenance.md` — live verification record.

Modify:

- `backend/app/models.py` — add `KnowledgeMaintenanceRun` and `KnowledgeMaintenanceIssue` models.
- `backend/app/api/routes.py` and `backend/app/main.py` — mount the maintenance router and recover queued work on startup.
- `backend/app/services/background_research.py` — persist and schedule maintenance jobs with existing quota/reading gates.
- `backend/app/services/research_policy.py` — add the maintenance call budget and explicit pause reasons.
- `backend/app/research_schemas.py` — add maintenance settings and scope controls.
- `backend/app/providers/base.py`, `backend/app/providers/openai_compatible.py`, `backend/app/providers/codex_subscription.py` — expose bounded structured maintenance calls and usage accounting.
- `backend/app/services/knowledge_curation.py` and `backend/app/services/knowledge_identity.py` — expose safe inverse operations and preserve manual-change guards.
- `backend/app/lib` equivalent API client is not present; update `frontend/src/lib/api.ts` and `frontend/src/types.ts` directly.
- `frontend/src/pages/KnowledgePage.tsx` — add the maintenance tab and load/run refresh logic.
- `frontend/src/locales/zh-CN.json` and `frontend/src/locales/en-US.json` — add concise labels, statuses and error messages.
- `backend/tests/test_background_research.py`, `backend/tests/test_knowledge_curation.py`, and `backend/tests/test_migrations.py` — extend existing scheduler and schema regressions.

## Task 1: Lock the public data contract and migration

**Files:**

- Create: `backend/app/maintenance_schemas.py`
- Modify: `backend/app/models.py`
- Create: `backend/migrations/versions/0015_knowledge_maintenance.py`
- Test: `backend/tests/test_migrations.py`

- [ ] **Step 1: Write failing schema/model tests.** Add tests that construct a run with `scope_type`, `status`, counters and a source fingerprint, then an issue with `kind`, `confidence_basis_json`, `auto_eligible`, evidence, proposed action and status. Assert JSON fields default to `{}` or `[]`, and that a run can own multiple issues.

- [ ] **Step 2: Run the focused tests and verify they fail.**

  Run: `pytest backend/tests/test_migrations.py -k maintenance -v`

  Expected: FAIL because the two ORM models and migration do not exist.

- [ ] **Step 3: Add typed schemas and ORM models.** Use these stable statuses and fields:

  ```python
  MaintenanceRunStatus = Literal['queued', 'running', 'complete', 'partial', 'failed', 'cancelled']
  MaintenanceIssueStatus = Literal['proposed', 'auto_applied', 'needs_review', 'accepted', 'rejected', 'stale', 'undone']
  MaintenanceKind = Literal['identity', 'relation', 'evidence', 'coverage', 'importance', 'structure']
  ```

  `KnowledgeMaintenanceRun` stores `id`, scope fields, `allow_external`, provider/prompt metadata, fingerprint, lifecycle timestamps, counters and error. `KnowledgeMaintenanceIssue` stores `run_id`, kind, severity, status, confidence, auto flag, subject/evidence/lead/action JSON, readable summary/reasoning, fingerprint and applied change IDs. Add indexes on `(status, created_at)`, `(run_id, status)`, and `source_fingerprint`.

- [ ] **Step 4: Write the additive Alembic migration.** Create both tables with foreign key from issue to run and `ON DELETE CASCADE`; keep all existing tables untouched. The downgrade drops issues before runs.

- [ ] **Step 5: Run migration and model tests.**

  Run: `pytest backend/tests/test_migrations.py -k maintenance -v`

  Expected: PASS, with the existing migration suite still green.

- [ ] **Step 6: Commit the contract.**

  ```powershell
  git add backend/app/models.py backend/app/maintenance_schemas.py backend/migrations/versions/0015_knowledge_maintenance.py backend/tests/test_migrations.py
  git commit -m "feat: persist knowledge maintenance runs"
  ```

## Task 2: Implement deterministic audits and confidence gating

**Files:**

- Create: `backend/app/services/knowledge_maintenance.py`
- Modify: `backend/app/services/knowledge_curation.py`
- Modify: `backend/app/services/knowledge_identity.py`
- Create: `backend/tests/test_knowledge_maintenance.py`

- [ ] **Step 1: Add failing tests for deterministic findings.** Cover exact same-type entity identities, same-paper duplicate candidates, duplicate relations with identical resolved endpoints, dangling/rejected endpoints, invalid quotes, conflicting aliases, and isolated entities. Assert that source-grounded coverage warnings require an actual mention and never treat absence alone as a defect.

- [ ] **Step 2: Add failing tests for the gate.** Assert that exact normalized identity with no human edit is auto-eligible; fuzzy match, a manual `edit_entity` change, a rejected subject, an external-only citation, or a relation predicate rewrite is review-only. Assert that two distinct valid source chunks can satisfy the strong-evidence requirement for an allowed action.

- [ ] **Step 3: Implement stable fingerprints.** Hash the ordered relevant row snapshots, evidence quotes, and current `KnowledgeChange` IDs. Store the fingerprint on the run and each issue. A proposal must be marked stale when any subject snapshot or evidence quote changes before application.

- [ ] **Step 4: Implement `collect_deterministic_findings(session, scope)`.** Return typed internal finding dictionaries for:

  - exact same-type canonical identities and paper-local candidates;
  - duplicate relation keys `(paper_id, source_candidate_id, relation, target_candidate_id)`;
  - missing, rejected or cross-paper endpoints;
  - evidence JSON that points to a missing chunk or quote not present in the owning chunk;
  - aliases that collide within a type while excluding ambiguous short aliases;
  - unresolved relations and orphan entities that have no live candidate/evidence.

  Reuse `normalize_name`, `archived_row`, `_valid_evidence`, and `snapshot`; do not duplicate merge semantics.

- [ ] **Step 5: Implement `confidence_gate(finding, proposal, session)`.** Return `auto_eligible`, `confidence_basis`, `risk`, and a human-readable reason. Allow only the five low-risk operations from the design. Check human `KnowledgeChange` actions, rejected status, valid evidence, current fingerprints, and distinct-source evidence before returning true.

- [ ] **Step 6: Implement safe apply/undo primitives.** Add `apply_issue` and `undo_issue` using one database transaction per issue. Call existing curation/identity functions; record every changed subject through `KnowledgeChange`; attach the created change IDs to the issue. Undo must compare current snapshots with the issue's after snapshots and set `stale` instead of overwriting a later edit.

- [ ] **Step 7: Run focused tests.**

  Run: `pytest backend/tests/test_knowledge_maintenance.py -v`

  Expected: PASS for all deterministic and gating cases.

- [ ] **Step 8: Commit the audit service.**

  ```powershell
  git add backend/app/services/knowledge_maintenance.py backend/app/services/knowledge_curation.py backend/app/services/knowledge_identity.py backend/tests/test_knowledge_maintenance.py
  git commit -m "feat: audit and gate knowledge network repairs"
  ```

## Task 3: Add bounded model auditing with provenance

**Files:**

- Create: `prompts/knowledge_maintenance.txt`
- Modify: `backend/app/providers/base.py`
- Modify: `backend/app/providers/openai_compatible.py`
- Modify: `backend/app/providers/codex_subscription.py`
- Modify: `backend/app/services/knowledge_maintenance.py`
- Test: `backend/tests/test_knowledge_maintenance.py`

- [ ] **Step 1: Write provider tests.** Use the existing fake transport/provider fixtures to assert that a maintenance call sends `store: false`, JSON output mode, a bounded payload, and a bounded output budget; assert malformed JSON and invalid citation IDs produce a retryable/partial result without mutating knowledge.

- [ ] **Step 2: Define the prompt contract.** Require exactly one JSON object containing `issues`, where each issue includes `kind`, `summary`, `reasoning`, `subject_ids`, `citations`, `action`, `confidence`, `confidence_factors`, and optional `external_queries`. Forbid invention, bibliography-only edges, and treating external leads as paper evidence. Limit each bundle to one proposed action and eight citations.

- [ ] **Step 3: Add `audit_knowledge_bundle(...)` to the provider protocol and implementations.** Reuse the existing `complete_json`/Responses streaming path, with `max_output_tokens=2200` and the configured reasoning level. Validate that every citation refers to a sent chunk and that every subject ID belongs to the bundle. Preserve `last_usage` for scheduler accounting.

- [ ] **Step 4: Implement bounded neighborhood assembly.** For each deterministic finding, include at most 20 subjects, one relation hop, 12 source chunks and 24,000 context characters. Cache a successful model result by bundle fingerprint and prompt version. Skip the model entirely when no deterministic or source-grounded signal exists.

- [ ] **Step 5: Merge model proposals with deterministic findings.** Validate source quotes using `_valid_evidence`, run the confidence gate, de-duplicate by `(kind, subject IDs, action)`, and persist external leads separately. A provider failure marks the run partial and leaves local issues available.

- [ ] **Step 6: Test model/provenance behavior.**

  Run: `pytest backend/tests/test_knowledge_maintenance.py -k provider -v`

  Expected: PASS, including no database writes on invalid provider output.

- [ ] **Step 7: Commit the provider integration.**

  ```powershell
  git add prompts/knowledge_maintenance.txt backend/app/providers/base.py backend/app/providers/openai_compatible.py backend/app/providers/codex_subscription.py backend/app/services/knowledge_maintenance.py backend/tests/test_knowledge_maintenance.py
  git commit -m "feat: add bounded model knowledge audits"
  ```

## Task 4: Add run and issue APIs

**Files:**

- Create: `backend/app/api/knowledge_maintenance.py`
- Create: `backend/app/api` route registration changes in `backend/app/api/routes.py`
- Create: `backend/tests/test_knowledge_maintenance_api.py`
- Modify: `backend/app/main.py` only if startup recovery registration is required by the existing pattern.

- [ ] **Step 1: Write failing API tests.** Cover starting a library/collection run, listing runs, retrieving paginated issues, applying safe issues, applying/rejecting one issue, undoing an automatic issue, stale fingerprint responses, and a partial model run that still returns deterministic findings.

- [ ] **Step 2: Implement route schemas and serialization.** Use `MaintenanceRunCreate(scope_type, scope_id, paper_ids, allow_external, force)` and response models that include counts, lifecycle state, issue summaries, evidence, action preview and source navigation metadata.

- [ ] **Step 3: Implement `POST /knowledge/maintenance/runs`.** Create a queued run with scope fingerprint, perform deterministic checks synchronously, then run bounded model checks through the existing provider capacity gate. Persist each issue before returning the run summary so a timeout never loses local findings.

- [ ] **Step 4: Implement apply/reject/undo routes.** Recheck fingerprint and permissions inside the service; return `409` for stale or unsafe direct application and `404` for missing issues. Keep rejected proposals and their evidence.

- [ ] **Step 5: Run API tests.**

  Run: `pytest backend/tests/test_knowledge_maintenance_api.py -v`

  Expected: PASS, with existing knowledge API tests unchanged and green.

- [ ] **Step 6: Commit the API.**

  ```powershell
  git add backend/app/api/knowledge_maintenance.py backend/app/api/routes.py backend/app/main.py backend/tests/test_knowledge_maintenance_api.py
  git commit -m "feat: expose knowledge maintenance runs"
  ```

## Task 5: Extend the scheduler with quota-safe maintenance jobs

**Files:**

- Modify: `backend/app/research_schemas.py`
- Modify: `backend/app/services/research_policy.py`
- Modify: `backend/app/services/background_research.py`
- Modify: `backend/app/models.py` only if a queue relation is needed; prefer using the maintenance run status instead.
- Modify: `backend/app/api/research.py`
- Modify: `backend/tests/test_background_research.py`

- [ ] **Step 1: Write scheduler regression tests.** Assert that maintenance work pauses when reading presence is active, any foreground `IntelligenceTask` is queued/running, Codex authentication/quota is unavailable, the hourly call budget is reached, or the configured stop threshold is crossed. Assert it resumes only after idle time and the start threshold are met, and never runs concurrently with essay/findings work.

- [ ] **Step 2: Add explicit settings.** Extend `ResearchSettings` with `maintenance_enabled`, `maintenance_interval_minutes`, `maintenance_calls_per_run`, and `maintenance_scope` (`library` or `enabled_collections`), validating positive bounds and preserving current defaults when absent from stored JSON.

- [ ] **Step 3: Add maintenance scheduling to `BackgroundResearchWorker`.** Use the existing `_run_lock`, `_eligible`, `profiles.priority.idle`, foreground queue check, subscription quota read, start/stop thresholds, and `calls_per_hour`. Pick maintenance only when no research task is ready, the maintenance interval has elapsed, and a previous run is not queued/running. Persist `reason='maintenance_reading'`, `maintenance_quota'`, `maintenance_foreground_queue'`, `maintenance_up_to_date'`, and `maintenance_error'` so the UI can explain why work waits.

- [ ] **Step 4: Add task lifecycle endpoints.** Expose maintenance settings and a retry/cancel action through the existing research settings/status routes; do not create a second scheduler thread. A cancelled or failed run remains inspectable and can be retried with a fresh fingerprint.

- [ ] **Step 5: Verify quota accounting.** Reuse `record_call`-style usage events with `kind='knowledge_maintenance'`, input/output/total token fields and timestamps. No paid API fallback is allowed when Codex quota reads fail.

- [ ] **Step 6: Run scheduler tests.**

  Run: `pytest backend/tests/test_background_research.py -k maintenance -v`

  Expected: PASS, including recovery of a stranded `running` run after restart.

- [ ] **Step 7: Commit scheduler work.**

  ```powershell
  git add backend/app/research_schemas.py backend/app/services/research_policy.py backend/app/services/background_research.py backend/app/api/research.py backend/tests/test_background_research.py
  git commit -m "feat: schedule quota-safe knowledge maintenance"
  ```

## Task 6: Build the A-style maintenance workbench

**Files:**

- Create: `frontend/src/components/KnowledgeMaintenance.tsx`
- Create: `frontend/src/components/knowledge-maintenance.css`
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/locales/zh-CN.json`
- Modify: `frontend/src/locales/en-US.json`
- Test: `frontend/tests/knowledge-maintenance.spec.ts`

- [ ] **Step 1: Add typed client methods and fixtures.** Add run/issue types and methods for list, detail, start, apply-safe, apply, reject and undo. Keep source quotes and affected-paper navigation as structured fields.

- [ ] **Step 2: Write the Playwright test first.** Seed a run with one auto-eligible duplicate and one review-only relation rewrite. Assert the page shows the two counts, the safe action is the primary button, the detail panel opens without losing the list, the evidence button navigates to the owning paper, applying safe fixes updates the count, and undo restores the issue.

- [ ] **Step 3: Add the maintenance tab.** Keep the existing collection selector and tabs. The new tab loads the latest run only and does not block the other knowledge views. Starting a run shows a progress state and then refreshes the persisted report.

- [ ] **Step 4: Implement the issue-first layout.** Use a four-stat header, a compact filter row, a two-column list/detail layout above 900px, and a stacked detail sheet on narrow screens. Show one readable reason, one evidence quote, one primary action, and a small focused neighborhood map; hide raw JSON and repeated URLs.

- [ ] **Step 5: Add status and accessibility behavior.** Keyboard focus follows the selected issue, Escape closes detail, buttons have explicit labels, severity colors retain text labels, and a stale response preserves the current selection while showing the reason.

- [ ] **Step 6: Run frontend tests and build.**

  Run: `npm --prefix frontend run build` and `npx playwright test frontend/tests/knowledge-maintenance.spec.ts`

  Expected: production build and focused browser test PASS.

- [ ] **Step 7: Commit the workbench.**

  ```powershell
  git add frontend/src/components/KnowledgeMaintenance.tsx frontend/src/components/knowledge-maintenance.css frontend/src/pages/KnowledgePage.tsx frontend/src/lib/api.ts frontend/src/types.ts frontend/src/locales/zh-CN.json frontend/src/locales/en-US.json frontend/tests/knowledge-maintenance.spec.ts
  git commit -m "feat: add knowledge maintenance workbench"
  ```

## Task 7: Integrate settings, documentation and live evidence

**Files:**

- Modify: `frontend/src/pages/LibrarianPage.tsx` or the existing research settings component where `ResearchSettings` is edited.
- Modify: `README.md`
- Create: `docs/superpowers/evidence/2026-10-25-knowledge-network-maintenance.md`
- Modify: `backend/tests/test_migrations.py`, `backend/tests/test_knowledge_api.py`, and `frontend/tests/background-research.spec.ts` only for integration assertions.

- [ ] **Step 1: Add quota controls to the existing settings surface.** Show the maintenance toggle, interval, per-run call cap, scope and current reason. Explain that reading presence, foreground analysis, and stop threshold always suspend the worker. Keep provider selection in the existing model-profile UI.

- [ ] **Step 2: Document the workflow.** Add a short README section covering “体检 → 自动修复 → 审阅少量语义问题 → 撤销”, the quota gates, the fact that external leads are not evidence, and the persisted run/history behavior. Do not expose API keys or internal raw payloads.

- [ ] **Step 3: Run the full verification set.**

  ```powershell
  pytest backend -q
  npm --prefix frontend run build
  npx playwright test frontend/tests/knowledge-maintenance.spec.ts frontend/tests/background-research.spec.ts frontend/tests/librarian-workspace.spec.ts
  git diff --check
  ```

  Expected: backend suite passes, build succeeds, focused browser suites pass, and `git diff --check` produces no new errors.

- [ ] **Step 4: Perform live read-only audit.** Back up the SQLite database using the repository's backup helper, run one maintenance audit against the current library with `allow_external=false`, inspect counts and the first ten issues, and record exact run ID, scope, provider state, quota state and remaining limitations in the evidence file.

- [ ] **Step 5: Apply only deterministic safe repairs on the backup.** Apply the safe subset on the copied database, verify `KnowledgeChange` rows, issue status transitions, relation endpoints and evidence counts, then test undo. Do not apply model-only semantic proposals to the live database during this first rollout.

- [ ] **Step 6: Restart and smoke test the real services.** Use the repository start/stop scripts, verify `http://127.0.0.1:8000/health` and `http://127.0.0.1:5173`, open the knowledge maintenance tab, and confirm scheduler status explains whether it is idle, reading-blocked, quota-blocked or up to date.

- [ ] **Step 7: Commit documentation and evidence.**

  ```powershell
  git add README.md docs/superpowers/evidence/2026-10-25-knowledge-network-maintenance.md frontend/src/pages backend/tests frontend/tests
  git commit -m "docs: verify knowledge maintenance workflow"
  ```

## Plan self-review

- The design's deterministic audit, model audit, confidence gate, provenance, external-lead boundary, reversible application, persistent runs, API, A-style UI, quota monitor and validation requirements each map to Tasks 1–7.
- No task permits direct model writes, deletes evidence, bypasses manual changes, or creates a second scheduler.
- Provider method names, issue statuses, settings names and API route names are consistent across tasks.
- The first live rollout is read-only on the real library and applies deterministic repairs only on a backup, preserving the existing dirty workspace and user data.
