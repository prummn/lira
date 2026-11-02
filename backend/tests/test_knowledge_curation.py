"""Researcher curation keeps identity separate from paper-local evidence."""
import json

import pytest

from app.models import KnowledgeCandidate, KnowledgeEntity, KnowledgeRelation, Paper, PaperChunk


@pytest.fixture
def registry(client):
    with client.app.state.database.sessions() as session:
        for pid in ('a', 'b'):
            paper = Paper(id=pid, title=f'Paper {pid.upper()}')
            paper.chunks.append(PaperChunk(id=f'chunk-{pid}', page=2, section='Method', content='Reflexion uses ReAct. HotpotQA is evaluated.'))
            session.add(paper)
        session.flush()
        for eid, name, kind in [('reflexion', 'Reflexion', 'method'), ('react', 'ReAct', 'method'), ('duplicate', 'Reason and Act', 'method'), ('dataset', 'HotpotQA', 'dataset'), ('benchmark', 'HotpotQA', 'benchmark')]:
            session.add(KnowledgeEntity(id=eid, name=name, normalized_name=name.casefold(), entity_type=kind))
        session.flush()
        for cid, pid, eid, name, kind in [('ca', 'a', 'react', 'ReAct', 'method'), ('cb', 'b', 'react', 'ReAct', 'method'), ('cf', 'b', 'reflexion', 'Reflexion', 'method'), ('cd', 'a', 'duplicate', 'Reason and Act', 'method'), ('ds', 'a', 'dataset', 'HotpotQA', 'dataset'), ('bm', 'b', 'benchmark', 'HotpotQA', 'benchmark')]:
            session.add(KnowledgeCandidate(id=cid, paper_id=pid, entity_id=eid, name=name, normalized_name=name.casefold(), entity_type=kind, role='used', status='confirmed', confidence=.9, evidence_json=json.dumps([{'chunk_id':f'chunk-{pid}', 'page':2, 'quote':'HotpotQA' if kind != 'method' else 'ReAct'}])))
        session.flush()
        session.add(KnowledgeRelation(id='r', paper_id='b', relation='requires_concept', source_name='Reflexion', source_normalized_name='reflexion', target_name='ReAct', target_normalized_name='react', source_candidate_id='cf', target_candidate_id='cb', status='confirmed', evidence_json=json.dumps([{'chunk_id':'chunk-b','page':2,'quote':'Reflexion uses ReAct.'}])))
        session.add(KnowledgeRelation(id='bench-r', paper_id='b', relation='evaluated_on', source_name='Reflexion', source_normalized_name='reflexion', target_name='HotpotQA', target_normalized_name='hotpotqa', source_candidate_id='cf', target_candidate_id='bm', status='confirmed', evidence_json=json.dumps([{'chunk_id':'chunk-b','page':2,'quote':'HotpotQA is evaluated.'}])))
        session.commit()
    return client


def test_dossier_sources_have_owning_paper_and_homonyms_do_not_leak(registry):
    detail = registry.get('/api/knowledge/entities/react').json()
    assert {(e['paper_id'], e['paper_title']) for e in detail['evidence']} == {('a', 'Paper A'), ('b', 'Paper B')}
    assert all(e['page'] == 2 for e in detail['evidence'])
    dataset = registry.get('/api/knowledge/entities/dataset').json()
    assert dataset['relations'] == []
    assert {p['paper_id'] for p in dataset['papers']} == {'a'}


def test_metadata_aliases_links_persist_without_rewriting_source(registry):
    payload = {'name':'Reasoning and Acting', 'entity_type':'method', 'aliases':['ReAct', ' ReAct '], 'description':'Reasoning with actions.', 'links':[{'kind':'paper','label':'Original paper','url':'https://arxiv.org/abs/2210.03629'}]}
    saved = registry.patch('/api/knowledge/entities/react', json=payload)
    assert saved.status_code == 200, saved.text
    detail = registry.get('/api/knowledge/entities/react').json()
    assert detail['aliases'] == ['ReAct']
    assert detail['links'][0]['source'] == 'user'
    assert detail['candidates'][0]['name'] == payload['name']
    assert detail['candidates'][0]['extracted_name'] == 'ReAct'
    assert detail['history'][0]['action'] == 'edit_entity'
    with registry.app.state.database.sessions() as session:
        assert session.get(KnowledgeCandidate, 'ca').name == 'ReAct'
    relation = registry.get('/api/knowledge/relations?status=all').json()['items'][0]
    assert relation['target_entity_id'] == 'react'
    assert relation['target_name'] == payload['name']


def test_alias_namespace_and_url_validation(registry):
    collision = registry.patch('/api/knowledge/entities/duplicate', json={'name':'Reason and Act','entity_type':'method','aliases':['ReAct']})
    assert collision.status_code == 409
    assert 'ReAct' in collision.json()['detail']
    unsafe = registry.patch('/api/knowledge/entities/react', json={'name':'ReAct','entity_type':'method','links':[{'kind':'paper','label':'bad','url':'javascript:alert(1)'}]})
    assert unsafe.status_code == 422
    blank = registry.patch('/api/knowledge/entities/react', json={'name':'   ','entity_type':'method'})
    assert blank.status_code == 422


