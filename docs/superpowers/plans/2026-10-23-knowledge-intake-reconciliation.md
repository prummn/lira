# Knowledge intake reconciliation and review

**Goal:** A repeated analysis enriches one paper-local knowledge inventory, while researcher decisions and every source remain traceable.

**Architecture:** Reconcile by paper, entity type and verified identity (normalized name, explicit unambiguous alias, or canonical entity). Reconcile relations by their resolved endpoints and predicate. Archive redundant extraction rows as complete snapshots in the existing append-only change log before repointing references. Do not merge homonyms across entity types, paper provenance, conflicting canonical identities, or merely similar strings. Keep the integrated dirty workspace and make no commits or pushes.

**Evidence:** The live library has 98 candidates and 69 relations. MemGPT accounts for 48 candidates and 33 relations from three repeated runs: 16 object identities and 11 relation identities. `persist_candidates` includes random run IDs and evidence in primary keys and only deduplicates within a single response. Confirmation drops extracted aliases. Paragraph extraction passes only the first source block despite having complete `refs`/`anchors`, and swallows provider failures.

**Design:** Replace the reader's mixed list with objects/relationships views, explicit pending/settled/ignored filters, search, and meaningful object groups. Show real source quotes on demand; keep status, role and evidence distinct. Default objects before relationships, because endpoints must be reviewed first. Do not expose confidence percentages as the main quality signal. Retain the warm existing theme, use dividers and typography, and keep PDF reading position intact.

**Research:** Zotero's duplicate handling preserves collections/tags/relations when merging (`https://www.zotero.org/support/duplicate_detection`). Here, identity is paper-local with separate canonical field objects; a dataset and same-name benchmark remain distinct. Automated merging is restricted to exact identities and unambiguous declared aliases.

## Execution

- [x] Reproduce repeated-run growth, lost rejection, lost aliases, repeated relationship edges and cross-block paragraph failures in isolated pytest fixtures.
- [x] Implement deterministic upserts, evidence/alias accumulation, manual-decision preservation, complete duplicate snapshots and endpoint rewiring. Add startup reconciliation and old-ID redirects.
- [x] Verify repeat repair is a no-op; preserve separate types/papers and ambiguous aliases; never reconnect rejected endpoints as confirmed relations.
- [x] Correct paragraph source gathering and surface provider failures. Regression-test complete multi-block context and repeated extraction.
- [x] Add reader and inbox review layout, source previews, filters and search. Browser-test decisions, scope changes, paragraph failures and narrow/dark layouts.
- [x] Back up the live SQLite database using its backup API; replay reconciliation on a copy and inspect counts, evidence, decisions and foreign keys before applying to the live app.
- [x] Run backend regressions and full suite, frontend build, focused Playwright suites, diff check, live service restart/health, real MemGPT UI inspection. Record concrete evidence and remaining limitations.

No user clarification is pending: the user explicitly asked for autonomous investigation and fixes while unavailable.

## Additional findings resolved during review

- Ambiguous acronym owners are computed across the full incoming batch before matching, making identity independent of input order.
- Explicit researcher edits survive pending-review status; latest human decisions outrank earlier acceptance. Established canonical identity wins over an unreviewed legacy duplicate.
- Original predicate/endpoints remain recoverable through change history and archive redirects after a relationship is corrected, merged, or ignored.
- Alias recovery and candidate restoration respect intentional canonical alias removal.
- Audit coverage is based on current-paper candidates and actual body mentions of library entities. The hardcoded ReAct checklist is removed; types and ignored decisions stay distinct.
- Reader dossiers navigate to the owning paper. Completed batch decisions invalidate older refresh requests.
- Source excerpts reflow PDF line breaks for display while retaining immutable quotes for evidence and locators.
- Method selectors list proposed methods; cited methods and supporting tools remain in their relationship neighborhoods.

See `docs/superpowers/evidence/2026-10-23-knowledge-intake-reconciliation.md` for database, browser, and regression evidence.
