# Concurrent background queue implementation plan

**Goal:** Use a default official concurrency of four and keep reading preparation,
body pretranslation, analysis and knowledge integration progressing automatically.

**Approved direction:** The user approved increasing default concurrency and
optimizing the existing queue after the scheduler audit. Execute in this checkout
without changing quota reserves, connection identities or library data.

**Architecture:** Keep the account-wide priority gate as the only request capacity
authority. Replace permanent foreground reservation with priority at admission.
Use bounded translation and intelligence worker pools; retain one serialized lane
for optional research and knowledge-network mutations. Claim each translation
work unit once, allow stable paragraphs of one paper to run together, and acquire
exclusive paper access for paragraph-boundary changes. Preserve import workflow
dependencies, per-paragraph persistence and analysis checkpoints.

**Tech stack:** Python threading, SQLAlchemy/SQLite WAL, FastAPI, React, Playwright.

1. [x] Add regression tests for four default slots, foreground overtaking,
   background borrowing, lower limits and runtime rate-limit reduction.
2. [x] Add regression tests for concurrent paragraph completion, shared-work
   deduplication, boundary review exclusivity and independently claimed analyses.
   Run with `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_concurrent_queue.py -q`;
   confirm the old implementation fails before editing production code.
3. [x] Implement bounded workers and short claim locks. Keep source/configuration
   validation before publishing and ensure deferred work does not stay running.
4. [x] Update official concurrency API and settings UI to 1–8, default 4. Preserve
   explicit persisted limits; set this installation to 4 through the normal API.
5. [x] Add scheduler visibility (configured/effective/active/waiting) and update
   guide text. Use rate-limit feedback to reduce effective admission temporarily.
6. [x] Run affected backend suites, settings/background browser tests and build.
   Exercise four real official requests with bounded output and no library writes.
7. [x] Load the verified code in the formal service at a safe request boundary,
   verify quota settings unchanged, inspect persisted progress and record evidence.

Acceptance: four independent requests can overlap; foreground wins the next free
slot; no paid duplication for identical queued/direct translations; review cannot
change a paragraph while its translation is in flight; source analysis and quota
failures remain recoverable; lowering concurrency never cancels an in-flight call.