def test_merge_preview_and_execution_preserve_quotes_and_redirect(registry):
    preview = registry.post('/api/knowledge/entities/duplicate/merge-preview', json={'target_id':'react'})
    assert preview.status_code == 200, preview.text
    assert preview.json()['candidate_count'] == 1
    assert preview.json()['aliases'] == ['Reason and Act']
    merged = registry.post('/api/knowledge/entities/duplicate/merge', json={'target_id':'react'})
    assert merged.status_code == 200, merged.text
    assert merged.json()['id'] == 'react'
    assert registry.get('/api/knowledge/entities/duplicate').json()['id'] == 'react'
    assert 'duplicate' not in {x['id'] for x in registry.get('/api/knowledge/entities').json()['items']}
    with registry.app.state.database.sessions() as session:
        assert session.get(KnowledgeCandidate, 'cd').entity_id == 'react'
        assert session.get(KnowledgeCandidate, 'cd').name == 'Reason and Act'
        assert session.get(KnowledgeEntity, 'duplicate').merged_into_id == 'react'
    assert any(h['action'] == 'merge_entity' for h in merged.json()['history'])
    assert registry.post('/api/knowledge/entities/dataset/merge-preview', json={'target_id':'benchmark'}).status_code == 409


def test_relation_review_edit_and_restore_validate_endpoints(registry):
    rejected = registry.post('/api/knowledge/relations/r/reject')
    assert rejected.status_code == 200 and rejected.json()['status'] == 'rejected'
    restored = registry.post('/api/knowledge/relations/r/restore')
    assert restored.status_code == 200 and restored.json()['status'] == 'candidate'
    wrong_paper = registry.patch('/api/knowledge/relations/r', json={'source_candidate_id':'ca','target_candidate_id':'cb','relation':'compares_with','description':'Compare'})
    assert wrong_paper.status_code == 422
    saved = registry.patch('/api/knowledge/relations/r', json={'source_candidate_id':'cb','target_candidate_id':'cf','relation':'compares_with','description':'A corrected comparison'})
    assert saved.status_code == 200, saved.text
    assert saved.json()['source_entity_id'] == 'react'
    assert saved.json()['status'] == 'candidate'
    confirmed = registry.post('/api/knowledge/relations/r/confirm')
    assert confirmed.status_code == 200 and confirmed.json()['status'] == 'confirmed'
    assert registry.get('/api/knowledge/entities/react').json()['history'][0]['action'] == 'confirm_relation'


def test_relation_confirmation_rejects_ignored_endpoint_and_invalid_quote(registry):
    response = registry.post('/api/knowledge/candidates/cb/reject')
    assert response.status_code == 200, response.text
    state = registry.get('/api/knowledge/relations?status=all').json()['items']
    assert next(r for r in state if r['id'] == 'r')['status'] == 'unresolved', (response.json()['status'], [(r['id'],r['status'],r['source_candidate_id'],r['target_candidate_id']) for r in state])
    assert registry.post('/api/knowledge/relations/r/confirm').status_code == 409
    with registry.app.state.database.sessions() as session:
        assert session.get(KnowledgeRelation, 'r').status != 'confirmed'
        session.get(KnowledgeCandidate, 'cb').status = 'confirmed'
        session.get(KnowledgeRelation, 'r').evidence_json = '[{"chunk_id":"chunk-a","quote":"Reflexion uses ReAct."}]'
        session.commit()
    assert registry.post('/api/knowledge/relations/r/confirm').status_code == 409


def test_resolve_target_does_not_confirm_missing_source(registry):
    with registry.app.state.database.sessions() as session:
        rel = session.get(KnowledgeRelation, 'r')
        rel.source_candidate_id = None
        rel.target_candidate_id = None
        rel.status = 'unresolved'
        session.commit()
    result = registry.post('/api/knowledge/relations/r/resolve', json={'target_name':'ReAct','target_type':'method'})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'unresolved'


def test_catalog_counts_and_scope(registry):
    all_items = registry.get('/api/knowledge/entities').json()['items']
    react = next(item for item in all_items if item['id'] == 'react')
    assert react['paper_count'] == 2 and react['relation_count'] == 1
    scoped = registry.get('/api/knowledge/entities?paper_ids=a').json()['items']
    assert 'reflexion' not in {item['id'] for item in scoped}
    assert next(item for item in scoped if item['id'] == 'react')['paper_count'] == 1


def test_manual_relationship_requires_owning_source_and_remains_reviewable(registry):
    body = {'source_candidate_id':'cf','target_candidate_id':'cb','relation':'compares_with','description':'Manually added comparison','evidence':[{'chunk_id':'chunk-b','page':999,'quote':'Reflexion uses ReAct.'}]}
    created = registry.post('/api/papers/b/knowledge/relations', json=body)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row['status'] == 'candidate' and row['evidence'][0]['page'] == 2
    assert row['run_id'] == 'manual'
    assert registry.post('/api/papers/b/knowledge/relations', json=body).status_code == 409
    body['relation'] = 'extends'
    body['evidence'][0]['chunk_id'] = 'chunk-a'
    assert registry.post('/api/papers/b/knowledge/relations', json=body).status_code == 422
    assert registry.post(f"/api/knowledge/relations/{row['id']}/confirm").status_code == 200


