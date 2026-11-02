# Existing paper collection assignment

> Execute inline in the current workspace. Preserve unrelated changes and the
> running user's papers; no commits, branch cleanup, or paid model calls.

**Goal:** Let users assign existing papers to a topic from the library, from
multi-selection, or from the topic itself, then persist and display membership.

**Design:** Reuse existing collection membership storage and removal. Add a
transactional endpoint for adding up to 500 papers to one collection. A shared,
searchable, staged dialog either fixes the papers and chooses a destination or
fixes the destination and chooses existing papers. Confirming saves; cancelling
does not mutate. Existing memberships are retained and repeated adds are safe.
Keep existing single-paper membership/tag management available. Use the current
warm palette and typography, a scrolling list, and clear primary action.

**Tech stack:** FastAPI/Pydantic/SQLAlchemy; React/TypeScript; pytest/Playwright.

## 1. Atomic addition

- [x] Add `backend/tests/test_collection_assignment.py`: multiple papers,
  duplicate/repeated IDs, other collection preservation, all-or-nothing missing
  paper, missing collection, and empty/oversized list validation.
- [x] Run `backend/.venv/Scripts/python.exe -m pytest
  backend/tests/test_collection_assignment.py -q`; verify missing bulk route.
- [x] Add `CollectionPapersAdd` to `backend/app/schemas.py` and
  `POST /collections/{collection_id}/papers` to
  `backend/app/api/collections.py` with payload `{"paper_ids":["paper-id"]}`.
  Validate all paper IDs before inserting, commit once, reload the collection's
  links, and return `CollectionRead`. Integrity conflicts leave no partial batch.
- [x] Re-run the focused tests.

## 2. Discoverable assignment

- [x] Add `frontend/tests/collection-assignment.spec.ts` using a disposable
  workspace. Cover row action, bulk selection, adding from an empty collection,
  search, cancellation, save failure/retry, duplicate membership, and reload.
- [x] Run the new test file and observe failures for missing controls.
- [x] Add `api.addCollectionPapers(collectionId, paperIds)`.
- [x] Create `frontend/src/components/AddToCollectionDialog.tsx` and its CSS.
  Fixed-paper mode lists searchable collections with radio inputs and marks
  destinations already containing the papers. Fixed-collection mode lists
  searchable existing papers not already in the destination. Retain selections
  across filtering, trap dialog focus, restore focus on close, disable duplicate
  submission, and keep errors inside the dialog with selections intact.
- [x] Update `LibraryPage.tsx`: explicit unfiled row button, selected-paper action,
  topic heading action, and a selected-paper detail action. Preserve existing
  membership removal and tag editing. Refresh paper membership and sidebar counts.
- [x] Add a labeled collection action in the reader using the same dialog.
- [x] Add Chinese and English strings. Check light/dark and narrow layouts.

## 3. Verification and actual filing

- [x] Run the new pytest file and existing workflow tests.
- [x] Run new Playwright cases plus `workspace.spec.ts`; build the frontend.
- [x] Inspect screenshots of both assignment modes and a narrow viewport.
- [x] Restart the backend only when model tasks are idle, then use the actual
  application to put Generative Agents in the existing Memory topic.
- [x] Re-read membership/count and the PDF after reload; run scoped
  `git diff --check` and record evidence. Report the actual controls and result.
