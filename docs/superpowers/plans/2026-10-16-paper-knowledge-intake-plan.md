# Paper Knowledge Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Turn every analyzed paper into source-linked knowledge candidates that can be reviewed in the reader, reconciled with a local field registry, and reused across papers without publishing unverified model guesses.

**Architecture:** Keep the existing staged intelligence harness and Paper Card as the single expensive model pass. Extend its validated JSON result with bounded entity and relation candidates, persist those candidates with exact `PaperChunk` evidence, and reconcile names locally against canonical entities. Expose small confirmation APIs and a reader-side Knowledge panel; the field page consumes only confirmed records. Paragraph extraction reuses the same contract with a cached, bounded request.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, Pydantic v2, existing staged provider harness/cache, React/TypeScript, Vitest/Playwright.

---

### Task 1: Add the knowledge data model and lifecycle migration

**Files:**
- Modify: `backend/app/models.py` (canonical entities, paper candidates, candidate evidence, relation candidates)
- Modify: `backend/app/schemas.py` (entity/relation lifecycle contracts)
- Create: `backend/migrations/versions/0010_paper_knowledge.py`
- Test: `backend/tests/test_knowledge_models.py`

- [x] **Step 1: Write failing model and schema tests**

```python
def test_candidate_requires_source_evidence_and_defaults_to_candidate(db_session, paper, chunk):
    candidate = KnowledgeCandidate(paper_id=paper.id, entity_type="dataset", name="HotpotQA", normalized_name="hotpotqa", status="candidate", evidence_json=json.dumps([{"chunk_id": chunk.id, "page": 2, "quote": "HotpotQA"}]))
    db_session.add(candidate); db_session.commit()
    assert candidate.status == "candidate"
    assert json.loads(candidate.evidence_json)[0]["chunk_id"] == chunk.id

def test_candidate_status_contract_rejects_unknown_status():
    with pytest.raises(ValidationError):
        KnowledgeCandidateRead(id="x", paper_id="p", entity_type="dataset", name="X", normalized_name="x", status="published", evidence=[])
```

- [x] **Step 2: Run `pytest backend/tests/test_knowledge_models.py -q` and verify the missing table/types fail.**

- [x] **Step 3: Implement focused SQLAlchemy tables**

Create `knowledge_entities` with `entity_type`, `name`, `normalized_name`, aliases/description JSON, and `status` (`active|needs_review|unsupported`). Create `knowledge_candidates` with paper/entity references, role, description, confidence, lifecycle status, evidence JSON, run metadata, and conflict JSON. Create `knowledge_relations` with source/target candidate/entity IDs, controlled relation kind, explanation, evidence JSON, lifecycle status, and run metadata. Add `Paper.knowledge_candidates` and `Paper.knowledge_relations` relationships with cascading paper-local deletion.

Add Pydantic models `KnowledgeEvidence`, `KnowledgeCandidateRead`, `KnowledgeRelationRead`, `KnowledgePaperRead`, `CandidateDecision`, and literal status/relation types. Require at least one evidence item for a candidate or relation and validate page numbers, quote strings, and confidence `[0,1]`.

- [x] **Step 4: Add Alembic migration `0010_paper_knowledge.py`**

Create the three tables, foreign keys to `papers`, indexes on normalized names/status, and a unique canonical entity key `(entity_type, normalized_name)`. Down migration drops relation candidates, paper candidates, then entities.

- [x] **Step 5: Run model, migration, and existing migration tests; commit `feat: add paper knowledge lifecycle schema`.**

Run: `pytest backend/tests/test_knowledge_models.py backend/tests/test_migrations.py -q`

### Task 2: Implement local reconciliation and candidate persistence

**Files:**
- Create: `backend/app/services/knowledge.py`
- Modify: `backend/app/services/intelligence.py`
- Modify: `backend/app/services/analysis.py`
- Test: `backend/tests/test_knowledge_service.py`

- [x] **Step 1: Write failing reconciliation tests**

