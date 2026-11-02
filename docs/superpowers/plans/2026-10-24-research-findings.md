# Background research beyond collection essays

> Execute inline, preserving the current workspace, essays, knowledge edits and official account policy.

**Goal:** Produce useful connections, consequential knowledge gaps, reusable review questions and grounded research questions while LIRA is idle.

**Architecture:** Add a `findings` job alongside `essay` in the existing durable queue. Discovery reads the scoped original material and prior findings; a second call verifies and edits candidates against their original passages. Publish a finite batch (at most12), allowing no new findings when nothing useful survives. Each collection chooses work types. Fingerprints include chosen types and their prompt recipe; unchanged materials do not generate new batches. User actions are excluded from the generation fingerprint. Existing essay fingerprints and defaults remain compatible.

**Data:** Migration0014 adds task.kind, scope.work_types_json, research_findings and immutable research_finding_revisions. A finding has category, stable identity, title, body, next_step, original sources, current status, review count and next due time. Revisions preserve previous explanations and evidence. Reusing a known finding ID updates its content while retaining user status and review schedule. Cross-paper connections require evidence from at least two papers; gaps identify missing understanding or coverage without claiming unobserved literature does not exist. Neither publishing nor retaining findings writes into the knowledge catalog.

**UI:** Add “研究线索” beside the existing collection views. A quiet list and one reading pane replace a grid of tiles. Filter by category/status; keep, dismiss and restore items; open citations and PDF; hide review answers until requested, then grade “再复习 / 记住了”. Due dates use deterministic intervals with no additional model calls. Per-scope work choices live in existing research settings. Keep source/PDF return navigation, dark mode, narrow layouts and keyboard behavior usable.

## Tasks

- [x] Write failing migration, evidence-validation, dedup/state-retention, spaced-review and queue independence/checkpoint tests.
- [x] Implement models/migration and `research_findings.py` for validation, publication, revision history and user actions. Use exact-quote validation, selected categories, bounded output and collection-scoped existing IDs.
- [x] Extend snapshot recipe and worker with findings discovery/review checkpoints, independent task identities, scoped enabled work types, original foreground preemption/quota policy, and finite automatic scans. Add API read/update/action routes.
- [x] Add frontend types/API and a focused `ResearchFindings` component. Connect the third collection view and per-type preferences without duplicating the existing research settings or source dialog.
- [x] Add meaningful browser coverage for the findings reading/action/review/source flows, settings persistence and narrow screens; run focused backend checks and production build.
- [x] Perform a bounded official trial on Memory初探-入门, inspect actual findings against sources, preserve the essay and catalog, test persisted actions/review in the real UI, and restore idle/budget settings.
- [x] Run complete backend tests and relevant browser regressions; record exact evidence, limitations and usage. Keep the local app running.

**Verification:** `.venv/Scripts/python.exe -m pytest tests/test_research_findings.py tests/test_background_research.py tests/test_research_policy.py tests/test_migrations.py -q` from backend; `npm run build` and `npx playwright test tests/background-research.spec.ts tests/research-findings.spec.ts --reporter=line` from frontend. Real findings require manual semantic inspection; passing quote checks alone is insufficient.
