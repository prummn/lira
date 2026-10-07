# Real Paper Identification and URL Import Implementation Plan

> **For agentic workers:** Apply test-driven-development and systematic-debugging. Execute independent parser, acquisition, and interface tasks in parallel; review and verify integration before completion.

**Goal:** Correct bibliographic identification using real PDFs, import papers from public links, and repair the user's existing Attention paper without losing research data.

**Architecture:** Extract first-page layout metadata and paper identifiers locally, enrich from authoritative public metadata when an identifier exists, and persist per-field sources. Acquire bounded public HTTP(S) PDFs with validated redirects. Refresh metadata and section labels in place, preserving chunk IDs, notes, evidence, reading state, and collections.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic/SQLite, PyMuPDF, httpx, React/TypeScript, Playwright.

## Contracts

- `ParsedPDF`: retain page_count/title/blocks; add defaulted authors:list[str], year:int|None, venue:str|None, doi:str|None, arxiv_id:str|None, metadata_sources:dict[str,str]. No paper-specific hardcoded answers. Geometry remains unrotated CropBox-relative.
- `POST /api/papers/import-url` with `{url:string}` returns PaperDetail, status201. Support arXiv abs/pdf and public direct PDFs; useful Chinese errors for invalid/HTML/private/oversized/duplicate/unreachable links.
- `POST /api/papers/{id}/refresh-metadata` returns PaperDetail. Resolve from stored PDF/identifiers/source URL; preserve record ID and all user data. Update section labels only when content and geometry match; no destructive chunk replacement.
- PATCH accepts optional title, authors, year, venue, doi, arxiv_id as well as existing user-state fields. Manual edits carry a manual source and are preserved by refresh.
- PaperSummary/Detail expose defaulted `source_url`, `metadata_sources:Record<string,string>`, and `metadata_warnings:string[]`.

## Task 1: Real fixtures and diagnosis

- [x] Download official Attention (`1706.03762`), BERT (`1810.04805`), LoRA (`2106.09685`) to ignored `.local-runtime/research-fixtures/`; record URLs/hashes and metadata from authoritative pages.
- [x] Reproduce user failure: first extracted line is Google permission paragraph, actual title appears later in 17pt bold; rotated arXiv stamp is 20pt and must not be a title candidate.
- [x] Capture compact real first-page layout/text regressions in tests with attribution, without committing full publisher PDFs.

## Task 2: Parser

Files: `backend/app/services/pdf.py`, new parser metadata helper, parser tests.

- [x] Write failing regressions for permission-before-title, rotated stamps, multiline title, authors in reading order, own identifiers/year/venue, and generic numbered section headings.
- [x] Verify red using `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_pdf_metadata.py -q`.
- [x] Score horizontal title candidates by size/position/grouping; reject permission text. Detect bibliographic facts only in front matter, never reference-list DOIs. Recognize styled/numbered headings without changing original text/bboxes.
- [x] Verify regressions and existing geometry tests.

## Task 3: Acquisition, authoritative metadata, and persistence

Files: new download/metadata services, `importing.py`, `models.py`, `schemas.py`, `api/papers.py`, serializers, migration0005, backend tests.

- [x] Write failing API/provider tests: arXiv normalization, original publication year vs revision date, ordered authors, redirects, non-PDF content, limits, private targets, duplicate errors, provider outage fallback, preserving notes/IDs/manual edits on refresh.
- [x] Run targeted pytest and observe intended failures.
- [x] Implement bounded HTTP(S) downloader and arXiv citation metadata/Crossref enrichment with source URL and finite timeout; metadata outages must allow local PDF import.
- [x] Integrate parsed facts and enriched facts into local/upload/link import. Default analysis remains local extractive.
- [x] Add migration and metadata correction/refresh API preserving user state.
- [x] Run targeted/full backend checks.

## Task 4: Interface

Files: `frontend/src/pages/LibraryPage.tsx`, new metadata dialog component, `lib/api.ts`, `types.ts`, locales, styles, `tests/workspace.spec.ts`.

- [x] Add failing browser scenario that opens link import, submits a link, sees success/error, opens imported paper; and metadata correction/refresh preserving user state.
- [x] Add URL dialog with form validation, disabled loading state, clear failures, active collection membership, success/open-paper action.
- [x] Add metadata action with editable bibliographic fields, provenance display, and refresh action.
- [x] Validate both locales, strict TypeScript, build, browser scenarios.

## Task 5: Real use and recovery

- [x] Use disposable database/browser to actually import downloaded Attention/BERT/LoRA and a live arXiv URL; inspect title, authors, original year, abstract, method sections, PDF reader, and evidence source jump.
- [x] Back up active SQLite database via SQLite backup API before migration/recovery. Restart local services and refresh existing `paper-bd976889aea34e46` through supported API. Verify notes/reading state/collections/ID unchanged.
- [x] Independent code review, full backend/browser/build checks, whitespace check, update docs with evidence and limitations. Prepare reviewed source changes for local commit and leave service running.

## Final evidence

125 backend tests passed (14.92 s); 13 default browser scenarios passed and the opt-in actual-paper scenario passed separately (32.8 s / 41.0 s total). Strict TypeScript and Vite build passed. Independent review blockers were corrected, including authoritative identity, trickle deadline, blank authors, collection recovery, parent Results selection, and BERT column ownership. The user paper was backed up, refreshed in place, locally reanalyzed, and opened in the running application. BERT/LoRA tests used disposable stores.