```python
def test_reconcile_marks_new_known_alias_and_conflict(db_session, paper, chunk):
    create_canonical(db_session, "dataset", "HotpotQA", aliases=["Hotpot QA"])
    rows = reconcile_candidates(db_session, paper, [{"entity_type":"dataset","name":"Hotpot QA","description":"multi-hop QA","role":"used","confidence":.9,"evidence":[evidence(chunk,"Hotpot QA")]}], run_id="run-1")
    assert rows[0].status == "alias"

def test_confirmation_creates_or_updates_canonical_entity(db_session, candidate):
    confirm_candidate(db_session, candidate, name="HotpotQA")
    assert candidate.status == "confirmed"
    assert db_session.scalar(select(KnowledgeEntity).where(KnowledgeEntity.normalized_name == "hotpotqa"))

def test_relation_without_evidence_is_dropped(db_session, paper):
    assert persist_candidates(db_session, paper, [], [{"relation":"builds_on","source":"A","target":"B","evidence":[]}], "run") == []
```

- [x] **Step 2: Run the focused tests and verify they fail because the service is absent.**

- [x] **Step 3: Implement deterministic normalization and reconciliation**

Normalize Unicode, punctuation, whitespace, and case; compare canonical names and aliases. Assign `new`, `known`, `alias`, `conflict`, or `unresolved` without making any candidate canonical. Validate every evidence item against the paper's stored chunks (`quote` must be a literal substring) and discard unverifiable rows. Persist a stable candidate ID from paper/run/entity/evidence digest so retries are idempotent. Relations resolve candidate IDs by normalized names, retain unresolved endpoints, and never infer lineage from a reference-list-only mention.

- [x] **Step 4: Wire persistence into `persist_analysis_result` and the intelligence worker**

After the existing Paper Card is validated, read `AnalysisResult.knowledge_candidates` and `.knowledge_relations`, persist them in the same transaction, update a paper-level knowledge status in the report (`unread|candidates|partially_settled|settled|needs_review`), and preserve prior confirmed candidates on partial/failed runs. Add a local `confirm_candidate`, `reject_candidate`, and `edit_candidate` service that updates candidate status and canonical entity support counts.

- [x] **Step 5: Run backend tests and commit `feat: reconcile paper knowledge candidates`.**

### Task 3: Extend the staged intelligence contract without adding a second full-paper call

**Files:**
- Modify: `backend/app/providers/base.py`
- Modify: `backend/app/providers/harness.py`
- Modify: `backend/app/providers/cards.py`
- Modify: `backend/app/providers/openai_compatible.py`
- Modify: `prompts/paper_synthesize.txt`
- Modify: `prompts/paper_analysis.txt`
- Test: `backend/tests/test_knowledge_extraction.py`

- [x] **Step 1: Write failing parser tests**

```python
def test_synthesized_knowledge_candidates_are_source_scoped(fake_provider, chunks):
    result = analyze_full_paper(db, fake_provider, chunks)
    assert any(item.entity_type == "dataset" and item.name == "HotpotQA" for item in result.analysis.knowledge_candidates)
    assert all(item.citations for item in result.analysis.knowledge_candidates)

def test_invalid_knowledge_quote_is_rejected(fake_provider, chunks):
    result = parse_knowledge_payload({"knowledge_candidates":[{"entity_type":"method","name":"X","citation_ids":["missing"]}]}, ...)
    assert result == []
```

- [x] **Step 2: Run the focused tests and observe missing fields/parser failures.**

- [x] **Step 3: Add dataclasses and validation**

Add `KnowledgeCandidateEntry` and `KnowledgeRelationEntry` to `providers/base.py`, each carrying verified citations, role/description/confidence, and normalized relation kind. Add bounded schemas in `cards.py` with at most 64 candidates and 96 relations per synthesis. In `harness.py`, validate `candidate.citation_ids` only against the immutable evidence pool, convert them to `VerifiedCitation`, require literal source support, cap names/descriptions, and discard invalid entries with diagnostics. Parse the fields from the existing `paper_synthesize` response and attach them to `AnalysisResult`.

- [x] **Step 4: Update the synth prompt**

Extend the JSON contract to `{"card":...,"concepts":[],"knowledge_candidates":[],"knowledge_relations":[]}`. Require entity types (`paper|method|dataset|benchmark|task|metric|concept|venue`), roles (`proposed|used|baseline|cited|compared`), evidence IDs, and relation vocabulary (`builds_on|extends|compares_with|replaces|uses_dataset|evaluated_on|inspired_by|contrasts_with|requires_concept`). Tell the model that a bibliography entry alone cannot support a semantic relation and every row must cite an original source passage.

