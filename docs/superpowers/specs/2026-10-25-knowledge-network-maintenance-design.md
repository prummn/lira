# Knowledge network maintenance design

## Problem

The workspace already stores paper-local candidates, canonical entities, relations, immutable paper evidence, merge redirects, and change history. The missing layer is a cross-paper maintenance workflow. Today a researcher can inspect an entity or a paper's intake inbox, but cannot ask the system to answer a larger question such as “which parts of this field map are duplicated, unsupported, disconnected, or incomplete?” The existing paper audit is intentionally read-only and mainly reports mentions of known entities; it does not produce a ranked, reviewable repair plan.

The new feature is a knowledge network maintenance assistant. It should improve the network's identity and relationships while preserving provenance and keeping the review burden small. It must not turn model output into an unchecked database write path.

## Goals

- Run a deterministic health check over the whole library or a selected collection.
- Let a model inspect only suspicious neighborhoods with their paper evidence, canonical identities, relation context, and relevant change history.
- Detect duplicate or split identities, dangling or contradictory relations, invalid evidence, missing links, and structures that make the field map misleading.
- Produce a persistent maintenance run with issues, evidence, proposed actions, confidence basis, and affected records.
- Apply high-confidence, low-risk repairs automatically when the stored evidence is sufficient.
- Put uncertain semantic decisions into a short, ranked review queue rather than forcing the researcher to inspect every extraction.
- Make every applied action atomic, traceable, and undoable.
- Use external search only as clearly labelled supporting leads; it may never silently overwrite paper evidence or a manual decision.
- Make the default interface problem-first (direction A): issues and safe fixes are the primary view; relationship visualization appears in the selected issue's detail view.

## Non-goals

- Replacing the existing paper intake and entity dossier workflows.
- Treating a model confidence number as proof by itself.
- Automatically deleting entities, evidence, user edits, or rejected decisions.
- Rebuilding the whole graph on every page load.
- Making external web search a hidden fallback for provider failures.

## Alternatives considered

### Audit-first, model-assisted repair (recommended)

Programmatic checks create a small set of suspicious neighborhoods. The model classifies the issue and proposes a typed action. A confidence and risk gate decides whether to apply it automatically or place it in review. This gives the user the low-noise workflow requested while keeping deterministic evidence and rollback in charge.

### Model-first autonomous curator

The model receives the full graph and is allowed to edit it directly. This could find more semantic connections, but it has poor failure isolation, spends more tokens, and makes it difficult to distinguish a factual correction from an invented relationship. It is rejected for the default path.

### Suggestion-only audit

The system would only list possible problems and require a manual decision for every change. This is safe but recreates the current review burden and leaves obvious exact duplicates unresolved. It remains available as a per-run “review everything” mode for cautious inspection.

## Confidence and action policy

The model reports confidence, but the application computes eligibility from evidence and record state.

### Automatic actions

An issue is eligible for automatic application only when all of these hold:

1. The operation is in the low-risk allowlist.
2. The affected records have not changed since the proposal was created.
3. There is no conflicting human change or rejected decision on the same subject.
4. The evidence is valid against the current paper chunks.
5. The identity or relation is either deterministic, or has strong evidence from at least two distinct source chunks or papers and no conflicting evidence.

The initial low-risk allowlist is:

- merge paper-local duplicate candidates with the same entity type and an exact normalized identity or an unambiguous canonical alias;
- merge duplicate relations with the same resolved endpoints and predicate, unioning their valid evidence;
- resolve a relation endpoint when exactly one active canonical entity matches the stored type and verified name/alias;
- repair an evidence locator when the quoted text is still present in the owning chunk and only page/bounding-box metadata is stale;
- restore a relation to its computed settled state when both endpoints and evidence are valid and a previous reconciliation left it unresolved.

No automatic action deletes a record. Entity merges retain redirects, snapshots, and source history through the existing change log. Any proposed rename, semantic merge, split, relation predicate rewrite, new entity, or external-source fact stays in the review queue even when the model is confident.

### Review actions

The following require explicit confirmation: fuzzy identity matches, homonym resolution, entity split, relation direction or predicate changes, missing dataset/benchmark/method creation, changes that touch a manual edit, and any proposal whose only support is an external source.

The user may still choose “review everything” for a run. Each issue is applied in its own transaction; if one proposal becomes stale, that proposal is skipped and the rest are reported separately.

## Audit pipeline

