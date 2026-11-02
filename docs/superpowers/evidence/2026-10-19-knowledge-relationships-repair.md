# Knowledge relationships repair — verified 2026-10-19

Reflexion (`paper-9e894f40c4924eb7`) cites ReAct (`paper-934bdcb94a0d4147`) in reference [30]. The original reference spans chunks 243–244 on page 11. The live graph now returns that direction, label, and both exact source excerpts. No model request, reimport, reanalysis, or mutation of stored knowledge decisions was needed.

The semantic records remain separate: Reflexion uses ReAct as an Actor in some experiments and compares ReAct + Reflexion against ReAct alone. Neither a citation nor that experimental arrangement automatically establishes a universal successor/extends relation.

## Changes

- `paper_citations.py` projects source-backed citations from local reference chunks, supporting wrapped/page-split titles, arXiv IDs, DOIs and reverse import order. Duplicate stored edges keep their original provenance. Ambiguous titles, partial titles embedded in longer names, body mentions, years and page ranges are excluded. Unnumbered lists expose bounded matched excerpts rather than an entire bibliography.
- Method neighborhoods merge canonical aliases while preserving paper-local roles. CoT is a component under Reflexion and a comparison baseline under ReAct. Parallel/reciprocal relations remain individually inspectable with their direction and evidence.
- The adaptive graph shows one method's neighborhood with optional components, evaluations and ablations. Narrow screens scroll horizontally. Clicking a connection brings its evidence into view; source buttons open the correct PDF page.
- Collection scopes use the overview's scoped relations rather than a global relation request. Rejected candidates and relations stay excluded.
- Removed graph-wide descendant SVG sizing. Footer icons now measure 14×14 px; previously they measured 432–475 px.

## Validation

Backend: `python -m pytest tests/test_paper_citations.py tests/test_knowledge_api.py tests/test_knowledge_presentation.py tests/test_knowledge_service.py tests/test_knowledge_audit.py tests/test_knowledge_extraction.py tests/test_knowledge_models.py tests/test_api.py -q` — **28 passed**.

Browser: `npm run test:e2e -- tests/knowledge-field.spec.ts tests/knowledge-panel.spec.ts` — **6 passed**. Includes a 20-node neighborhood with bounds/overlap checks, rejected-item exclusion, scoped loading, reciprocal edges, local roles, pending resolution, readable evidence, original-page navigation and footer sizing.

`npm run build` — passed. Existing large-bundle advisory remains.

Live library (ports 5173/8000): selected Reflexion, opened its two ReAct semantic records, expanded citation [30], and navigated to the actual Reflexion PDF at page **11**. Switched to ReAct and expanded evaluation. Inspected light/dark appearance and 800 px viewport: map viewport 512 px, scrollable graph 850 px. All footer icons 14×14 px. **No browser page errors**.

Ignored local artifacts in `.local-runtime/knowledge-relations-debug/`: `real-ui-verification.json`, `reflexion-after.png`, `reflexion-evidence.png`, `reflexion-narrow.png`, `reflexion-dark.png`, `react-after.png`, and the before screenshot.

Independent review identified local-role loss, overlapping reciprocal paths, embedded-title false positives, and misleading inferred-citation provenance. Each was addressed and covered by a regression. A further real-library check caught year/page-range markers in unnumbered bibliographies; those now have dedicated regressions too.

Citation matching is intentionally conservative: identifiers or distinctive complete titles with source boundaries are required. Short/ambiguous or damaged references can remain unmatched. This projection describes citations, not inferred method lineage.
