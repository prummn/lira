# Reading First Implementation Plan

**Goal:** Deliver reading preparation before deep analysis without losing source integrity or foreground responsiveness.

**Architecture:** Reuse persistent IntelligenceTask and TranslationJob checkpoints. Add request-priority admission to existing profile capacity gates, and a compact, explicitly marked synthesis evidence view over the immutable original evidence pool.

**Tech Stack:** FastAPI, SQLAlchemy/SQLite, Python threading/contextvars, React/TypeScript, pytest, Playwright.

- [x] Add isolated scheduling regressions in `backend/tests/test_reading_first.py` and `test_provider_profiles.py`; confirm failures before implementation.
- [x] Extend `providers/priority.py` and `profiles.py` for cooperative request-boundary priority and foreground capacity reservation. Verify threaded order and capacity.
- [x] Extend `services/translation_queue.py` to handle explicitly requested full translation with selected API or Codex profile, and preserve current results on foreground interaction. Update intentional preemption expectations.
- [x] Connect `services/intelligence.py`, `main.py` and import endpoints to persisted reading preparation and dependency release; support manual analysis override. Verify cache, restart, failed/paused translation behavior.
- [x] Bound synthesis evidence delivery in `providers/harness.py` without dropping facts, weakening citations, or changing extraction checkpoints. Verify science review uses originals.
- [x] Update import, analysis, background, and translation UI copy and phase labels, then build and run relevant browser regressions.
- [x] Run focused backend regression, inspect current live task before any restart, and verify the updated running application using isolated data or read-only checks. Record concrete evidence and remaining limitations.

Execution stays in the existing checkout as requested in session history; tests use temporary stores. Existing unrelated changes are preserved; no blanket commit/reset or new project tree.
