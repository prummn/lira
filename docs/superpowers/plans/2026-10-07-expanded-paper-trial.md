# Expanded Real-Paper Trial and Repairs

**Goal:** Exercise more real papers through the existing import, full-text analysis and cross-paper librarian, and repair defects reproduced by those papers.

**Architecture:** Keep the approved local-first application and single persistent analysis worker. Use the running API, actual PDFs and an SQLite consistency backup. Record rejected evidence without loosening citation or provenance validation; successful model stages remain reusable.

**Execution:** Continue inline under the user's authorization to test and repair autonomously. No new product redesign or deployment. Credentials, PDFs, SQLite and raw trial artifacts stay outside Git.

**Observed claim repair:** Reuse one bounded, own-citations-only review for unmatched technical markers and exclusive conditions reproduced in actual answers. A local blacklist would discard supported claims; reviewing every answer would add unnecessary calls. Targeted review preserves the approved quality-first workflow without adding a recursive agent loop. Unknown sources remain rejected, accepted outputs are validated again, and stable requests reuse the reviewed stage.

## Baseline and real input

- [x] Verify running services and record the current library, task history and latest GraphRAG card in `.local-runtime/expanded-trial-20261007/`.
- [x] Make `before-expansion.db` using SQLite's backup API before changing the library.
- [x] Verify method-paper links against the frozen `awesome-rag/awesome-rag` GitHub source; import six methods by `/api/papers/import-url` with analysis disabled, checking title, authors, page count and PDF availability. Record transient download errors and explicit retries.
- [x] Queue a representative subset of new methods plus existing RECALL, CRUD-RAG and CodeRAG-Bench. Keep one worker; save terminal reports and actual usage. Seven terminal outcomes: one completed, one partial, five failed; no queued/running tasks remain. Terminal failure is a trial result, not successful analysis.

## Evidence-driven repairs

- [x] Audit existing GraphRAG and new cards against local chunks, page coordinates and cited claims. Inspect representative scientific statements and table/formula conditions independently of literal quote checks.
- [x] For each reproduced application defect, trace the import/extraction/reduction/synthesis/retrieval boundary. Save a sanitized minimal case, write a failing regression, run it, make the focused fix and rerun it. Nine repairs recorded; upstream transport and incomplete model evidence remain explicit limits.
- [x] Safely update the running backend between tasks so real verification exercises the revised code. Reuse good stages; cap deliberate retries and report unresolved external failures honestly.
- [x] Ask technical cross-paper questions with original evidence and replay an identical request to verify cache behavior. Exercise real browser status and evidence navigation where a defect affects the interface. Latest method comparison: one bounded review, 6,581 tokens; repeat and live browser both reuse three stages with zero calls.

## Validation and preservation

- [x] Verify pre-existing papers' personal metadata, notes, translations, chunks and collection memberships as a subset of the expanded library. Account explicitly for newly added records and changed machine analyses.
- [x] Update `docs/intelligence-validation.md` and a new expansion report with the real sample, failures, repairs, usage and remaining limits, including the latest published GraphRAG card.
- [x] Run backend tests, TypeScript/Vite build, relevant browser regressions and diff checks. Obtain an independent code review for repairs and address actionable findings. Backend: 312 passed; browser: 27 passed, one opt-in skipped; build passed. Latest independent librarian review: 78 passed, no outstanding findings.
- [x] Commit the reviewed implementation, fixtures, prompts and documents locally without pushing; preserve existing untracked `test_papers/` and keep all runtime, credentials and private data outside Git.