- [x] **Step 5: Keep the legacy provider compatible**

The non-staged OpenAI-compatible provider parses the same optional fields when present and returns empty lists otherwise. Existing Paper Card validation and cache fingerprints remain unchanged except for the prompt digest, so cached calls are invalidated exactly once when the contract changes.

- [x] **Step 6: Run extraction, harness, and full backend tests; commit `feat: extract source linked knowledge in staged analysis`.**

### Task 4: Add candidate and incremental paragraph APIs

**Files:**
- Create: `backend/app/api/knowledge.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/api/papers.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_knowledge_api.py`

- [x] **Step 1: Write failing API tests**

```python
def test_get_paper_knowledge_returns_candidates_and_status(client, analyzed_paper):
    response = client.get(f"/api/papers/{analyzed_paper.id}/knowledge")
    assert response.status_code == 200
    assert response.json()["paper_status"] == "candidates"

def test_confirm_candidate_is_idempotent_and_visible_in_field_registry(client, candidate):
    first = client.post(f"/api/knowledge/candidates/{candidate.id}/confirm", json={"name":"HotpotQA"})
    second = client.post(f"/api/knowledge/candidates/{candidate.id}/confirm", json={"name":"HotpotQA"})
    assert first.status_code == second.status_code == 200
    assert client.get("/api/knowledge/entities?entity_type=dataset").json()["items"]

def test_extract_paragraph_preserves_existing_translation_locator(client, paper, paragraph):
    response = client.post(f"/api/papers/{paper.id}/knowledge/paragraph", json={"paragraph_id":paragraph.id})
    assert response.status_code == 202
```

- [x] **Step 2: Run the API tests and verify 404/route failures.**

- [x] **Step 3: Implement read and decision routes**

`GET /papers/{id}/knowledge` returns paper status, grouped candidates, relations, confirmed/settled counts, and evidence geometry. `POST /knowledge/candidates/{id}/confirm`, `/reject`, and `/edit-confirm` update the lifecycle safely and return the updated paper package. `GET /knowledge/entities` supports `entity_type`, `query`, and `status`; `GET /knowledge/relations` returns confirmed evolution edges. Every source action returns `page`, `chunk_id`, `section`, `quote`, and the existing locator fields.

- [x] **Step 4: Implement `POST /papers/{id}/knowledge/paragraph`**

Accept a paragraph ID and bounded surrounding paragraph IDs. Reuse the current configured provider and model-call cache under operation `paper_knowledge_paragraph_v1`; validate evidence against the selected paragraph/source chunks, reconcile locally, and return `202` with new candidate IDs. Do not change `Paper.analysis`, translations, active reader locator, or existing confirmed records.

- [x] **Step 5: Run API tests and commit `feat: expose knowledge review and paragraph extraction APIs`.**

### Task 5: Add the reader Knowledge panel and first-pass/settled interaction

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/components/KnowledgePanel.tsx`
- Modify: `frontend/src/pages/ReaderPage.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/locales/zh-CN.json`
- Modify: `frontend/src/locales/en-US.json`
- Test: `frontend/tests/knowledge-panel.spec.ts`

- [x] **Step 1: Write failing Playwright tests**

```ts
test('first pass shows candidate status and source action', async ({page}) => {
  await openReader(page, paperId)
  await page.getByRole('tab', {name:'知识'}).click()
  await expect(page.getByText('新发现')).toBeVisible()
  await page.getByRole('button', {name:'查看原文'}).first().click()
  await expect(page.locator('.pdf-panel')).toBeVisible()
})

