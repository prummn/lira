# Provider Profiles Implementation Plan

> **For agentic workers:** Execute inline with tests and checkpoints; user has authorized autonomous implementation.

**Goal:** Recover ReAct analysis and make multiple model connections usable inside LIRA.

**Architecture:** A local atomic profile store manages named connections and route selection. A provider router retains existing analysis/translation APIs and selects a concrete provider at each network boundary. Cache identities remain concrete-provider identities; reports include concrete provenance. Existing environment configuration remains a migration source.

**Tech Stack:** FastAPI, Pydantic, httpx, SQLAlchemy, React/TypeScript, Playwright, pytest.

- [x] Reproduce ReAct's failed second extraction window, inspect only safe error shape/categories; add adapter regression tests before correcting classification.
- [x] Add `backend/tests/test_provider_profiles.py` for migration, CRUD, secret isolation, persistence failure, hot switching, retryable fallback, nonretryable errors, and per-profile concurrency. Run with `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_provider_profiles.py -q` and confirm missing feature failures.
- [x] Implement atomic store in `backend/app/providers/profiles.py`, route calls through `services/model_calls.py`, endpoints in `backend/app/api/model_settings.py`, contracts in `backend/app/schemas.py`. Preserve legacy endpoints; initialize store in `main.py` with an application context and an explicit worker factory to isolate tests.
- [x] Extend `services/model_calls.py` cache lookup/write to use actual provider identity; record profile provenance in harness calls. Test fallback cache isolation and no false result identity after mixed-provider calls.
- [x] Add Playwright CRUD/switch/form tests in `frontend/tests/model-profiles.spec.ts`; implement dedicated `ModelProfilesSettings.tsx`, API/types/locales and responsive styles. Preserve appearance/storage/shortcuts sections.
- [x] Restart only the existing backend process after confirming no active tasks. Run ReAct via the real task API and inspect terminal coverage, failures, usage, scientific review and retained/published result.
- [x] Run backend suite, frontend E2E and build; review diff and document profile behavior in README. Use independent code review, resolve findings, then commit only scoped source/docs/tests.

Real-run evidence, scope and usage limitations: [provider-profiles-regression.md](../../provider-profiles-regression.md).
