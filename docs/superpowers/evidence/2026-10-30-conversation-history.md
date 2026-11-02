# Reading conversation history

The explanation drawer filtered its History list by the exact current selection. NL2Repo had three intact conversations, but the table conversation displayed only itself. The separate reading archive already supported paper-wide listing and complete source restoration.

The drawer now uses that same archive and restore path. Selecting history restores page, chunk, original text, translated excerpt, figure/table label, bounds, and a locally rendered image when needed. The selection-specific hook still controls automatic restoration and New chat, so a fresh passage does not inherit an unrelated conversation. A restore generation prevents stale requests from replacing a newer selection and forces a fresh panel when returning to the same saved conversation after New chat.

## Verification

- Added a real API/SQLite browser regression with original-text, translated-text and visual conversations, plus another paper's conversation to verify isolation. Before the fix, the expected three entries were absent for a fresh selection.
- Verified follow-ups against the real API persist to the correct conversation with the correct context. Verified image cropping, current selection indicator, New chat, minimize/reopen, and returning to the same saved conversation after New chat. The last case reproduced a blank-transcript bug before the restore-generation fix.
- Conversation persistence and explanation UI suites: **20 passed**, using a disposable database and deterministic local providers. Final run disabled tracing to reduce memory use after earlier test-process memory failures.
- TypeScript and production Vite build passed. Build output is in the system temporary directory; Vite reports its existing large-chunk warning.
- Read-only live browser verification opened all three existing NL2Repo conversations (pages 13, 3, and 2), checked their full saved turn counts, source restoration, the Table 7 image, and current history marker. All three remained accessible after reload.
- Menu bounds checked at widths 1440, 780 and 390; screenshots visually inspected at desktop and narrow widths. No page errors.
- Live browser writes were intercepted, including presence/activity signals. No question submitted and no personal model quota used during live verification. Existing backend/frontend processes on ports 8000/5173 were preserved.

Temporary evidence: `C:/Users/15039/AppData/Local/Temp/lira-history-live.json`, `lira-history-live-1440.png`, `lira-history-live-390.png`, and `lira-history-regression-3.log`.
