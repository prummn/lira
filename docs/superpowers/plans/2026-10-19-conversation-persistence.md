# Persistent research conversations

**Goal:** Keep paper questions, selection/figure explanations and librarian conversations across navigation, refresh and application restarts, including full answer formatting and source snapshots.

**Design:** Store conversations and turns in SQLite, alongside the existing saved translations/cards/knowledge. Save a question before model work and update the same turn with the completed answer or failure. Opening a chat restores its last conversation for that paper/context; a compact history picker retrieves older conversations and New conversation keeps the old one. Content lives in SQLite; browser storage only remembers the selected conversation/scope. Conversation history sent to a model remains bounded. Page changes do not trigger model calls. Pending work survives navigation; interrupted requests after service restart stay visible and are never automatically repeated.

Existing authorization covers this fix and routine design decisions. Preserve unrelated dirty changes and provider credentials. Old model caches contain hashes and raw model responses, not a recoverable question/conversation archive; do not invent missing history.

- [x] Add failing backend persistence/API regressions for successful answers, errors, scope isolation, replay, restart and source snapshots. Initial six regressions failed before implementation.
- [x] Add conversation/turn models and Alembic migration 0011, typed history endpoints, and a shared save-before/run/save-after service. Wrap all three question routes; retain older API contracts with optional IDs.
- [x] Add a shared client history hook and compact history/new-chat control. Restore paper questions, selection/figure explanations and librarian chats. Keep drafts, cancellation guards and bounded model history.
- [x] Verify navigation and browser-refresh recovery against the actual disposable backend (local paper/explanation mode), plus existing chat/intelligence regressions. Browser librarian uses a real loopback HTTP provider and actual SQLite/API, including finishing after navigation; no personal credentials or paid model requests.
- [x] Run migrations, relevant backend/browser tests, production build and independent code review. Back up the local database, restart the real app and verify stored history survives a backend restart.

**Files:** backend/app/{models.py,schemas.py,library_schemas.py,main.py}; backend/app/api/{conversations.py,librarian.py,papers.py,routes.py}; backend/app/services/conversations.py; backend/migrations/versions/0011_conversations.py; backend/tests/test_conversations.py and test_migrations.py; frontend/src/lib/useConversation.ts and api.ts; frontend/src/components/{ConversationHistory.tsx,PaperQuestion.tsx,ExplainPanel.tsx}; frontend/src/pages/LibrarianPage.tsx; frontend/src/App.tsx and types.ts; locale files; frontend/tests/conversation-persistence.spec.ts.

**Commands:** Backend: `.venv/Scripts/python.exe -m pytest tests/test_conversations.py tests/test_migrations.py tests/test_librarian.py -q`. Browser: put `../backend/.venv/Scripts` on PATH, then `npm run test:e2e -- tests/conversation-persistence.spec.ts tests/research-answer.spec.ts tests/explain-chat.spec.ts tests/intelligence.spec.ts`. Build: `npm run build`.

**Verified results (2026-10-19):**

- Final backend run: 109 passed across conversations, migrations, librarian, paper answer context, persistence, API and external search.
- Browser run: 36 passed. New coverage restores local paper answers/citations across navigation/reload/fresh browser storage, keeps older conversations after New conversation, isolates selected passages and preserves librarian responses after leaving the page. Existing mocked librarian fixture now implements the archive read contract.
- Production build passed. Existing Vite bundle-size warning remains.
- Independent review found Unicode escaping limits, empty selected/global scope collision, stale refresh scope and combined scope API compatibility. All corrected, with added regressions where applicable.
- Backed up the 37-paper personal database with SQLite backup and a successful quick_check before migration. Backup: `.local-runtime/backups/before-conversations-20261019-190416.db`.
- Recovered the known Reflexion appendix question from the previous verified answer artifact, preserving 28 citations, without invoking a model. Saved as paper conversation `chat-65cfb7266f924bb2851320442657663b`. This is recovery of that known retained artifact, not a claim to recover all prior memory-only user questions.
- Restarted the actual app using ownership-checked stop/start scripts. The full archive fingerprint before/after restart matched; actual browser UI opened the recovered answer/history with zero page errors. Service remains at `http://127.0.0.1:5173`.