test('settled view collapses confirmed rows and keeps conflicts visible', async ({page}) => {
  await seedConfirmedCandidate()
  await openReader(page, paperId)
  await page.getByRole('tab', {name:'知识'}).click()
  await expect(page.getByText('已沉淀内容')).toBeVisible()
})
```

- [x] **Step 2: Run the focused Playwright test and verify the missing tab/component fails.**

- [x] **Step 3: Add frontend contracts and API methods**

Define candidate/relation/evidence types and `api.paperKnowledge`, `confirmKnowledgeCandidate`, `rejectKnowledgeCandidate`, `editConfirmKnowledgeCandidate`, `extractKnowledgeParagraph`, and `knowledgeEntities`. Keep errors inline and preserve the existing reader state.

- [x] **Step 4: Implement `KnowledgePanel`**

Render compact groups for methods, datasets/benchmarks, tasks/metrics, cited papers, and relations. Show status chips (`新发现`, `已有知识`, `别名匹配`, `冲突`, `待确认`), confidence, concise grounded description, and one source button. Confirm/edit/reject controls update only the panel query. Batch confirm is available per group. Confirmed rows collapse under “已沉淀内容”; conflict/unresolved rows stay open. `识别本段` calls the bounded endpoint and never changes bilingual selection or PDF position.

- [x] **Step 5: Add the panel as a new research notebook tab and polish CSS/locales**

Use the existing side panel surface, 10–12px labels, clear status colors, and a fixed-width source action. Add accessible labels and focus states; avoid large cards, gradient backgrounds, or opaque AI branding.

- [x] **Step 6: Run the focused Playwright tests, frontend build, and commit `feat: add reader knowledge review panel`.**

### Task 6: Project confirmed knowledge into the field page and librarian context

**Files:**
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `backend/app/services/librarian.py`
- Modify: `backend/app/api/knowledge.py`
- Modify: `frontend/src/locales/zh-CN.json`
- Modify: `frontend/src/locales/en-US.json`
- Test: `backend/tests/test_librarian_knowledge.py`
- Test: `frontend/tests/knowledge-field.spec.ts`

- [x] **Step 1: Write failing cross-paper tests**

Assert that a confirmed dataset appears in the dataset catalog, a confirmed `builds_on` relation appears in the evolution view, and the librarian retrieval context includes canonical entities plus source citations while candidate-only rows stay excluded.

- [x] **Step 2: Implement field projections**

Add `datasets/benchmarks`, `candidate inbox`, and confirmed method evolution sections to the existing Knowledge page. Reuse exact source buttons and expose unresolved/conflict counts. Keep existing paper comparison and citation graph intact.

- [x] **Step 3: Extend librarian context**

Load confirmed entities/relations and their supporting papers into the local metadata context. Label each item with evidence source and status; never include rejected or candidate-only rows as confirmed facts. Add tests and commit `feat: project confirmed knowledge into cross paper views`.

### Task 7: Real ReAct regression and full verification

**Files:**
- Modify: `backend/tests/test_real_paper_import.py` (or create if absent)
- Create: `docs/superpowers/evidence/2026-10-16-react-knowledge-intake.md`

- [x] **Step 1: Download/import ReAct `2210.03629` through the existing URL import path**

Use `POST /api/papers/import-url` with `https://arxiv.org/pdf/2210.03629`, `analyze=true`, and the configured provider. If the source is already present, force a fresh knowledge run while retaining prior confirmed knowledge.

- [x] **Step 2: Verify the result package**

Record paper title, task status, candidate counts, and evidence pages for ReAct, HotpotQA/FEVER/ALFWorld (when present in source), and at least one cited method relation. Open the Introduction in the reader, invoke `识别本段`, and confirm one candidate. Verify it appears in `/api/knowledge/entities` and the field page while the source locator still points to the same paragraph.

- [x] **Step 3: Run complete verification**

Run `pytest backend -q`, `npm run build` from `frontend`, focused Playwright tests for knowledge, reading, translation, and activity, then `git diff --check`. Save exact commands/results in the evidence note. Commit `test: verify ReAct knowledge intake` only if the real source run is reproducible without credentials in tests; keep downloaded PDFs out of git.

---

## Self-review

- The plan covers programmatic evidence validation, one unified model pass, local reconciliation, first-pass versus settled lifecycle, bounded paragraph extraction, field projections, librarian context, and real ReAct validation.
- Every model or relation row requires stored source evidence; bibliography presence alone cannot create a lineage edge.
- Existing analysis/translation/reading behavior remains independent; failed or partial tasks retain prior cards and confirmed knowledge.
- Tests are specified before implementation for schemas, reconciliation, API decisions, incremental extraction, reader states, field projections, and the real paper workflow.