def test_restore_retains_manually_curated_type_and_identity(registry):
    saved = registry.patch('/api/knowledge/entities/react', json={'name':'Reasoning + Acting','entity_type':'concept','aliases':['ReAct']})
    assert saved.status_code == 200
    registry.post('/api/knowledge/candidates/ca/reject')
    restored = registry.post('/api/knowledge/candidates/ca/confirm', json={})
    assert restored.status_code == 200
    assert restored.json()['entity_id'] == 'react'
    assert restored.json()['entity_type'] == 'concept'
    assert restored.json()['name'] == 'Reasoning + Acting'


def test_released_merged_alias_can_be_used_without_unique_constraint_failure(registry):
    registry.post('/api/knowledge/entities/duplicate/merge', json={'target_id':'react'})
    registry.patch('/api/knowledge/entities/react', json={'name':'ReAct','entity_type':'method','aliases':[]})
    reused = registry.patch('/api/knowledge/entities/reflexion', json={'name':'Reason and Act','entity_type':'method','aliases':[]})
    assert reused.status_code == 200, reused.text


def test_removing_last_suggested_resource_link_stays_removed(registry):
    initial = registry.get('/api/knowledge/entities/react').json()
    assert any(link['source'] == 'curated' for link in initial['links'])
    saved = registry.patch('/api/knowledge/entities/react', json={'name':'ReAct','entity_type':'method','links':[]})
    assert saved.status_code == 200
    assert all(link['kind'] == 'search' for link in saved.json()['links'])


def test_merge_previews_relationships_that_need_review_instead_of_losing_them(registry):
    with registry.app.state.database.sessions() as session:
        session.add(KnowledgeRelation(id='duplicate-r',paper_id='a',relation='compares_with',source_name='ReAct',source_normalized_name='react',target_name='Reason and Act',target_normalized_name='reason and act',source_candidate_id='ca',target_candidate_id='cd',status='confirmed',evidence_json='[{"chunk_id":"chunk-a","quote":"Reflexion uses ReAct."}]'))
        session.commit()
    preview = registry.post('/api/knowledge/entities/duplicate/merge-preview',json={'target_id':'react'}).json()
    assert preview['relations_to_review'][0]['id'] == 'duplicate-r'
    registry.post('/api/knowledge/entities/duplicate/merge',json={'target_id':'react'})
    with registry.app.state.database.sessions() as session:
        assert session.get(KnowledgeRelation,'duplicate-r').status == 'conflict'
        assert session.get(Paper,'a').knowledge_status == 'needs_review'


@pytest.mark.parametrize('predicate,source_id,target_id', [
    ('uses_dataset', 'cf', 'cb'),
    ('evaluated_on', 'bm', 'cb'),
    ('compares_with', 'cf', 'metric-candidate'),
])
def test_confirmation_rejects_semantically_illegal_endpoint_types(registry, predicate, source_id, target_id):
    with registry.app.state.database.sessions() as session:
        session.add(KnowledgeEntity(id='metric', entity_type='metric', name='EM', normalized_name='em'))
        session.flush()
        session.add(KnowledgeCandidate(id='metric-candidate', paper_id='b', entity_id='metric',
            entity_type='metric', name='EM', normalized_name='em', status='confirmed',
            evidence_json='[{"chunk_id":"chunk-b","quote":"Reflexion uses ReAct."}]'))
        session.flush()
        relation = session.get(KnowledgeRelation, 'r')
        relation.source_candidate_id = source_id
        relation.target_candidate_id = target_id
        relation.relation = predicate
        relation.status = 'candidate'
        session.commit()
    assert registry.post('/api/knowledge/relations/r/confirm').status_code == 409


def test_unknown_predicate_cannot_be_confirmed(registry):
    from app.services.knowledge_curation import confirmable
    with registry.app.state.database.sessions() as session:
        relation = session.get(KnowledgeRelation, 'r')
        relation.relation = 'invented_relation'
        assert not confirmable(session, relation)


def test_edit_relation_rejects_illegal_types_before_saving(registry):
    response = registry.patch('/api/knowledge/relations/r', json={
        'source_candidate_id': 'cf', 'target_candidate_id': 'cb',
        'relation': 'uses_dataset', 'description': 'Not a dataset',
    })
    assert response.status_code == 422
    with registry.app.state.database.sessions() as session:
        assert session.get(KnowledgeRelation, 'r').relation == 'requires_concept'


def test_confirmation_uses_researcher_curated_entity_type(registry):
    with registry.app.state.database.sessions() as session:
        relation = session.get(KnowledgeRelation, 'r')
        relation.relation = 'evaluated_on'
        relation.status = 'candidate'
        # The extracted row remains a method; the researcher's canonical
        # correction makes the target a benchmark.
        session.get(KnowledgeEntity, 'react').entity_type = 'benchmark'
        session.commit()
    assert registry.post('/api/knowledge/relations/r/confirm').status_code == 200
