# Research Intelligence Harness Implementation Plan

**Goal:** Deliver quality-first full-paper analysis and a local-library AI librarian, integrated with import, reading, notes and evidence navigation.

**Architecture:** Deterministic structure extraction feeds a persistent staged worker. Provider calls cache by content/model/prompt and record actual usage. A read-only retrieval orchestrator combines scoped metadata, FTS, cards and notes; all returned evidence is validated locally.

**Tech stack:** Existing FastAPI/SQLAlchemy/Alembic, httpx, React/TypeScript/PDF.js, SQLite, pytest and Playwright. Work in current development checkout to retain live research data and running app; no external deployment.

## Task 1 — Provider transport and staged full-paper analysis

Files: `backend/app/providers/{base,openai_compatible,harness}.py`, `backend/app/services/{intelligence,structure}.py`, `backend/app/models.py`, migration `0007_intelligence.py`, `prompts/{paper_extract,paper_synthesize}.txt`, `backend/tests/test_intelligence.py`.

- [x] Write tests using httpx MockTransport: late-page source is sent; all windows covered; invalid quotes dropped; cached phase makes zero calls; response usage preserved; invalid/length-truncated output is safe failure. Run targeted pytest and observe failures.
- [x] Add persistent intelligence task and stage cache tables, nullable Paper intelligence state and report. Implement a 12k–24k character window packer that splits oversized chunks with exact offsets and never silently omits full-text chunks.
- [x] Extract per-window cited entries, verify each quote against actual supplied slice, synthesize only from verified entries/original quotes, support bounded recursive reduction for long papers and record coverage. Reuse existing PaperCard persistence with an explicit provider/result, preserving previous ready result on failure.
- [x] Record prompt/completion/cache usage when service reports it; bounded timeouts, safe errors, configurable completion parameter (`max_tokens` / `max_completion_tokens`) and JSON capability. Never persist key or raw upstream errors.
- [x] Run targeted tests and original remote-provider tests; inspect failure/partial boundaries.

## Task 2 — Persistent task worker and API integration

Files: `backend/app/services/intelligence.py`, `backend/app/api/intelligence.py`, `backend/app/api/{papers,system}.py`, `backend/app/{main,schemas}.py`, `backend/tests/test_intelligence_jobs.py`.

- [x] Write failing API tests: opt-out never queues remote; opt-in queues once; duplicate queue deduplicates; cancellation cannot overwrite ready result; interrupted tasks recover on restart; backend failure keeps old analysis. Run tests to observe failure.
- [x] Create single background worker with short DB transactions around network calls; task state and phase persisted, active job uniqueness enforced, cancellation checked between model calls, failures retained with safe messages and retry reuses cache. Register lifecycle startup/shutdown and recovery.
- [x] Add `POST /api/intelligence/tasks` `{paper_ids, force:false}`, `GET /api/intelligence/tasks`, `POST /api/intelligence/tasks/{id}/cancel`, `GET /api/intelligence/overview`; optional `analyze` on URL and file imports defaults false for backwards compatibility.
- [x] Paper API adds `intelligence_status` separate from legacy local `analysis_status`, with latest task/report. Existing imports and personal data remain available.
- [x] Verify job tests, migrations and original workflow tests.

## Task 3 — Read-only cross-paper librarian and single-paper retrieval

Files: `backend/app/services/librarian.py`, `backend/app/api/intelligence.py`, `backend/app/providers/harness.py`, prompts `librarian_plan.txt`, `librarian_answer.txt`, `backend/tests/test_librarian.py`.

- [x] Write failing tests for Chinese question→English search, scope validation, metadata answers without fake PDF citation, multi-paper source IDs, note vs paper sources, forged quotations, insufficient evidence and cache invalidation after notes/cards change.
- [x] Build scoped local catalog; model query planner chooses bounded search terms and candidate IDs only. Metadata/FTS/card/note retrieval returns typed source IDs and paper/chunk geometry, with neighboring context for PDF blocks; never execute model SQL or accept arbitrary tools.
- [x] `POST /api/intelligence/ask` accepts `{question, collection_id?, paper_ids?, history?}`. Response includes cited claim segments, catalog/quote provenance, retrieved papers, coverage and usage. Validate each source by type and scope, require original quotes for semantic paper claims, label user and inferred sources. Single-paper Notebook uses same retrieval route.
- [x] Use limited recent conversation, refreshed current-library signature and exact request cache; unchanged repeat has no remote calls. Error/empty/partial states remain explicit.
- [x] Run librarian and integration tests.

## Task 4 — Import choices, AI states, Notebook and librarian UI

Files: `frontend/src/{types,App}.tsx`, `lib/{api,useWorkspace}.ts`, components `AnalysisControl.tsx`, `AnalysisBadge.tsx`, `ImportFilesDialog.tsx`, `ImportUrlDialog.tsx`, pages `LibrarianPage.tsx`, `LibraryPage.tsx`, `ReaderPage.tsx`, `SettingsPage.tsx`, locales and `styles.css`, `frontend/tests/intelligence.spec.ts`.

- [x] Write meaningful Playwright scenarios for URL/file batch opt-out, remote queue/progress/cancel and librarian multi-paper citations. Use isolated remote-response fixtures, clearly separate these tests from live provider quality.
- [x] Import dialog offers one analysis checkbox for the batch, remembered preference and configured capability; lists distinct AI status including never analyzed locally extracted papers. Add batch selected-paper analysis and active-task polling only while work remains.
- [x] Notebook shows task progress, retry/cancel, coverage/usage, cached original card while task runs. Use claim-level evidence links. Librarian is a scoped conversation workspace with knowledge inventory context, source links and recent thread; citations open the matching paper/page.
- [x] Keep Chinese/English locale parity, restrained desktop styling, shallow component hierarchy and loading/error/empty/cancel states. Check 1080 and 1440 viewport, strict TypeScript build.
- [x] Run Playwright, original suite and build.

## Task 5 — Live validation, review and documentation

Files: ignored `.local-runtime/intelligence-trial/`, tracked `docs/intelligence-validation.md`, README, user guide and implementation status.

- [x] Obtain confirmed SpacetimeAI URL/model without transmitting credentials to guessed hosts. Select 2–4 representative real papers including a long survey; backup SQLite before migration and machine analysis changes.
- [x] Actually analyze and ask Chinese technical questions, multi-paper comparison and personal-metadata queries. Validate actual source quotations and inspect scientific conclusions; save only sanitized usage/results/screenshots. Repeat identical operation to demonstrate zero-call cache.
- [x] Review spec compliance then code quality using a reviewer; fix important issues and recheck. Run complete pytest, TypeScript/Vite, default Playwright and live UI evidence navigation.
- [x] Update approved design/task checkboxes and docs with actual results and limits; local commit only verified code. Preserve user PDF directory, research database and secrets outside version control.

Validation closeout: RGB and ARES retain partial cards, Ragas completed with zero-call replay; GraphRAG extraction covered 9/9 windows but reduction failed safely upstream and is not counted as a completed card. Cross-paper comparison, scoped inventory, empty-note abstention and live citation navigation were checked. Independent review fixes cover late cancellation responses, reasoning-parameter omission and bounded JSON reads. Final checks: 291 backend tests, 27 browser tests (1 opt-in skipped), TypeScript/Vite build and diff whitespace check. Local develop commit; PDFs, database, runtime credentials and trial artifacts remain outside version control.
