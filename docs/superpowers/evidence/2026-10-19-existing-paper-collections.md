# Existing paper assignment verification — 2026-10-19

Existing collection membership was available through small unlabeled-looking
controls. The library now explicitly offers Add to collection for unfiled
papers and selected batches; topic pages offer Add existing papers. The reader
toolbar uses the same destination chooser. Existing membership management,
removal and tag editing remain available independently.

The new bulk endpoint validates every paper before one transaction. Existing
memberships are retained; repeated IDs and repeated submissions are idempotent.
Selections survive searching and failed saves; cancelling before save does not
mutate membership. Saving blocks repeated submission/dismissal and retains focus.

## Verification

- `backend/.venv/Scripts/python.exe -m pytest
  backend/tests/test_collection_assignment.py backend/tests/test_workflow.py -q`:
  **22 passed**. The existing Starlette/httpx deprecation warning remains.
- `npm run test:e2e -- tests/collection-assignment.spec.ts tests/workspace.spec.ts`
  from `frontend`, with the backend venv on PATH: **22 passed** in a disposable
  database. Covers single/batch addition, topic-to-paper selection, filtering,
  cancellation, failure/retry, focus during pending/failed saves, reader action,
  duplicate membership, removal, tag editing, reload and empty English/dark UI.
- `npm run build`: passed. The existing large-bundle warning remains.
- Screenshots inspected in light and dark modes, including 1080×800. The chooser
  has one search border, readable rows, a scrolling list and a fixed action area.
- Independent review found an unfiled tag-editor entry regression and focus
  escape when disabling submit. Both were reproduced in browser regressions,
  fixed and independently rechecked. No remaining findings in this scope.
- Scoped `git diff --check`: passed. No paid model calls or database migration.

## Actual application

After checking that no model tasks were queued or running, the backend was
restarted to load the bulk endpoint. The actual frontend on port 5173 was used
to assign **Generative Agents: Interactive Simulacra of Human Behavior**
(`paper-06a65bc9f9fa4723`, arXiv `2304.03442`) to the user's existing
**Memory初探-入门** collection (`collection-3a2e5347255c4a6f`). Reloading the page
and opening that collection showed the paper and count **1**. API rereads
confirmed persistence, the downloaded PDF retained its original SHA-256, and
there were no browser JavaScript errors. No additional user papers were filed.

The screenshot and verification record are ignored runtime artifacts under
`.local-runtime/collection-assignment/`. The original papers, notes and unrelated
repository changes were preserved; no commits or pushes were made.
