# Knowledge intake: reconciliation and review

Verified on 2026-10-23 in the existing `D:\paper_reader` workspace. No commits or pushes were made.

## Root causes

1. Extraction identity included a random run ID and source evidence. Three analyses of MemGPT created three copies of the same inventory.
2. Candidate confirmation did not retain declared aliases on canonical objects. Later extraction could create a second identity for the same object.
3. Paragraph extraction sent only its first source block and hid provider failures behind a successful response.
4. Review mixed pending, settled and ignored records. Generic method-map selection promoted cited methods and supporting tools to core methods.
5. Knowledge audit applied a fixed ReAct vocabulary to arbitrary papers, including duplicate dataset/benchmark checks and irrelevant missing items.

The reconciliation follows the preservation principle described in [Zotero duplicate detection](https://www.zotero.org/support/duplicate_detection): retain sources and associations while merging identity. Here the scope is paper-local extraction, with separate canonical library objects. Different types, papers and ambiguous acronyms are not joined by string similarity.

## Data verification

SQLite backup before modification:

`D:\paper_reader\.local-runtime\knowledge-backups\2026-10-23-pre-live-apply.db`

| Inventory | Before | After |
| --- | ---: | ---: |
| Library candidates | 98 | 66 |
| Library relationships | 69 | 47 |
| MemGPT candidates | 48 | 16 |
| MemGPT relationships | 33 | 11 |

The 32 redundant objects and 22 relationships are archived in `knowledge_changes` with their original fields and timestamps. Surviving records accumulate the original evidence, and relationship endpoints are rewired. Archived IDs redirect to retained records. User edits and ignored states are preserved; conflicting decisions use the most recent human action.

Reconciliation ran first on a database copy. Every original `(chunk_id, quote)` pair remains reachable through its retained object or relationship. Three replays of the stored MemGPT extraction produced no inventory growth. A second reconciliation created no additional changes. SQLite integrity and foreign-key checks passed. All tables other than paper knowledge and the paper knowledge-status/update-timestamp fields were unchanged before UI inspection, including notes, translations and conversations.

The same counts and preservation checks passed after application startup repaired the live database. The original analysis results were replayed locally; this does not claim a new model extraction or exhaustive semantic verification of every entity.

Machine-readable report: `.local-runtime/knowledge-reconciliation-report.json`. Replay script: `.local-runtime/verify_knowledge_reconciliation.py`.

## Workflow and presentation

- The reader starts with objects, then relationships; pending, settled and ignored inventories are separate.
- Search covers names, aliases and definitions. Main methods, evaluation objects, components and prior work have distinct groups.
- Users can inspect original quotes in place, edit before confirming, or confirm/ignore selected objects atomically.
- The field review includes a source-paper filter and paper titles. Object dossiers open the actual source paper, including across papers.
- Refresh keeps the inventory visible. A late refresh cannot replace a completed batch decision.
- Evidence prose reflows PDF soft wraps and split words for display; immutable stored quotes and PDF locators stay verbatim. Explicit math uses the existing scientific typography.
- Core-method selection excludes merely used tools and cited methods. These objects remain available in the catalog and related-method graph.
- Missing-source suggestions come from current body text and existing library identities, with correct types and review states. They are suggestions to check, not a field-completeness score.

## Verification

- Full backend suite: **722 passed**, one existing Starlette/httpx deprecation warning.
- Knowledge and reading-notes browser suites: **27 passed, 1 skipped**. The optional real-research-PDF annotation test was skipped because its fixture was unavailable; note/highlight checks using the seeded PDF passed.
- Additional final method-selector and intake browser run: **9 passed**; covers supporting-method exclusion, source navigation, batch review, filtering, pending refresh and late-response protection.
- Production frontend build passed. Vite reports the existing large-bundle advisory.
- `git diff --check` passed.
- Live API health: `{"status":"ok","service":"research-intelligence-api"}`.
- Live frontend: `http://127.0.0.1:5173`.

Live screenshots and UI script are under `.local-runtime/knowledge-intake-20261023/` and `.local-runtime/verify-knowledge-intake.cjs`: reader pending, settled source preview, narrow dark reader, library inbox, paper-scoped inbox and evolution graph. Browser inspection reported no page errors. The reader inventory had 11 pending and 5 settled MemGPT objects; its scroll width matched its client width.

This change prevents repeated extraction from inflating the inventory and improves source review. It deliberately does not infer new technical lineage from citation presence or automatically merge merely similar concepts; those decisions still require grounded extraction and researcher review.
