# Research activity refinement

**Goal:** Keep frequent translations from saturating the daily heatmap and replace native browser title balloons with a readable, styled day preview.

**Design:** Preserve all existing counters. Derive color from `4*log2(1+reading) + 3*log2(1+notes) + min(language/10,1) + min(search/4,1) + min(imports/5,1)`; levels are zero, positive below 6, 6–12, 12–20, and 20+. Reading and notes receive diminishing returns. Each supporting activity contributes at most one, so translation-only and even all supporting activities alone remain at the lightest active level. This is an activity indicator, not a measure of research quality or time. Existing historical days recalculate without modifying stored counts. Replace the cumulative action count in the headline with reading entries. Current tracking deduplicates opening a paper each day in that browser's localStorage; the server stores raw entries, so these are not unique-paper counts across browsers.

**Interaction and visual design:** A compact dark warm preview appears near the hovered/focused square, through a portal outside scroll containers. Show date, primary reading/note figures, quieter translation/search/import counts and touched paper count. Empty dates show a brief empty state. Clamp to viewport and flip above/below; allow moving over the preview, Escape dismissal, independent hover/focus ownership, scroll/resize repositioning and reduced motion. Dismiss when its anchor leaves the viewport. Short viewports can scroll preview content with the pointer or keyboard while focus stays on the day. Retain clicking the square to filter papers. Native title attributes are removed.

Existing user authorization covers routine design and implementation; preserve unrelated work and stored activity. No model requests or schema migration are necessary.

- [x] Add browser regressions for heavy translations, substantial reading/notes, bulk imports, stored raw counts, hover/focus/Escape, dark theme, viewport edges and existing date filtering. Run before implementation.
- [x] Add a pure level calculation to frontend activity utilities; update heatmap headline, accessible labels and localized descriptions.
- [x] Implement a portal preview with warm dark styling, hover persistence and viewport positioning.
- [x] Run focused browser tests, existing tracking/reading regressions and production build. Inspect screenshots and request code review.
- [x] Verify against actual local activity without modifying user data or using model quota. Record results here.

## Validation

- Initial browser regressions reproduced premature translation saturation and the native title balloon. Additional failing regressions reproduced focus dismissal and inaccessible short-viewport content before those fixes.
- `npm run test:e2e -- tests/research-activity.spec.ts tests/reading-notes.spec.ts tests/translation-reading.spec.ts`: 24 passed, 1 skipped (optional real-PDF fixture unavailable). After the final keyboard-scrolling and reading-label refinements, all 4 heatmap tests passed again.
- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_activity.py -q` (run from backend with relative test path): 3 passed. Stored counters and API behavior are unchanged.
- Final `npm run build`: passed; existing bundle-size advisory remains.
- Independent review found focus/hover ownership and short-viewport overflow issues; both were fixed. Keyboard scrolling was then verified using End while focus remains on the date.
- Light, dark, and 390px viewport screenshots inspected at `frontend/test-artifacts/research-activity-preview-*.png`.
- Read-only live check against the running app passed with 371 cells, an actual active-day preview, no native title, hover persistence, Escape dismissal, zero page errors, and zero non-GET API requests. No model calls or user-data writes. Screenshot: `.local-runtime/heatmap-refinement-live.png`; verification script: `.local-runtime/verify_heatmap_ui.cjs`.
- README now explains color meaning, day inspection/filtering, and the reading-record unit.
