# Bounded card science review

**Goal:** Correct the observed loss of scientific conditions without repeating successful paper-analysis stages.

**Architecture:** Build an unused review helper and contract tests while the v5 trial runs; integrate into the harness only after all six current tasks reach a terminal state. Use immutable original-source catalogs, two bounded review batches, strict local replacement validation and exact-request caching. Existing transport retries and cancellation remain the sole network-recovery path.

**Tech stack:** Python, SQLite, existing provider harness, pytest, React/Playwright report fixtures.

- [ ] Freeze the real failed scientific card and source audit; define scope and budget.
- [ ] Write failing contracts for overview/risk selection, bounded source context, supplementary evidence, decisions, immutable unrelated slots, missing/duplicate/foreign replies and correct TLDR cardinality.
- [ ] Implement `backend/app/providers/science_review.py` and `prompts/paper_review.txt` without importing them into the active harness.
- [ ] Let the six-paper v5 trial finish and save its terminal evidence and scientific limits.
- [ ] Test then integrate bounded review, typed recoveries, accurate usage, partial-state semantics and cache reuse; version the analysis fingerprint while preserving the extraction/reduction/synthesis requests.
- [ ] Add explicit report text and frontend regression for scientific-review scope and unresolved conditions.
- [ ] Load the sole backend between tasks; review cached real cards with no repeated successful extraction/reduction/synthesis.
- [ ] Independently compare corrected Adaptive-RAG claims with the original PDF, and check actual browser navigation.
- [ ] Run required regression/build checks, preserve personal records, document actual costs/limits and commit locally.
