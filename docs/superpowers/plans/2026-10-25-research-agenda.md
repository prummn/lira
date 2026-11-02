# Research Agenda Implementation Plan

**Goal:** Let enabled topics progress from initial findings to finite, source-backed investigations while preventing repeated maintenance work.

**Architecture:** Keep the existing worker and ResearchTask persistence. Add agenda planning and investigation material assembly in a focused service; reuse findings verification/publication and immutable history. Expose agenda state in the existing findings endpoint and a compact expandable UI.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, pytest, React/TypeScript, Playwright.

1. Add failing regressions in `backend/tests/test_research_agenda.py` for bounded scoped plans, duplicate questions, unknown papers, selected full-text sections, persisted planning, dispatch, cancellation, foreground priority and publication. Reproduce maintenance same-snapshot and recursive-proposal waste in maintenance tests.
2. Implement `backend/app/services/research_agenda.py`, `prompts/research_plan.txt` and `prompts/research_investigate.txt`; integrate agenda/ investigation kinds in `background_research.py` and opt-in settings. Reuse `verify_findings` and `publish_findings`.
3. Stop same-snapshot maintenance duplication and audit only the original deterministic findings. Count maintenance calls for every worker job.
4. Add typed agenda state and a collapsible task list to research findings; allow start, retry, cancel, and navigation to published results. Add the global deep-research toggle to research settings.
5. Run focused and full backend tests, frontend build, and agenda browser tests. Restart only the owned backend after verifying idle; enable deep research for existing scopes and observe real planning and one complete investigation.
6. Record exact task IDs, output titles, calls, quota and any remaining queued work in evidence documentation. Preserve unrelated workspace edits and all library content.

## Completion

- [x] Scoped finite planning, full-text investigations, settings and persistence.
- [x] Same-snapshot maintenance deduplication, original-issue filtering and shared attempt budgets.
- [x] Compact task list, saved-result navigation, cancellation and retry.
- [x] Full-source freshness, legacy adoption and user-decision races reproduced and fixed.
- [x] Final backend suite: 804 passed; frontend build and four browser checks passed.
- [x] Real plans for both topics; eight investigations published and independently checked against the local text. Remaining work continues in the service.
- [x] Evidence saved in `docs/superpowers/evidence/2026-10-25-research-agenda.md`.
