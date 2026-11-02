# Knowledge page presentation verification

The UI work preserves the existing workspace and does not write to the production database or restart production services. Browser tests use the guarded disposable backend on port 8010 and frontend on 5177; the existing isolation token and temporary database/storage checks remain enabled.

## Behavior delivered

- Citation graph relationship details start collapsed beneath `关系明细`.
- Missing publication venues display `预印本 · arXiv` when arXiv provenance exists, otherwise `发表信息待补充`; unknown years have a specific pending label.
- Comparison uses 15px body text with 1.85 line height, 16px column titles, and at least 340px per paper. The table scrolls at a 390px viewport. Missing analysis distinguishes failed, queued/running, absent, incomplete-field, and extractive states and provides an open-paper action.
- The evolution map includes proposed methods, benchmarks and datasets, with explicit contribution-type labels. Legacy `used` benchmark/dataset candidates are recovered as a paper's own contribution only when their name or alias exactly matches that paper's title identity before the colon. External benchmark mentions remain supporting objects.
- Papers without a core contribution remain visible in the coverage section with status and an open-paper action.
- Navigation contains one `对象目录`; the legacy concepts view remains internal.
- `AI 知识整理` leads with automatically completed actions, paper source audits, object/relation counts and aliases. Remaining checks and operation history are expandable; evidence, existing issue actions and undo remain available. Active runs refresh automatically. The completed-action metric reads `usage.auto_actions` with a legacy `applied_count` fallback. Starting a run enables public publication metadata verification via the existing `allow_external` argument.

## Red evidence before fixes

- New timeline test received `未识别` instead of `预印本 · arXiv`.
- New comparison test received the generic unreported text instead of the failed-analysis explanation.
- The proposed SWE-bench contribution was absent from the evolution choices.
- The completed paper audit section was absent.
- The completed metric displayed 1 issue instead of 3 automatic actions.
- An active run stayed queued after its API result became complete.
- Selecting completed history removed pending checks; the new assertion failed because their summary disappeared.
- A new curation request submitted `allow_external:false` instead of the requested public metadata verification.

## Final verification

- `npx playwright test knowledge- --reporter=line`: **24 passed (55.6s)**. Includes existing editing, merge-preview, relation correction, asynchronous saves, evidence navigation, intake and dossier tests plus new contribution/presentation/curation regressions.
- `npx playwright test tests/workspace.spec.ts --grep "Knowledge and researcher" --reporter=line`: **1 passed (13.6s)**.
- `npm run build`: exit 0; TypeScript and Vite succeeded. Vite retains its existing large-chunk advisory.
- `git diff --check` on the modified tracked UI sources: no whitespace errors; Git reports existing CRLF normalization notices.

Screenshots visually inspected from isolated fixture data:

- `D:/paper_reader/frontend/test-artifacts/knowledge-relations-collapsed.png`
- `D:/paper_reader/frontend/test-artifacts/knowledge-comparison-readable.png`
- `D:/paper_reader/frontend/test-artifacts/knowledge-comparison-mobile.png`
- `D:/paper_reader/frontend/test-artifacts/knowledge-contributions.png`
- `D:/paper_reader/frontend/test-artifacts/knowledge-ai-curation.png`

These establish UI behavior and API integration against controlled fixtures. The parent task separately owns real-model curation against an isolated snapshot; these screenshots do not establish production ingestion completion.

## Follow-up: real curation contract

Paper audit counts now display `objects_confirmed` and `relations_confirmed` directly. Added and confirmed counts overlap, so adding them incorrectly counted the same newly created object or relationship twice. The regression reproduced 6 objects instead of 4 before the fix.

Proposed `curate_paper` issues are displayed in a separate automatic paper queue and the pending-paper metric, without review/reject actions. Only `needs_review` items enter the exception section. Legacy deterministic repair suggestions remain separately available. Accepted or automatically applied history records expose undo only when `applied_change_ids` is nonempty. Failed and partial runs display their actual persisted error message.

New red evidence: the automatic queue was absent; an accepted audit with no changes exposed undo; and a failed run hid its actual provider error. All failures were reproduced using intercepted API fixtures on the isolated test backend.

Follow-up verification:

- Focused maintenance and contract tests: **7 passed (23.6s)**.
- `npx playwright test knowledge- --reporter=line`: **27 passed (57.3s)**.
- `npm run build`: exit 0, TypeScript and Vite succeeded, retaining the large-chunk advisory.
- `git diff --check`: no whitespace errors; CRLF normalization notices remain.

No real model calls, production database access or production service restarts were performed for this follow-up.


## Read-only real-data UI verification and scope-loading fix

The 7-paper Agent 初探 - 入门 collection was inspected through real API GET responses against `.local-runtime/steward-replay-20261101-final-a/replay.db`. The dedicated backend used SQLite `mode=ro`, disabled lifespan/workers, cleared model credentials and denied non-GET requests; the browser also blocked writes. A test write returned 405. Snapshot SHA-256 was unchanged before and after: `3E4C9786DDD39C71FDF627DE8465D5728FB44FF13ADD2374E6A6BD90A4FB8B48`. Ports 8022 and 5188 were stopped and verified closed. No production database writes/restarts or real model calls occurred.

