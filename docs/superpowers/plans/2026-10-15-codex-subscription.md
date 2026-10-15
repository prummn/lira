# Codex Subscription Implementation Plan

> Execute inline with tests and checkpoints. The user has authorized configuration and autonomous implementation; browser OAuth still requires the user's own sign-in.

**Goal:** Use the user's official ChatGPT-managed Codex quota in LIRA, alongside existing API profiles.

**Architecture:** An isolated official app-server process owns OAuth and account status; stateless official CLI executions implement the existing model transport contract. Profiles retain routing, actual-provider caching, shared capacity and provenance.

**Tech Stack:** Python subprocess/JSON-RPC, FastAPI, React/TypeScript, pytest, Playwright.

- [x] Verify the installed CLI's isolated `initialize` / `account/read` protocol without touching existing login or making a model request.
- [x] Add `backend/tests/test_codex_subscription.py` covering profile creation without API keys, safe account status/login/cancel/logout, environment isolation, CLI output/usage, auth/quota/timeout handling and fallback. First run must demonstrate the missing feature.
- [x] Implement process/RPC lifecycle in `backend/app/providers/codex_account.py` and inference in `backend/app/providers/codex_subscription.py`. Use child-only `CODEX_HOME`, file auth, fixed official provider, no tools, stdin prompts, bounded output, timeout and clean shutdown.
- [x] Extend `backend/app/providers/profiles.py`, `schemas.py`, `api/model_settings.py`, `api/system.py` and `main.py` for profile kind, account endpoints, shared subscription capacity, auth readiness and shutdown. Preserve old profiles/API migration and cache identities.
- [x] Add Playwright subscription login/metadata/no-key/routing cases before implementing the UI. Extend types/API/locales and add a focused `CodexAccountSettings.tsx` component within the existing profile editor.
- [x] Run backend tests, subscription and existing profile E2E, then full frontend regressions and build. Obtain focused independent code review and resolve findings. Final backend 552 passed; full browser 62 passed/1 skipped plus final profile/subscription 6 passed; build passed.
- [x] Update README, restart the backend when idle, prepare an inactive Codex profile and official account login in the working UI. Existing primary stays selected.
- [x] Load final backend code after the first pending OAuth session ended without signing in; confirm health, saved inactive subscription and CLI availability.
- [ ] User completes OAuth. Test one small real request and inspect official account/limit status before marking live setup complete.
- [x] Commit scoped source/docs/tests; keep account storage, runtime files and the user's `test_papers/` out of version control.
