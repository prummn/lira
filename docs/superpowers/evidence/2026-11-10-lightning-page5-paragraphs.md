# Agent Lightning: page 5 paragraph recovery

## Reproduction

Paper `paper-7ca1c77cfaa945e9`, **Agent Lightning v1.0: Towards Harnessed Agentic RL**, PDF page 5. Compared the original PDF rendering, immutable stored chunks, exact PDF lines/fonts/coordinates, and the reading API.

The reading projection exposed 27 units on this page. Inline variables/subscripts fragmented running prose; some short formula fragments and the words “The response returned / to the harness” were discarded. Equations (8) and (9) lost fragments because their prefix-relation operator was absent from the math-character recognizer. Numbered items (1)–(3) split at their hanging continuation lines. A source block could also contain an equation tail followed by a new indented paragraph, which needs a source-range split.

## Repair

- Recognize mathematical operators across the Unicode math ranges and use observed mathematical fonts to identify variable/subscript fragments without an explicit operator.
- Preserve those fragments through the short-label/table filter, retaining their actual source text and bounds.
- Keep hanging continuation lines with their numbered item using line geometry and an unfinished preceding sentence.
- Split mixed formula/prose blocks at an observed new paragraph relative to the surrounding column margin. Require complete-line membership when matching source slices to typography; a single `i` must not match every later sentence containing that character.
- Keep fresh prose separate from a preceding numbered display equation. Retain existing column/page and unrelated-diagram guards.

No PDF, stored chunk, original evidence coordinate, note or chat record was rewritten. Paragraph IDs continue to derive from exact source slices. Old translations remain stored; changed paragraph sources require fresh translations.

## Verification

- Added a compact fixture of actual page-5 chunks, lines, fonts and geometry, without depending on the local paper library or a downloaded PDF.
- Four real-layout regressions failed before implementation: source conservation, inline continuity, numbered-item continuity, and complete display-equation grouping.
- Final suite: `test_reading_paragraphs.py`, `test_reading_boundary_review.py`, `test_translation_queue.py`, `test_selection_layout.py` — **148 passed**, one existing Starlette deprecation warning.
- Exact source-slice conservation covers every page-5 body chunk, including previously discarded fragments; only the printed page number is omitted.
- Direct base reconstruction reduced page 5 from 27 to 16 reading units. Visual inspection of the original page and before/after anchor overlays confirmed the repaired prose, equations and lists. Existing model boundary decisions can further combine appropriate units; a later live response had 15 units.
- Restarted the production service successfully using the existing frontend build. A new browser session opened page 5 in bilingual mode and selected the restored paragraph.
- Five existing translations initially matched the new page-5 projection. Enqueued only the other 11 page-5 units as selected background work (`translation-job-2239892fa6af482faf276bafbca6ad74`), keeping the already completed full translation and all saved results.
- Final monitoring confirmed the repair job **completed 11/11 with zero failures**. A fresh reading API returned **15 page-5 units, all 15 with saved translations, no translation errors** after model boundary projection. A fresh browser session opened the repaired “where the harness sends…” paragraph and verified the persisted full translation, including two rendered LaTeX expressions. Screenshot: `.local-runtime/lightning-page5-live-translated.png`.
- `git diff --check` passed with line-ending normalization warnings only.

Local visual checks (untracked runtime artifacts): `.local-runtime/lightning-page5.png`, `lightning-page5-paragraph-comparison.png`, `lightning-page5-live-repaired.png`.