1. **Scope and fingerprint.** A run records `all papers` or a collection/paper scope, the source record fingerprint, whether external leads are allowed, and the prompt/model version.
2. **Deterministic checks.** The service scans active entities, candidates, relations, evidence, and change history for exact duplicates, dangling endpoints, rejected endpoints, invalid quotes, duplicate edges, unresolved relations, orphaned objects, conflicting aliases, and suspicious topology. It also reports coverage gaps only when a paper or an existing entity gives a source-grounded signal; it does not turn absence into a completeness score.
3. **Neighborhood assembly.** Only suspicious records and their one-hop relation neighborhoods are sent to the model. Each bundle contains canonical names and aliases, paper titles and sections, immutable quotes, relation predicates, status, importance, and relevant human changes. Stable fingerprints allow unchanged bundles to reuse the previous result.
4. **Semantic audit.** The model classifies each bundle as `identity`, `relation`, `evidence`, `coverage`, `importance`, or `structure`, explains the issue in plain Chinese, separates paper fact from inference, and returns at most one concrete proposed action per issue.
5. **Evidence gate.** The application validates every citation against the stored chunk before calculating `auto_eligible`. External leads are stored separately and never count as paper evidence.
6. **Plan publication.** The run becomes `complete`, `partial`, or `failed` with counts for safe fixes, review items, conflicts, and unresolved provider work. The report remains available after the browser session ends.
7. **Application and undo.** Safe actions can be applied in one click. Each mutation records a `KnowledgeChange` before/after snapshot and points back to the maintenance issue. Undo applies the inverse snapshot only if the subject has not changed since the automatic action.

The model prompt must explicitly forbid inventing entities, treating a bibliography-only mention as a relation, and using outside knowledge as if it came from the paper. It must return structured JSON with issue type, affected IDs, evidence IDs, reasoning, confidence factors, and a single action proposal.

## Persistent model

Add two additive tables through an Alembic migration.

### `knowledge_maintenance_runs`

- `id`, `scope_type`, `scope_id`, `status`, `allow_external`, `model_name`, `prompt_version`;
- `source_fingerprint`, `started_at`, `finished_at`, `error_message`;
- `safe_count`, `review_count`, `conflict_count`, `applied_count`.

### `knowledge_maintenance_issues`

- `id`, `run_id`, `kind`, `severity`, `status`;
- `confidence`, `confidence_basis_json`, `auto_eligible`;
- `subject_ids_json`, `evidence_json`, `external_leads_json`;
- `summary`, `reasoning`, `proposed_action_json`;
- `source_fingerprint`, `applied_change_ids_json`, `created_at`, `updated_at`.

Issue statuses are `proposed`, `auto_applied`, `needs_review`, `accepted`, `rejected`, `stale`, and `undone`. The existing `KnowledgeChange` table remains the mutation history; the issue stores links to the changes created by its application.

## API surface

- `POST /knowledge/maintenance/runs` starts a run for the library, collection, or explicit paper IDs.
- `GET /knowledge/maintenance/runs` lists recent runs and their counts.
- `GET /knowledge/maintenance/runs/{run_id}` returns the report and paginated issues.
- `POST /knowledge/maintenance/runs/{run_id}/apply-safe` applies all currently eligible safe issues atomically per issue.
- `POST /knowledge/maintenance/issues/{issue_id}/apply` applies one issue after rechecking its fingerprint.
- `POST /knowledge/maintenance/issues/{issue_id}/reject` records a rejection without deleting evidence.
- `POST /knowledge/maintenance/issues/{issue_id}/undo` reverses an applied issue when its subjects are unchanged.

Provider and quota failures do not erase deterministic results. A run can finish as `partial` with the local findings and a retryable model stage. External search timeouts leave the issue usable with its paper evidence and a visible “external lead unavailable” state.

## A workbench interaction

Add a `维护` tab to the existing knowledge page. The page keeps the selected collection as its scope and contains:

- a compact header with scope, last run, “开始体检”, and “应用安全修复”;
- a four-number status strip: safe fixes, needs review, conflicts, and evidence gaps;
- a filterable issue list ordered by impact first, then confidence, with concise labels such as “同名对象重复” or “关系端点悬空”;
- a detail panel that shows the affected entity/relation, the before/after change, the original paper quote, source navigation, and the reason for the confidence gate;
- a small relationship neighborhood diagram inside the detail panel, with the selected issue highlighted and unrelated nodes hidden;
- a history drawer with automatic actions, human decisions, and undo controls.

The list should never show raw URLs or repeated citation blocks as the main content. Evidence is a readable quote with paper title, section, page, and a single “打开原文” action. The visual language follows the existing warm editorial theme: restrained borders, clear severity color, generous spacing, and one primary action per issue.

## External leads

When enabled, the existing external search service may look up a candidate's canonical paper, dataset, or project page after the local audit identifies a gap. Store query, URL, title, snippet, retrieved time, and provider in `external_leads_json`. Display it as a lead with a provenance badge. It can support a review proposal, but cannot satisfy the paper-evidence gate or auto-create an entity.

## Validation

Backend tests will cover exact duplicate repair, ambiguous aliases, duplicate relation union, invalid evidence, rejected endpoints, manual-change protection, confidence gating, stale fingerprints, partial provider failure, apply/undo, and scope isolation. API tests will verify persistent run history and idempotent safe batches. Frontend Playwright tests will cover the A layout, safe batch application, evidence navigation, review/reject, stale issue display, undo, narrow layout, and reload persistence.

The existing knowledge, analysis, background research, and full backend suites remain required. A live smoke check will run a maintenance audit against the current library in read-only mode first, then apply only the deterministic safe subset on a database backup. The result and any remaining provider limitations will be recorded in `docs/superpowers/evidence/`.
