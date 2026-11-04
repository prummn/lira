# Quota-Native Background Scheduler Implementation Plan

> **For agentic workers:** Implement inline in this session. Preserve existing uncommitted work in the checkout.

**Goal:** Let optional research, knowledge maintenance, and full-text pretranslation use available official quota without extra local hourly or estimated daily cutoffs.

**Architecture:** Use reported official short/long quota windows and existing start/stop/reserve thresholds as the only quota gates. Keep foreground priority, configured concurrency, and provider-error backoff; retain `calls_per_hour` only to load legacy settings, but stop enforcing it. Remove the estimated daily ledger from runtime status and UI.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React, TypeScript, Playwright.

---

### Task 1: Prove quota readings override legacy local budgets

**Files:** `backend/tests/test_optional_concurrency.py`

- [x] Add tests with `calls_per_hour=1`, recent persisted calls, an exhausted legacy daily ledger, and official quota above all configured thresholds; `_eligible()` must allow the task.
- [x] Run the tests before and after removing the old gates; they failed before the change and pass afterward.

### Task 2: Remove duplicate admission gates

**Files:** `backend/app/services/background_research.py`, `backend/app/services/research_policy.py`, `backend/app/services/translation_queue.py`, `backend/app/services/knowledge_maintenance.py`

- [x] Remove daily-ledger checks and hourly-count reservations from research, maintenance, and full translation paths.
- [x] Keep the pre-generation callback for policy/foreground validation, but stop counting calls as a local quota limit.
- [x] Keep call timestamps for history and fair task ordering; retain cooldown handling for provider errors.
- [x] Run focused tests for the quota-native admission and queue execution.

### Task 3: Remove misleading budget controls and status

**Files:** `backend/app/research_schemas.py`, `frontend/src/types.ts`, `frontend/src/components/CollectionResearch.tsx`, `frontend/src/components/ResearchBudget.tsx`, `frontend/src/components/collection-research.css`, `frontend/src/pages/background-tasks.css`, `frontend/src/locales/zh-CN.json`, `frontend/src/locales/en-US.json`

- [x] Ignore legacy `calls_per_hour` on input, remove its editable control, and remove estimated daily-budget status and meter.
- [x] Explain that backend admission follows official quota windows and the configured reserve line.
- [x] Run frontend status/settings tests and production build.

### Task 4: Regression and compatibility verification

**Files:** `backend/tests/test_research_daily.py`, `backend/tests/test_research_agenda.py`, `backend/tests/test_translation_queue.py`, `backend/tests/test_optional_concurrency.py`, `frontend/tests/background-research.spec.ts`

- [x] Replace assertions for local hourly/daily cutoffs with assertions that actual official quota reserve still blocks, while calls/hour history and old daily ledger do not.
- [x] Run focused backend tests, focused Playwright tests, `git diff --check`, and `npm run build`.
