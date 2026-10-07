# Bounded card science review

**Goal:** Correct the observed loss of scientific conditions without repeating successful paper-analysis stages.

**Architecture:** Build an unused review helper and contract tests while the v5 trial runs; integrate into the harness only after all six current tasks reach a terminal state. Use immutable original-source catalogs, up to four bounded review batches (12 entries and 36,000 payload characters each), strict local replacement validation and exact-request caching. The real 34-item RECALL preview requires three batches. Existing transport retries and cancellation remain the sole network-recovery path.

**Tech stack:** Python, SQLite, existing provider harness, pytest, React/Playwright report fixtures.

- [x] Freeze the real failed scientific card and source audit; define scope and budget. Frozen Adaptive-RAG and RECALL cards and PDF hashes are recorded in the ignored trial directory.
- [x] Write failing contracts for overview/risk selection, bounded source context, supplementary evidence, decisions, immutable unrelated slots, missing/duplicate/foreign replies and correct TLDR cardinality.
- [x] Implement `backend/app/providers/science_review.py` and `prompts/paper_review.txt` without importing them into the active harness. Distinguish exact old quote IDs from the larger supplemental passage; RED/GREEN regression and independent request-identity/offset/budget review passed.
- [x] Let the six-paper v5 trial finish and save its terminal evidence and scientific limits. Four completed, two partial; all 917 original quotes/geometry/claim mappings verified, while independent PDF audits found substantive scope and internal-consistency issues.
- [x] Test then integrate bounded review, typed recoveries, accurate usage, partial-state semantics and cache reuse; version the analysis fingerprint while preserving the extraction/reduction/synthesis requests. Full backend442 passed; independent science-contract59 passed.
- [x] Add explicit report text and frontend regression for scientific-review scope and unresolved conditions. Full isolated browser suite: 35 passed, one real-import opt-in skipped; build passed.
- [x] Load the sole backend between tasks; complete the real v6 review trial. Six partial tasks retained v5 cards under the old publication rule; 18 remote calls/81 cache hits, 287,281 reported tokens and zero unknown-usage calls. Candidate improvements are not actual published fixes. Publication/context and obsolete stored-section defects are addressed by the subsequent plans.
- [ ] Independently compare corrected Adaptive-RAG claims with the original PDF, and check actual browser navigation.
- [ ] Run required regression/build checks, preserve personal records, document actual costs/limits and commit locally.
