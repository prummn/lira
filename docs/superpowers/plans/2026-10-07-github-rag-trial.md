# GitHub RAG collection trial and import repairs

**Goal:** Sequentially import all 17 entries in three complete lists from `awesome-rag/awesome-rag` at commit `cca6aa9ad7f62288eafbb99de908ca7917f36347`, investigate actual failures, and leave a verified collection in the user's workspace.

**Scope:** `2023/benchmark.md`, `2024/benchmark.md`, `2024/survey.md`. Browser-driven URL import, official metadata comparison, PDF rendering and evidence navigation for every entry. Preserve existing user data; snapshot SQLite before the trial and before any repair. Downloads remain local; analysis remains extractive.

**Design:** Keep canonical arXiv IDs for paper identity, but fetch metadata for the exact PDF revision observed in the document. Improve the existing layout parser for explicit abstracts next to figures, inline IEEE abstracts, and unlabeled ACM abstracts bounded by publisher front matter. Preserve original source text, block order and coordinates. Reject explicit placeholder DOIs. Use real layout snapshots as offline regressions, rather than paper-specific title rules.

- [x] Freeze repository files and independent official citation metadata; back up database.
- [x] Import sequentially through the live UI; preserve per-paper results and screenshots.
- [x] Write regression cases from the failures and observe them fail.
- [x] Repair version selection, abstract and heading recognition; verify regressions. Persist the observed revision in migration `0006_arxiv_revision` and clear it on manual identity changes. Prevent Crossref byline fallback across unavailable exact revisions.
- [x] Finish the batch, audit all abstracts and evidence rather than only HTTP status.
- [x] Refresh affected records after backup; regenerate local analysis; compare IDs, content, geometry and user state.
- [x] Retry both affected actual URLs in the live collection; the second required a PDF-only 180-second deadline, verified by a 137.2-second successful transfer. Do not mix duplicate trial records into the user's library.
- [x] Complete final live reader/duplicate checks and publish the validation report. All 17 readers rendered and located first/last evidence; both duplicate downloads returned 409. Final backend 153 passed, default browser 13 passed/1 skipped, strict frontend build exit 0; report: `docs/github-rag-import-validation.md`.

Local card extraction remains a separate quality boundary: original quotes and positions are verified, but methods/results are not guaranteed semantic summaries. The trial exposed and corrected prior-work and diagram-answer selection; missing fields and experiment setup excerpts still require human review.
