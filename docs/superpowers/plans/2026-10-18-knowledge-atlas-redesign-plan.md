# Knowledge Atlas Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat method-evolution and entity catalog views with an evidence-backed knowledge atlas that audits coverage, resolves pending relations, and exposes a full entity dossier.

**Architecture:** Keep extraction and paper-local evidence as the source of truth. Add a read-only audit projection and a detail projection over existing candidates, canonical entities, papers, relations and source chunks; add a narrowly scoped relation-resolution mutation for unresolved edges. Render the field page as an SVG evidence map plus an entity dossier drawer, with no new model call required for the first pass.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, React/TypeScript, SVG, existing Playwright and pytest suites.

---

### Task 1: Add evidence audit and entity dossier contracts

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/services/knowledge_audit.py`
- Modify: `backend/app/api/knowledge.py`
- Modify: `backend/app/services/serialization.py`
- Test: `backend/tests/test_knowledge_audit.py`

- [ ] **Step 1: Write failing audit and dossier tests**

```python
def test_react_audit_distinguishes_covered_ignored_and_missing(db_session, react_paper):
    audit = audit_paper_knowledge(react_paper)
    assert audit.coverage['method']['ReAct']['state'] == 'confirmed'
    assert audit.coverage['metric']['exact match (EM)']['state'] in {'ignored', 'missing'}
    assert any(item['name'] == 'Inner Monologue' for item in audit.suggestions)

def test_entity_dossier_contains_related_papers_relations_evidence_and_links(client, confirmed_react_entity):
    response = client.get(f"/api/knowledge/entities/{confirmed_react_entity.id}")
    assert response.status_code == 200
    body = response.json()
    assert body['papers']
    assert body['evidence']
    assert body['relations']
    assert any(link['kind'] == 'search' for link in body['links'])
```

- [ ] **Step 2: Run the focused tests and verify the missing service/route failure**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_knowledge_audit.py -q`

Expected: FAIL because the audit service and entity dossier route do not exist.

- [ ] **Step 3: Implement deterministic audit projection**

Create `audit_paper_knowledge(paper)` that scans existing candidates and source chunks without calling a model. It must preserve candidate lifecycle state and return per-category records for `method`, `baseline`, `ablation`, `component`, `dataset`, `benchmark`, `task`, `metric`, and `related_method`. Each record includes `name`, `state` (`confirmed|candidate|ignored|missing`), `candidate_id`, `evidence_count`, and `why`. Use a small alias table for the ReAct vocabulary (`CoT`, `CoT-SC`, `EM`, `SR`, `Inner Monologue`, `SayCan`, `WebGPT`, `Wikipedia API`) and a generic fallback that searches normalized source text. Suggestions are source-grounded only and include source chunk IDs and quotes.

- [ ] **Step 4: Implement dossier serialization and routes**

Add `KnowledgeAuditRead`, `KnowledgeEntityDetailRead`, `KnowledgeEntityPaperRead`, `KnowledgeEntityLinkRead`, and `KnowledgeRelationResolution` schemas. Add:

```text
GET /api/papers/{paper_id}/knowledge/audit
GET /api/knowledge/entities/{entity_id}
```

The dossier must include canonical entity metadata, every paper-local candidate using it, related papers, confirmed/pending relations, deduplicated source evidence, and curated/search links. Use direct links for known ReAct entities and safe search links for unknown names; label link provenance.

- [ ] **Step 5: Run focused backend tests**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_knowledge_audit.py backend/tests/test_knowledge_api.py -q`

### Task 2: Make unresolved relations actionable

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/knowledge.py`
- Modify: `backend/app/api/knowledge.py`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Test: `backend/tests/test_knowledge_audit.py`

- [ ] **Step 1: Write failing resolution tests**

```python
def test_resolve_unresolved_relation_creates_target_entity_and_confirms_edge(client, unresolved_butler_relation):
    response = client.post(
        f"/api/knowledge/relations/{unresolved_butler_relation.id}/resolve",
        json={'target_name': 'BUTLER', 'target_type': 'method'},
    )
    assert response.status_code == 200
    assert response.json()['status'] == 'confirmed'
    assert response.json()['target_candidate_id']
```

- [ ] **Step 2: Run the test and verify the route is absent**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_knowledge_audit.py::test_resolve_unresolved_relation_creates_target_entity_and_confirms_edge -q`

Expected: FAIL with 404.

- [ ] **Step 3: Implement safe relation resolution**

Add `resolve_relation` to create or reuse a canonical target entity, create a paper-local candidate with `status='confirmed'` only when the relation already has literal source evidence, attach the candidate ID to the relation, set relation status to `confirmed`, and preserve the original quote. Reject invalid entity types and empty names. Make repeated resolution idempotent.

- [ ] **Step 4: Add API types and methods**

Add `KnowledgeAudit`, `KnowledgeEntityDetail`, `KnowledgeEntityLink`, and `resolveKnowledgeRelation` to the frontend contracts. The mutation must return the updated relation and refresh the detail view.

- [ ] **Step 5: Run backend knowledge tests**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_knowledge_audit.py backend/tests/test_knowledge_service.py backend/tests/test_knowledge_api.py -q`

### Task 3: Build the evidence map visualization

