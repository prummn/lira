# Reading paragraph boundary repair — 2026-10-20

## What changed

Reading paragraphs remain derived views over immutable PDF chunks. The layout pass now uses the observed column flow, page order, first-line indentation and typography instead of requiring every continuation to share the same left edge. It recognizes the final column to first column transition across pages, keeps captions and footnotes out of prose, and treats a completed sentence with a superscript marker such as `The Sims.2` as a real paragraph boundary. Scientific prefixes such as `mRNA`, `pH` and `3D` are no longer mistaken for footnote artifacts.

The real Generative Agents paper now reads the introduction in the intended order. The sentence beginning `In this paper, we introduce generative agents` continues from the bottom of the left column into `demonstrate that they produce...` at the top of the right column. The following `A society full...` paragraph remains separate. The `This architecture suggests applications...` paragraph remains intact through `The Sims.2`; the following `By connecting our architecture...` paragraph is separate. The abstract also continues into the unlabelled opposite column without losing its section.

## Conservative model review

Some breaks cannot be decided from geometry alone, especially when a figure, table, footnote or page turn sits between two incomplete prose fragments. The reader marks only eligible boundaries as reviewable. Pressing `检查分段` sends a small decision-only context containing the two source fragments, page/flow metadata and nearby context. The model can return `same_paragraph`, confidence and a reason; it cannot rewrite text, coordinates or paper records. Only an exact, validated ID set with confidence at least 0.90 can join fragments.

Decisions are keyed by a source fingerprint and stored in the existing local model-call cache. Reopening the paper reuses the decision without another call. Source edits invalidate the key. A provider failure, invalid JSON, stale source or forbidden section boundary leaves the derived paragraphs unchanged. The review route checks the selected paragraph's immediate neighboring boundaries before expanding context, so the right edge cannot remain unchecked indefinitely. Selection redirects allow a second selected fragment to follow a merge without changing scroll position. Translation refuses to proceed while a selected unit still has unchecked boundaries.

The model review is deliberately on demand when a reader asks to translate or explicitly checks a segment. This prevents a whole library import from generating a call for every ordinary paragraph while preserving a high-accuracy path for ambiguous passages. A review request now drains the selected unit's connected pending boundaries in small batches (up to eight provider calls), prioritizing the immediate left and right edges. Decisions are held in memory and committed together only after every batch succeeds, so a later timeout cannot leave a half-merged reading unit. A fully cached decision remains readable even while the provider is offline. Existing translation caches remain keyed by the final source text.

## Automated verification

| Check | Result |
| --- | --- |
| Full backend suite after the repair | 690 passed, 1 warning, 162.87 s |
| Paragraph/boundary regression, including long-chain, mid-review outage and offline-cache cases | 36 passed, 1 warning, 9.58 s |
| Reader translation + continuous PDF browser tests | 10 passed, 1.0 min |
| Frontend production build | Passed, 25.62 s |

The focused backend set covers double-column rollover, cross-page flow, captions, superscript footnotes, headings, scientific prefixes, true paragraph boundaries, source immutability, strict model validation, cached decisions, low confidence, stale source changes, forbidden section boundaries, immediate-right-boundary review, selection redirects and provider failures. Browser coverage includes review-before-translation, persisted merged selection, failed review without fragment translation, translation caching, page changes, narrow layout and continuous scrolling.

## Real-library checks

After the latest backend restart, `/api/health` returned `ok`. Read-only reading payloads loaded for:

- Generative Agents: 315 derived paragraphs before live review; 313 after a real cross-figure/cross-page review of its information-diffusion example.
- Reflexion: 176 derived paragraphs.
- ReAct: 204 derived paragraphs.

The configured Codex subscription provider completed the live review with two high-confidence merge decisions, and the decisions were reused from the local cache on the next read. Existing PDF chunks, notes, evidence and translations were not modified; only the derived boundary decision cache changed. A pre-change backup for this iteration is in `D:\paper_reader\.local-runtime\backups\before-paragraph-repair-20261020-102939.db`; the backup was created before the production read checks.

The full suite retains the existing Starlette/httpx deprecation warning and the frontend bundle-size advisory. No commit or push was made.
