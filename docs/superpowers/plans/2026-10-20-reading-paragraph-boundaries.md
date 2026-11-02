# Reading paragraph boundary repair

**Goal:** Read double-column and figure-interrupted paragraphs as complete units, with cached model review for ambiguous boundaries.

**Architecture:** Keep stored chunks, evidence and PDF coordinates immutable. Derive reading units from observed column flow, first-line indentation and line spacing. A separate boundary-review service asks the configured model only about adjacent, eligible source fragments, validates a small decision-only response, and caches source-fingerprinted decisions in the existing model call cache. Only confident merges change derived paragraphs. The reader checks suspicious boundaries before translation and exposes a manual check without resetting reading position.

**Scope decisions:** Continue in the integrated workspace, preserving unrelated changes. No commits or pushes. No automatic whole-paper model pass. Model output can choose boundaries but cannot rewrite source text or geometry. Explicit headings and unrelated columns are hard barriers. Existing exact translation caches remain valid for unchanged source text; changed reading units get their own translation identity.

- [x] Reproduce Generative Agents against the real PDF and add failing synthetic PDF tests for column rollover, sentence-final footnotes, cross-page right-to-left flow, captions and true paragraph boundaries.
- [x] Repair layout-derived continuation and keep all previous ReAct, Reflexion, formula and source-offset regressions passing.
- [x] Add source-keyed boundary review, strict validation, persistence and failure behavior. Test cached merges/separations, stale sources, forbidden boundaries and untrusted model output.
- [x] Connect review API and translation workflow with visible checking state, manual checking, and race protection. Add browser coverage for merged selection and persisted reading state.
- [x] Run focused/backend/browser/build checks, inspect real Generative Agents/ReAct/Reflexion reading units, restart only an idle owned backend and document results.