**Files:**
- Create: `frontend/src/components/KnowledgeEvolutionMap.tsx`
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/locales/zh-CN.json`
- Modify: `frontend/src/locales/en-US.json`
- Test: `frontend/tests/knowledge-field.spec.ts`

- [ ] **Step 1: Write failing Playwright assertions**

```ts
test('method evolution renders an evidence map with actionable pending relation', async ({ page }) => {
  await openKnowledgePage(page)
  await page.getByRole('button', { name: '方法演进', exact: true }).click()
  await expect(page.locator('.knowledge-evolution-map')).toBeVisible()
  await expect(page.locator('.knowledge-map-node[data-layer="primary"]')).toContainText('ReAct')
  await expect(page.locator('.knowledge-map-pending')).toContainText('BUTLER')
  await page.getByRole('button', { name: /BUTLER/ }).click()
  await expect(page.locator('.knowledge-entity-dossier')).toBeVisible()
})
```

- [ ] **Step 2: Run the focused test and verify the new map is absent**

Run: `cd frontend; npx playwright test tests/knowledge-field.spec.ts -g "method evolution"`

Expected: FAIL because the new map and dossier do not exist.

- [ ] **Step 3: Implement the SVG evidence map**

Create a responsive SVG map with a central primary method node, a curved main-line rail for lineage, lower-weight baseline arcs, a distinct dashed ablation arc, an evaluation halo, and a component orbit. Use relation family and importance from the API, never infer geometry from DOM cards. Add accessible buttons for every node and pending edge. Clicking any node opens the dossier; clicking a pending edge opens the resolution state. Keep descriptions and source actions in a compact inspector beside the map.

- [ ] **Step 4: Replace the old evolution list**

Use `KnowledgeEvolutionMap` in the `evolution` tab. Load `knowledgeRelations('all')`, the paper audit packages, and entity details lazily. Remove the old multi-card lane layout from the evolution path. Keep the citation graph tab unchanged.

- [ ] **Step 5: Run focused frontend tests and build**

Run: `cd frontend; npx playwright test tests/knowledge-field.spec.ts -g "method evolution"`; `npm run build`

### Task 4: Replace the flat catalog with entity dossiers

**Files:**
- Create: `frontend/src/components/KnowledgeEntityDossier.tsx`
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/locales/zh-CN.json`
- Modify: `frontend/src/locales/en-US.json`
- Test: `frontend/tests/knowledge-field.spec.ts`

- [ ] **Step 1: Add failing catalog interaction assertions**

```ts
test('catalog opens an entity dossier with papers, evidence and external links', async ({ page }) => {
  await openKnowledgePage(page)
  await page.getByRole('button', { name: '目录', exact: true }).click()
  await page.getByRole('button', { name: 'HotPotQA', exact: true }).click()
  await expect(page.locator('.knowledge-entity-dossier')).toContainText('HotPotQA')
  await expect(page.locator('.knowledge-dossier-papers')).toContainText('ReAct')
  await expect(page.locator('.knowledge-dossier-links')).toContainText(/官网|GitHub|搜索/)
})
```

- [ ] **Step 2: Run the test and verify the old catalog cannot satisfy it**

Run: `cd frontend; npx playwright test tests/knowledge-field.spec.ts -g "catalog opens"`

Expected: FAIL because catalog items are not interactive and no dossier exists.

- [ ] **Step 3: Implement the entity index and dossier**

Render a slim index with search, type filters, state counts and names; render the selected entity as a dossier with a short definition, role badge, related paper list, relation list, evidence excerpts, and links. Use a drawer on narrow screens and an anchored inspector on wide screens. Every paper/source row opens the existing reader locator.

- [ ] **Step 4: Add unresolved relation controls**

In the dossier's pending relation section, show the source quote and an inline target field/type selector. Submit `resolveKnowledgeRelation`; update the map and dossier without losing selection.

- [ ] **Step 5: Run focused frontend tests and build**

Run: `cd frontend; npx playwright test tests/knowledge-field.spec.ts`; `npm run build`

### Task 5: Re-audit ReAct and run complete verification

**Files:**
- Create: `docs/superpowers/evidence/2026-10-18-knowledge-atlas-review.md`
- Modify: `backend/tests/test_real_paper_import.py` if present, otherwise add a focused audit fixture test

- [ ] **Step 1: Exercise the actual ReAct database record**

Call the audit endpoint for `paper-934bdcb94a0d4147` and record the states for ReAct, CoT, CoT-SC, Act, Standard, ReAct-IM, BUTLER, all four benchmarks, tasks, metrics, thought/sparse reasoning and related methods. Confirm that ignored rows remain visible as ignored and unresolved BUTLER is resolvable.

- [ ] **Step 2: Run complete verification**

Run:

```text
backend/.venv/Scripts/python.exe -m pytest backend -q
cd frontend; npm run build
cd frontend; npx playwright test tests/knowledge-field.spec.ts tests/knowledge-panel.spec.ts tests/research-activity.spec.ts tests/workspace.spec.ts -g "method evolution|catalog opens|knowledge panel|research activity|real PDF import"
git diff --check
```

- [ ] **Step 3: Save evidence and report remaining limits**

Record exact outputs, the ReAct audit package, and any source-grounding gaps. Do not claim full extraction for a field unless the audit has evidence for it.
