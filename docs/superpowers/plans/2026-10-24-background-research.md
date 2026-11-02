# Background Research Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Preserve the existing working tree; do not commit or push.

**Goal:** Deliver a persistent collection essay that advances during spare official allowance and yields to reading.

**Architecture:** A separate finite worker stores source snapshots, synthesis, draft and reviewed revisions in SQLite. A shared priority coordinator preempts only optional work; foreground provider routes stay intact. Collection UI reads persisted state and offers scope, revisions, source navigation and quota controls.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, official Codex CLI, React/TypeScript, existing Markdown/KaTeX, pytest, Playwright.

## 1. Priority and quota policy
- [x] Add `backend/tests/test_research_policy.py`: stale/missing quota blocks, actual windows/buckets honored, start/stop hysteresis, foreground cancellation releases single-account slot.
- [x] Run `python -m pytest tests/test_research_policy.py -q` in backend; expect failure for missing policy/coordinator.
- [x] Create `services/research_policy.py` and `providers/priority.py`; wire cancellation polling in `codex_subscription.py` and priority at `profiles.py` capacity boundary. Extend `_limits` to preserve multi-bucket identity.
- [x] Repeat policy tests and existing `test_codex_subscription.py`; expect passing.

## 2. Durable research pipeline
- [x] Add `backend/tests/test_background_research.py`: scoped input, dedup, checkpoints, cancellation, stale-source rejection, bad quote rejection, previous revision preservation, restart recovery, retry bounds and API validation.
- [x] Run focused tests and see missing-feature failure.
- [x] Add migration `0013_background_research`, models and `research_schemas.py`. Create `services/research_materials.py` for immutable original-text snapshots/fingerprints and `services/background_research.py` for bounded tasks and publication. Keep API orchestration in `api/research.py`.
- [x] Register lifespan and HTTP foreground signals in `main.py`; default disabled until a scope/profile is selected. Tasks are queued by fingerprint, not timers; automatic planning is the finite synthesis stage.
- [x] Run focused backend tests plus migration tests; expect passing and intact prior rows.

## 3. Collection reading experience
- [x] Add Playwright coverage for scope setup, persistence across navigation, essay versions, source links and keyboard/mobile interactions.
- [x] Add typed API/types, `components/CollectionResearch.tsx` and `collection-research.css`; embed in `LibraryPage.tsx`. Reuse Markdown with citation callback. Add short global status/settings entry and reading heartbeat in `App.tsx`.
- [x] Run production build and focused browser tests; inspect warm light/dark and narrow layouts with real screenshots.

## 4. Real trial and completion
- [x] Backup live SQLite with its backup API, restart through existing scripts and check health.
- [x] Select current official profile and Memory collection, perform bounded real pipeline trial, inspect actual article/source support and preemption; leave safe automatic policy enabled for selected scope.
- [x] Run full backend suite, relevant reading/collection browser regressions, build, live health. Record evidence and limitations in `docs/superpowers/evidence/2026-10-24-background-research.md`; document usage in README.
