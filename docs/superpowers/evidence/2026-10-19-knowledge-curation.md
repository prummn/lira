# Knowledge curation validation — 2026-10-19

## Result

The field catalog now supports maintained canonical objects and source-backed relationship review. An object dossier exposes overview, relationships, original evidence and change history. The existing method map, catalog and reader share these identities and review decisions.

Object editing covers names, all eight classifications, aliases, descriptions and resource links. Renaming retains the old name as an alias without rewriting extracted labels or quotes. Aliases and canonical names share a namespace within each classification. Dataset and benchmark homonyms remain distinct. Same-type merges require an explicit preview and confirmation, preserve a redirect and history, and flag relationships that would become self-references.

Relationship maintenance covers endpoints, direction, kind, description, confirmation, rejection and restoration. Manual creation requires a verified quote from the owning paper. Endpoint candidates must belong to that paper; confirmation additionally requires accepted endpoints and active distinct canonical objects. Editing returns a relationship to review. Rejecting an endpoint invalidates incident confirmed relationships rather than leaving them established.

The catalog respects collection scope and exposes paper and relationship counts. The review queue includes objects, relationships and ignored records. Human-readable labels replace raw enums in the reader and curation interface. Dialog focus, keyboard dismissal, concurrent actions and stale-request guards preserve context during maintenance.

## Automated verification

| Check | Result |
| --- | --- |
| Full backend suite | 665 passed, 93.93 s |
| Final backend regression after the last curation fixes | 44 passed, 14.38 s |
| Browser regressions: curation, field map, reader panel | 11 passed, 31.4 s |
| Production frontend build | Passed, 15.81 s |

The full suite preceded the last merge-preview and resource-link refinements. The final 44-test regression covers the updated curation paths, migrations, citations, knowledge API, presentation, extraction and service behavior. There are 13 curation-specific backend tests and five curation-specific browser tests.

Commands:

```powershell
# backend/
.venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe -m pytest tests/test_knowledge_curation.py tests/test_paper_citations.py tests/test_knowledge_api.py tests/test_knowledge_presentation.py tests/test_knowledge_service.py tests/test_knowledge_audit.py tests/test_knowledge_extraction.py tests/test_knowledge_models.py tests/test_migrations.py tests/test_api.py -q --tb=short

# frontend/, with backend/.venv/Scripts on PATH
npm run test:e2e -- tests/knowledge-curation.spec.ts tests/knowledge-field.spec.ts tests/knowledge-panel.spec.ts --timeout=25000
npm run build
```

Regression coverage includes canonical identity surviving candidate restoration, alias reuse after merging, duplicate-name validation, persisted resource links including deletion of the last suggested link, merge preview without mutation, same-name objects of different classifications, source ownership, same-paper endpoint validation, evidence verification, reversible review decisions, persisted metadata edits and keyboard focus. Migration coverage upgrades a populated 0011 database and checks preserved candidates, confirmations, quotes and foreign keys.

Independent code review identified identity restoration, retired alias keys, callbacks after unmount, collection request races and overlapping action state. These were corrected before the final regression and build.

Existing warnings are a Starlette/httpx deprecation and the frontend bundle-size advisory.

## Real-library visual and navigation checks

Checked the running application at 1440 × 960 and a narrow 800 × 820 viewport in light and dark themes.

- ReAct dossier: two related papers, 12 relationships and 19 source quotes.
- Opened Reflexion from a relationship endpoint, then opened its source quote. Navigation selected Reflexion and the matching PDF page rather than the first paper in the object dossier.
- Verified metadata editing and the explicit merge preview visually; no real object edit or merge was submitted.
- No browser page errors. The narrow dossier had no horizontal overflow: content width 719 px, scroll width 719 px.
- Verified the dark theme from persisted theme preference; the dossier background was `rgb(40, 36, 33)`.

Local screenshots and browser reports are in `.local-runtime/knowledge-curation-debug/`: `react-object.png`, `react-relations.png`, `reflexion-sources.png`, `object-editor.png`, `merge-preview.png`, `narrow-dark.png` and `real-ui.json`. These are local verification artifacts, excluded from version control.

## Migration and data preservation

Created a SQLite backup before applying `0012_knowledge_curation`:

`D:\paper_reader\.local-runtime\backups\before-knowledge-curation-20261019-223431.db`

The migration adds object links, merge redirects and the append-only change table. The owned backend was restarted after checking that no analysis task was queued or running. After the final restart, `/api/health` returned `ok`, the real ReAct dossier loaded, and a read-only merge preview returned the current preview schema including `relations_to_review`.

Compared every pre-existing column and row against the backup:

| Table | Before / after | Original values unchanged |
| --- | --- | --- |
| knowledge_entities | 25 / 25 | Yes |
| knowledge_candidates | 49 / 49 | Yes |
| knowledge_relations | 36 / 36 | Yes |
| notes | 3 / 3 | Yes |
| evidence | 5,368 / 5,368 | Yes |

The live change table remains empty, confirming that real-library checks did not submit curation mutations. Schema revision is `0012_knowledge_curation`; `PRAGMA foreign_key_check` returned no violations. The exact counts and row fingerprints are saved in `.local-runtime/knowledge-curation-debug/data-preservation.json`.

## Boundaries

This iteration improves identity, maintenance, review and provenance. It does not re-run model extraction or establish that every existing extracted semantic claim is correct. Original evidence remains authoritative for review. Merge confirmation retains historical rows but has no automatic unmerge action. Manual relationship creation requires objects already present in its source paper; unsupported cross-paper evidence is rejected. No paid model calls, commits or pushes were made for this iteration.
