# Paper answers: read the paper, then answer the question

The reported appendix answer omits WebShop and most of the appendix structure despite spending 21,705 tokens. The current librarian prompt forbids background knowledge, asks for 2–8 isolated claims, and the frontend repeats a full paper title for each citation. The local Reflexion PDF contains 59,030 extracted characters across 352 chunks and 19 pages; the existing 72-source retrieval cannot supply the entire document.

Use the existing validated citation pipeline with three focused changes. For explicitly scoped single-paper research questions, supply all extracted text when it fits a bounded context, in reading order with a section outline. If it does not fit, retain scoped retrieval and report the actual partial coverage. General knowledge may explain concepts and motivate reading advice, with a distinct background kind; paper-specific assertions still require local originals. Compose coherent sections in Markdown, with priorities and reasoning appropriate to the user's question rather than a fixed number of claim bullets.

Render answers as readable prose, lists, tables and equations. Replace repeated citation tiles with numbered references grouped by paper/page. Selecting a reference reveals only that passage's original sources and a PDF jump. Move provider/usage/verification details into one disclosure. Apply the same Markdown renderer to selection/page chat. Simplify the notebook's question area consistently with the previous drawer redesign.

- [x] Reproduce missing context with a regression containing a low lexical relevance appendix subsection among hundreds of PDF blocks; retain cross-paper scope and quote validation checks.
- [x] Implement complete single-paper text context with honest extraction coverage, stable source IDs and bounded fallback.
- [x] Update answer prompting and background provenance; preserve strict validation of paper facts and comparisons.
- [x] Add readable Markdown and numbered, expandable sources; simplify notebook questioning without breaking cancellation, source navigation or history.
- [x] Verify backend and browser regressions, build, and inspect desktop/narrow layouts.
- [x] Ask the exact appendix question through the configured live provider, assess actual source coverage and response quality, and record the result separately from UI fixtures.

No provider credentials, extracted source text, user feedback, or unrelated knowledge features will be changed. Existing authorization covers implementation and live model trials.

Results: 101 scoped backend tests and 33 browser tests passed. The production build passed with Vite's existing large-chunk warning. Independent review identified geometric interleaving and a combined-context-budget gap; both now have regression coverage. The actual two-column PDF test exercises parsing and importing before checking reading order, without changing stored originals. Complete sources reuse the reading paragraph service's observed layout ranks. The combined serialized source cap also includes notes/cards; overflow retains honest scoped retrieval.

Three real answer calls were made, followed by application-cache UI checks. The last iteration corrected imprecise attribution of body results to an appendix. The final call supplied 352/352 stored Reflexion text chunks (59,030 characters, 19 pages), took 63.4 seconds, and reported 67,595 tokens. It recovered the missing WebShop negative result and covered appendices A–D. See `docs/superpowers/evidence/2026-10-19-paper-answer-quality.md` for evidence and limitations.
