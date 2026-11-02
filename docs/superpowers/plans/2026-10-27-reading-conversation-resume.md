# Reading conversation resume

Goal: allow researchers to hide selection Q&A while it answers, continue reading, and return without selecting the original passage again.

Design: freeze the original selection or page when opening a question. Keep the active panel mounted while hidden, preserve its draft, and use SQLite conversation summaries to restore submitted questions after navigation or reload. Provide a compact reading-toolbar entry and an on-demand history list with question, page and latest status. Preserve translation text as display context without changing the original-evidence identity. Re-render archived visual pages locally when needed for follow-ups. No duplicate model submission on resume; service restart keeps the existing interrupted state.

- [x] Add failing browser tests for hidden in-flight requests and context isolation, plus backend tests for summary status and translated context.
- [x] Add latest-turn status to read-only summaries and preserve translated display context.
- [x] Add a reading conversation controller, hidden panel lifecycle and direct saved-ID restoration.
- [x] Verify delayed real API generation across navigation/reload, narrow layout, failures and existing chats.
- [x] Build frontend, run relevant backend/browser regressions and document evidence.
