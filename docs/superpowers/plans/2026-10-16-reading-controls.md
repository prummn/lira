# 阅读控制与词典速译 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dictionary-first short-word translation, keep note markers out of PDF text, and make note type/filter/sort controls legible and predictable.

**Architecture:** Keep paragraph translation on the existing model-backed endpoint. Add a bounded dictionary lookup endpoint with normalized-key caching and a small result contract. Keep note filtering and sorting in the reader panel, while sharing type colors with PDF marker classes; compute marker placement from page geometry without changing stored anchors.

**Tech Stack:** FastAPI, httpx bounded public fetch, SQLAlchemy existing cache patterns, React/TypeScript, Playwright.

---

### Task 1: Dictionary-first lookup

**Files:**
- Create/modify: `backend/app/services/dictionary.py`
- Modify: `backend/app/api/papers.py`, `backend/app/schemas.py`
- Modify: `frontend/src/lib/api.ts`, `frontend/src/types.ts`, `frontend/src/pages/ReaderPage.tsx`, `frontend/src/components/TranslationPanel.tsx`
- Test: `backend/tests/test_dictionary.py`, `frontend/tests/translation-reading.spec.ts`

- [ ] Add a failing backend test for a normalized word returning dictionary meanings and a second identical request reusing the cache.
- [ ] Add a failing browser test that selects a short word, opens dictionary lookup, and verifies the paragraph translate endpoint is untouched.
- [ ] Implement the bounded dictionary adapter, safe error contract, API method and compact result popover.
- [ ] Run focused backend and Playwright tests; then run the full suites.

### Task 2: Non-obscuring PDF note markers

**Files:**
- Modify: `frontend/src/components/PdfPage.tsx`, `frontend/src/components/pdf-viewer.css`
- Test: `frontend/tests/reading-notes.spec.ts`

- [ ] Add a failing visual assertion for marker placement beside a highlighted region and away from its source text rectangle.
- [ ] Implement side-aware marker placement with viewport clamping and a narrow-page marker fallback.
- [ ] Verify marker clicks still focus the same note and run reading-note regression tests.

### Task 3: Note type colors, filters, and ordering

**Files:**
- Modify: `frontend/src/components/NotesPanel.tsx`, `frontend/src/components/reading-notes.css`, `frontend/src/locales/zh-CN.json`, `frontend/src/locales/en-US.json`
- Test: `frontend/tests/reading-notes.spec.ts`

- [ ] Add failing tests for type filter, type color classes, default reading-order sorting, and updated-time sorting.
- [ ] Implement stable derived filtering/sorting state with a native select and shared color classes.
- [ ] Verify old anchorless notes remain visible and editable.

### Task 4: Integration verification

- [ ] Run `pytest backend/tests -q`.
- [ ] Run `npx playwright test` with the backend virtual environment on PATH.
- [ ] Run `npm run build` and `git diff --check`.
- [ ] Inspect the dictionary/notes/marker screenshots, restart the idle backend safely, and record results in the regression note.
