# Research activity heatmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a local daily research activity aggregate and a GitHub-style heatmap on the library page that can filter papers touched on a selected day.

**Architecture:** A new SQLite aggregate table stores one row per day, with five counters and unique paper ids. A small API serves a zero-filled date range and records validated activity kinds. The frontend records explicit local UI actions with a once-per-day client dedupe key and renders a dependency-free accessible heatmap component.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, React 18, TypeScript, existing CSS variables and locale dictionaries, Playwright and pytest.

---

### Task 1: Add the daily aggregate model and migration

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/migrations/versions/0009_research_activity.py`
- Test: `backend/tests/test_activity.py`

- [ ] Add `ResearchActivity` with a `Date` primary key, counters for `reading`, `notes`, `language`, `search`, `imports`, and `paper_ids_json`.
- [ ] Add migration `0009_research_activity` after `0008_note_anchors` with a reversible `CREATE TABLE`/`DROP TABLE`.
- [ ] Verify `Database.migrate()` creates the table in the existing isolated test fixture.

### Task 2: Add activity API aggregation and validation

**Files:**
- Create: `backend/app/api/activity.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_activity.py`

- [ ] Add `POST /api/activity` accepting only the five activity kinds and an optional existing `paper_id`; increment the matching counter and append a paper id once per day.
- [ ] Add `GET /api/activity?days=365` returning zero-filled day entries, total activity, active days in the last 30 days, current streak, and day paper ids.
- [ ] Return 422 for an unknown kind and 404 for an unknown paper id; keep activity failures isolated from paper workflows.
- [ ] Test aggregation, zero-filled ranges, streaks, paper id deduplication, and validation.

### Task 3: Add typed client tracking and record activity at real actions

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/researchActivity.ts`
- Modify: `frontend/src/pages/ReaderPage.tsx`
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Modify: `frontend/src/components/QuickTranslationPopover.tsx` if needed for paper context

- [ ] Add typed activity response and API methods.
- [ ] Add a best-effort `recordResearchActivity` helper that deduplicates by local day, kind, paper, and optional query key, removes the dedupe key if the request fails, and never throws into the reading flow.
- [ ] Record reading once per paper/day on reader open, notes after successful saves, paragraph translation after successful completion, search after a successful query, and imports after successful import.
- [ ] Add failing unit or component assertions for dedupe behavior before implementation.

### Task 4: Build the accessible heatmap component

**Files:**
- Create: `frontend/src/components/ResearchActivityHeatmap.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/locales/zh-CN.json`
- Modify: `frontend/src/locales/en-US.json`
- Test: `frontend/tests/research-activity.spec.ts`

- [ ] Render a 53-week CSS grid with month labels, five intensity levels, keyboard-focusable day buttons, native/custom hover details, and a legend.
- [ ] Show current streak, active days in 30 days, and total activity beside the grid.
- [ ] Support loading, unavailable, dark theme, narrow widths, and selected-day clear behavior.
- [ ] Test accessible day labels, level classes, selection callback, and empty days.

### Task 5: Integrate date filtering into the library page

**Files:**
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/research-activity.spec.ts`

- [ ] Load the activity range independently of the paper list; an activity request failure must leave the library usable.
- [ ] Place the heatmap below the library heading/facts and filter the visible paper rows by the selected day's paper ids.
- [ ] Add a clear selected-day control and make the empty result state explain that the day contained activity without a stored paper link.
- [ ] Test a day selection filters rows and clearing restores the list.

### Task 6: Verify the feature

- [ ] Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_activity.py -q`.
- [ ] Run `npm run build` in `frontend`.
- [ ] Run `npx playwright test tests/research-activity.spec.ts tests/reading-notes.spec.ts tests/translation-reading.spec.ts --reporter=line`.
- [ ] Run `git diff --check` and inspect that `test_papers/` remains untouched.
