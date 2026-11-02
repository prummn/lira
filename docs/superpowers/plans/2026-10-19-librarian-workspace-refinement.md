# Librarian workspace refinement

**Goal:** Make the cross-paper librarian a comfortable daily research workspace as the library grows.

**Design:** Use the established warm LIRA palette and a single central reading column. A compact toolbar holds the page name and conversation history/new controls. The empty state centers a quiet invitation and one input. During a conversation, only the transcript scrolls; the composer stays visible below it. Scope is a compact control in the composer, opening a searchable, staged selection dialog. Avoid permanently visible inventory cards, repeated instructions and suggestion grids.

**Architecture:** Keep the existing SQLite conversation API, model prompts, scoped retrieval and provenance checks. `LibrarianPage.tsx` owns request state and transcript interaction. New `LibrarianScopeDialog.tsx` owns unapplied scope selection, searching and incremental rendering; changes only commit on Apply. New `LibrarianSources.tsx` groups actual citations by paper and presents a compact bibliography with links to originals/notes. Dedicated `librarian.css` replaces obsolete librarian styles, and App provides a full-height librarian container. `IntelligenceAnswer` gains an optional source-title display for this cross-paper context; paper reader behavior stays the same.

**Acceptance:** Enter sends, Shift+Enter inserts a line, IME composition never sends. A busy turn immediately shows its question; rapid duplicate submits are ignored. Errors and stopping preserve the unsent draft. Source navigation returns to the saved conversation and reading position. Long answers begin at the question instead of jumping to their end. Scope remains explicit, counts exclude demo papers, custom selection has a 50-paper cap, search matches title/authors/year/tags, and checkbox edits do not reset the active conversation until Apply. Large lists render incrementally. History, sources and selection work within desktop, dark theme and narrow screens. Important actual coverage gaps are visible without expanding diagnostics.

Existing authorization covers design decisions and implementation; proceed without an approval pause. Preserve unrelated dirty work, user data and provider configuration. Do not make paid model requests for UI validation.

- [x] Add browser regressions for readable full-height layout, a large searchable scope, staged/cancelled changes, selection cap, follow-ups/IME/duplicate requests, pending/error states, source reading and short/narrow viewports. Run failing cases first.
- [x] Implement the scope dialog and flat bibliography with localized labels.
- [x] Refine librarian layout, request/focus/scroll behavior and source return position; remove superseded style rules.
- [x] Run librarian, persistence, answer-rendering and workspace regressions; production build; request independent code review and address material findings.
- [x] Inspect light/dark/narrow screenshots and verify the actual local app read-only. Update README and record results.

Review fixes: coalesce conversation creation within each hook generation, prevent the stop button's browser activation from submitting the newly rendered form control, retain focus in an open modal, restore expanded sources/details before restoring transcript scroll, preserve evidence-type labels, and show independent coverage gaps together. Added reproductions failed before these fixes; the seven focused regressions passed afterward. Independent review repeated the delayed-creation and source-return checks with no remaining material findings.

Validation does not call a paid provider. Browser fixtures cover a 320-paper library; persistence checks use SQLite and a deterministic loopback provider. The actual local application is inspected with all non-GET API requests blocked. This work changes the librarian workspace and shared conversation interactions; it does not assess live answer quality or change retrieval/model prompts.

Final verification (2026-10-19):

- `npm run test:e2e -- tests/librarian-workspace.spec.ts tests/conversation-persistence.spec.ts tests/research-answer.spec.ts tests/intelligence.spec.ts tests/explain-chat.spec.ts tests/workspace.spec.ts`: 61 passed (3.3m). Updated old workspace checks to identify their own fixture, address the current knowledge navigation, scope assertions to the latest answer, and explicitly open notes after saving a plain highlight.
- `npm run build`: passed, with the existing bundle-size advisory.
- Scoped `git diff --check`: passed.
- `node .local-runtime/verify_librarian_ui.cjs`: actual application verified; zero page errors, zero non-GET API requests, zero model requests. Inspected light/dark, laptop/mobile, scope dialog and conversation screenshots.
- README now explains scope selection, keyboard submission, grouped references, history and stop behavior.