Observed 7 timeline cards; a 7-node/9-edge paper graph with collapsed details; 7/7 evolution coverage and 11 contribution choices; 2 source quotes from a selected edge; 3-paper readable comparison with no missing cells and 390px horizontal scrolling; 156 directory entities with working search; 7 curation audit reports and 135 automatic actions with no queued/review/conflict items. Navigation and reload worked. No page errors or failed GET requests were recorded. Screenshots were visually checked at top, lower scroll positions and the narrow comparison viewport, with no clipping/overlap blocker.

The inspection exposed an unbounded request flood when switching from the 43-paper library to the collection. The regression reproduced 24 stale-scope detail requests under StrictMode. The active-scope queue now limits details and audits to 3 concurrent reads each, stops scheduling on cleanup and preserves response order. Its focused regression passed; the actual collection loaded in 11228ms after the fix.

Evidence and measurement details: `.local-runtime/steward-ui-20261101/README.md`, `browser-report.json`, `cleanup-report.json`, and the 13 PNG captures in that directory. These establish final-a snapshot/browser behavior; later context-classification replays and production deployment require separate verification.

## Context-action presentation follow-up

Per-paper reports now render `objects_contextualized` as 上下文标注 / Context annotations only when the count is positive. Missing legacy values normalize to zero. A new regression failed with the context row absent before the implementation. The parent-owned context classification, candidate explanations and method-network filtering are included in the final frontend regression run below.


Final combined frontend verification after context annotations and bounded scope loading:

- `npx playwright test knowledge- --reporter=line`: **30 passed (1.0m)**, including the retained-context method-network regression, contextualized action count, queued-paper contract, comparison/presentation and scope-loading checks.
- `npm run build`: exit 0; TypeScript and Vite succeeded (16.41s Vite build). Existing large-chunk advisory remains.
- `git diff --check` on the changed tracked UI files: exit 0, no whitespace errors; Git retains CRLF normalization notices.
- Snapshot SHA-256 rechecked unchanged; no listeners on dedicated real-snapshot ports 8022 or 5188.


## Final validated snapshot browser acceptance

The validated replay snapshot was inspected read-only through temporary ports8022/5188. Actual API/UI checks confirmed7papers,195candidates,168entities,111confirmed/9unresolved/6rejected relations and11contextual records. DeepSWE evolution excludes all11context examples while retaining7/7coverage; the candidate view explains all11preserved identities and expands BookWorm source evidence. AI curation renders7reports,192actions and DeepSWE contextual count11. Navigation/reload passed with0page errors and0failedGETs. Screenshots were visually inspected. Full detail,known limitations and actual measurements are in `.local-runtime/steward-ui-20261101-final/README.md` and `browser-report.json`.

Known observations:directory/dossier lack contextual badges and preserve the canonical BookWorm description; a later edge hit path intercepts the first dense-map relation click, while the last relation opens2source quotes normally. Both were reported to the parent. No code changes or full-suite rerun were made in this acceptance pass.

Temporary services were stopped and ports verified closed. Snapshot SHA256 before/after remained `4CFBE6B2FA74C9D6C736E7DAC9DD857E3E8ECC8A7BA552517ABCE3FEEFA0486E`. No production database writes/restarts or real model calls occurred.

## Final parent verification

After dense-edge controls, catalog/dossier context and the keep-as-research-object action:
`npx playwright test knowledge- --reporter=line`: **34 passed (1.6m)**.
`npm run build`: TypeScript and Vite succeeded, Vite22.34s; existing large-chunk advisory remains.
Scoped tracked `git diff --check` passed with CRLF normalization notices only.
These supersede the earlier30-test and31-test runs above.


## Final real-data findings resolved

The previous directory-context and dense-edge observations above are resolved. Directory rows display scoped contextual badges and reasons; context-only rows use the verified summary instead of the old canonical description. Dossiers group candidate context reasons by paper,mark only the matching paper as an example,and preserve canonical text in collapsed details and the existing editor. Mixed-use objects keep their definition.

All relation pointer controls now paint after every edge hit path,with24px targets and keyboard activation. The new red regression reproduced relation0 receiving another edge path at its click target. Final focused tests passed8/8(40.4s); build exited0(Vite25.81s,existing chunk advisory); tracked UI diff--check exited0. The parent owns the final full Knowledge run.

Refreshed validated-snapshot browser-report.json confirms all22actual DeepSWE relation controls receive their own pointer targets,the repaired first mini-swe-agent edge opens3source quotes,all11context examples stay excluded,and directory/dossier explanations are shown. Seven curation reports,context count11,navigation and reload pass with0pageerrors/0failedGETs. Updated screenshots03b/03c and02c-first-edge-source-quotes.png were visually inspected.

After the refreshed checks,ports8022/5188 were stopped and verified closed. Snapshot SHA256 remains4CFBE6B2FA74C9D6C736E7DAC9DD857E3E8ECC8A7BA552517ABCE3FEEFA0486E.No production writes,restarts or model calls occurred.
