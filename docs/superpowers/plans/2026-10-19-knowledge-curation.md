# Knowledge curation implementation plan

**Goal:** Make the field registry an editable, source-grounded knowledge base with clear object identity and complete relationship review.

**Architecture:** Canonical entities own names, types, aliases, descriptions and maintained links. Paper-local candidates and relations keep their original extraction and quotes. A curation service handles validation, same-type merges, reversible relationship decisions and change history; projections attach precise paper provenance and canonical endpoint IDs.

**Tech stack:** FastAPI, SQLAlchemy, additive Alembic migration, React, existing warm theme, pytest and Playwright.

## Decisions

- Extend the existing catalog / dossier / method-map path. The dossier is a readable modal panel with overview, relationships, sources and history, and explicit edit mode.
- Canonical renames do not rewrite extracted labels or source quotes. Aliases share one namespace per type. Same names in different types remain distinct. Merges require same type and a preview; keep a redirect and snapshots rather than delete source history.
- Relation confirmation requires two accepted paper-local candidates linked to active objects and a quote verified against that paper. Rejection is reversible. Editing endpoints cannot attach a candidate from another paper. Resolving a missing target does not silently accept a missing or rejected source.
- Evidence always includes owning paper ID and title. Dossier sources and relation sources navigate to that paper and page. Rejected records stay in review/history, excluded from established facts.
- The catalog respects the selected collection, includes all eight types and paper / relationship counts. The inbox includes relationships and ignored items as well as candidate objects.

## Execution

- [x] Add regression tests for provenance, homonyms, metadata edits / alias collisions / persisted links, merge preview and history, relation endpoint validation / review / restoration and unresolved source behavior. Run to record expected failures.
- [x] Add migration `0012_knowledge_curation`, schemas, curation service and routes. Keep extraction and manual curation separate. Run knowledge and migration tests.
- [x] Add typed client operations and shared human-readable labels. Build canonical editor / merge preview, relation editor and dossier tabs with race protection, Escape and focus handling.
- [x] Connect scoped catalog and relationship inbox, refresh projections without closing dossier or resetting map context. Improve reader review labels / relationship actions.
- [x] Add browser regressions for edits surviving reload, rejected / restored relationships, merge preview and correct evidence navigation. Check narrow layout, light / dark, keyboard and icon dimensions.
- [x] Run backend suite, browser regressions, production build. Review code, back up database, restart idle owned backend for additive migration, inspect real Reflexion / ReAct read flows. Record evidence and limitations.

Work stays in the current dirty workspace to preserve the integrated local app and all existing user changes. No commit or push is requested. Test mutations use isolated databases; the real library is inspected without synthetic edits.

Execution and validation: [knowledge curation evidence](../evidence/2026-10-19-knowledge-curation.md).
