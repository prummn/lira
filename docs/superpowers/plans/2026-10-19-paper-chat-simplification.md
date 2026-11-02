# Paper question drawer simplification

**Goal:** Make a question the primary action, with consistent spacing and context available on demand.

**Design:** Keep the existing warm palette and reader drawer. Use a single 28 px horizontal inset (20 px on small screens). Before the first question, center one composer in the available space. Collapse the attached PDF page or selected passage into one context row; reveal the full preview only on request. Remove suggested question buttons and introductory metadata. Put scope and web permission behind an Options control, preserving their defaults and request fields. After sending, show questions and answers chronologically in a scrollable transcript and keep the composer at the bottom. Render equations with the existing ScientificText component; disclose source passages and request metadata on demand.

**Files:** ExplainPanel.tsx owns conversation, context disclosure, composer and options; explain-panel.css owns isolated layout and typography; both locale files own short labels; explain-chat.spec.ts verifies real user interactions; workspace.spec.ts updates older expectations for the simplified controls.

## Implementation

- [x] Add browser regression coverage and observe failures: initial focus, collapsed preview, hidden settings, image payload, chronological follow-up, draft handling after errors, source navigation, mobile geometry.
- [x] Replace the old stacked markup with a transcript and one composer; retain the existing backend contract and six-turn history limit.
- [x] Consolidate the drawer's CSS in one component stylesheet and remove obsolete rules from styles.css. Keep the preview, conversation and composer on the same inset; respect reduced motion.
- [x] Verify the focused tests and nearby reading regressions, then build the frontend.
- [x] Inspect screenshots of empty, answered, preview, options and narrow layouts; correct visual defects before delivery.

**Results, 2026-10-19:** Nine focused browser checks passed (six new conversation tests and three existing selection/visual/source-navigation checks). Nine neighboring translation/dictionary/highlight checks passed. The production build passed; Vite retains its existing chunk-size warning. Scoped `git diff --check` passed. Visual review covered empty, answered, expanded attachment, options, narrow conversation and 390 px layouts, plus the real Reflexion page 5 in light and dark themes. Screenshots are in `frontend/test-artifacts/chat-*.png` and `.local-runtime/chat-ui-20261019/reflexion-chat-*.png`. Browser response fixtures exercise UI behavior without paid model calls; the real-paper inspection opens the drawer without submitting a question.

**Validation commands (PowerShell, frontend directory):**

```powershell
$env:PATH="$(Resolve-Path ../backend/.venv/Scripts);$env:PATH"
npm run test:e2e -- tests/explain-chat.spec.ts
npm run test:e2e -- tests/workspace.spec.ts -g 'selected passage|selection explanation|current page visual'
npm run build
```

**Scope:** UI and conversation state only. Do not modify provider settings, credentials, PDF extraction or model behavior. Preserve unrelated working changes. Use the user's existing authorization to implement and refine the design in this session.
