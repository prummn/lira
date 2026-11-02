import json

from sqlalchemy import select

from app.models import Collection, CollectionPaper, KnowledgeCandidate, KnowledgeMaintenanceIssue, KnowledgeRelation, Paper, PaperChunk
from app.services import knowledge_maintenance as maintenance
from app.services.knowledge_steward import apply_batch, build_bundle
from app.services.knowledge import normalize_name


def test_alias_collision_defers_one_identity_without_aborting_safe_decisions(tmp_path):
    from app.models import KnowledgeEntity
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = source(session)
        paper.chunks[0].content += ' We use Shared (Long Shared).'
        session.add(KnowledgeEntity(id='owner', entity_type='method', name='Long Shared',
            normalized_name=normalize_name('Long Shared'), aliases_json='[]', status='active'))
        session.flush()
        citation = [{'chunk_id':'source','quote':paper.chunks[0].content}]
        report = apply_batch(session, paper, {'candidates':[
            {'name':'Shared','entity_type':'method','role':'used','aliases':['Long Shared'],
             'confidence':.99,'citations':citation},
            {'name':'SWE-smith','entity_type':'method','role':'proposed','confidence':.99,'citations':citation},
        ]}, build_bundle(session,paper))
        assert report['objects_confirmed'] == 1 and report['deferred'] == 1
        assert session.scalar(select(KnowledgeEntity).where(KnowledgeEntity.normalized_name=='shared')) is None
        assert session.get(KnowledgeCandidate,'smith-object').status == 'confirmed'
from test_knowledge_service import make_db


def source(session):
    paper = Paper(id='smith', title='SWE-smith')
    paper.chunks = [PaperChunk(id='source', page=1, section='Introduction',
        content='We introduce SWE-smith. SWE-smith uses ReAct to generate tasks.')]
    session.add(paper); session.flush()
    for key, name in [('smith-object', 'SWE-smith'), ('react-object', 'ReAct')]:
        session.add(KnowledgeCandidate(id=key, paper_id=paper.id, name=name, normalized_name=normalize_name(name),
            entity_type='method', role='proposed' if key == 'smith-object' else 'used', status='new',
            evidence_json=json.dumps([{'chunk_id': 'source', 'quote': name}])))
    session.flush()
    return paper


def test_supported_object_reviews_settle_endpoints_before_relation_review(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = source(session)
        edge = KnowledgeRelation(id='edge', paper_id=paper.id, relation='requires_concept',
            source_name='SWE-smith', source_normalized_name=normalize_name('SWE-smith'), target_name='ReAct', target_normalized_name='react',
            status='unresolved', evidence_json='[]')
        session.add(edge); session.flush()
        citation = [{'chunk_id': 'source', 'quote': 'SWE-smith uses ReAct to generate tasks.'}]
        result = apply_batch(session, paper, {
            'object_reviews': [{'candidate_id': key, 'verdict': 'supported', 'confidence': .99,
                'reason': 'The original explicitly describes this method.', 'citations': citation}
                for key in ('smith-object', 'react-object')],
            'reviews': [{'relation_id': 'edge', 'verdict': 'supported', 'confidence': .99,
                'reason': 'An explicitly used component.', 'citations': citation}],
        }, build_bundle(session, paper))
        assert result['objects_confirmed'] == 2
        assert edge.status == 'confirmed'


def test_changed_snapshot_does_not_duplicate_an_already_queued_paper(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = source(session)
        first = maintenance.prepare_run(session, scope_type='papers', paper_ids=[paper.id])
        session.commit()
        session.get(KnowledgeCandidate, 'smith-object').description = 'Updated extraction'
        session.flush()
        second = maintenance.prepare_run(session, scope_type='papers', paper_ids=[paper.id])
        assert second.id == first.id
        assert len(list(session.scalars(select(KnowledgeMaintenanceIssue)))) == 1


def test_batch_error_is_not_attached_to_a_paper_that_has_not_failed(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = source(session)
        run = maintenance.prepare_run(session, scope_type='library')
        run.status = 'partial'; run.error_message = 'Another paper failed its citation check'
        state = maintenance.backlog(session, scope_type='papers', paper_ids=[paper.id])
        assert state['items'][0]['status'] == 'queued'
        assert state['items'][0]['error'] is None


def test_scope_backlog_includes_paper_jobs_outside_the_latest_collection_batch(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = source(session)
        session.add(Collection(id='agents', name='Agents'))
        session.flush(); session.add(CollectionPaper(collection_id='agents', paper_id=paper.id)); session.flush()
        maintenance.prepare_run(session, scope_type='papers', paper_ids=[paper.id])
        maintenance.prepare_run(session, scope_type='library')
        session.flush()
        state = maintenance.backlog(session, scope_type='collection', scope_id='agents')
        assert state['pending_papers'] == 1
        assert state['pending_objects'] == 2
        assert state['items'][0]['paper_id'] == paper.id
        assert state['items'][0]['status'] == 'queued'
        empty = maintenance.backlog(session, scope_type='papers', paper_ids=['outside'])
        assert empty['pending_papers'] == 0 and empty['items'] == []


def test_duplicate_scopes_reuse_a_completed_paper_without_another_model_call(tmp_path):
    database = make_db(tmp_path)
    class Curator:
        mode = 'remote'; configured = True; last_usage = {}; calls = 0
        def audit_knowledge_bundle(self, bundle):
            self.calls += 1
            return {'summary': 'The source has been checked.'}
    provider = Curator()
    with database.sessions() as session:
        paper = source(session); session.commit()
        first = maintenance.prepare_run(session, scope_type='papers', paper_ids=[paper.id])
        second = maintenance.prepare_run(session, scope_type='library')
        session.commit()
        maintenance.execute_run(session, first, provider, max_calls=1); session.commit()
        maintenance.execute_run(session, second, provider, max_calls=1); session.commit()
        assert provider.calls == 1
        assert second.status == 'complete'


def test_backlog_api_returns_current_scope_without_changing_knowledge(client):
    with client.app.state.database.sessions() as session:
        source(session); session.commit()
        maintenance.prepare_run(session, scope_type='papers', paper_ids=['smith']); session.commit()
    response = client.get('/api/knowledge/maintenance/backlog?scope_type=papers&paper_ids=smith')
    assert response.status_code == 200
    assert response.json()['pending_papers'] == 1
    assert response.json()['pending_objects'] == 2
    assert client.get('/api/knowledge/maintenance/backlog?scope_type=papers&paper_ids=outside').json()['items'] == []


def test_explicit_force_rechecks_even_a_completed_unchanged_paper(tmp_path):
    database = make_db(tmp_path)
    class Curator:
        mode = 'remote'; configured = True; last_usage = {}; calls = 0
        def audit_knowledge_bundle(self, bundle):
            self.calls += 1
            return {'summary': 'The source has been checked.'}
    provider = Curator()
    with database.sessions() as session:
        paper = source(session); session.commit()
        first = maintenance.prepare_run(session, scope_type='papers', paper_ids=[paper.id])
        maintenance.execute_run(session, first, provider, max_calls=1); session.commit()
        forced = maintenance.prepare_run(session, scope_type='papers', paper_ids=[paper.id], force=True)
        maintenance.execute_run(session, forced, provider, max_calls=1); session.commit()
        assert provider.calls == 2


def test_new_success_supersedes_an_older_failed_check_in_backlog(tmp_path):
    database = make_db(tmp_path)
    class Curator:
        mode = 'remote'; configured = True; last_usage = {}
        def audit_knowledge_bundle(self, bundle):
            return {'summary': 'Checked; some uncertainty remains.'}
    with database.sessions() as session:
        paper = source(session); session.commit()
        old = maintenance.prepare_run(session, scope_type='papers', paper_ids=[paper.id])
        issue = session.scalar(select(KnowledgeMaintenanceIssue).where(KnowledgeMaintenanceIssue.run_id == old.id))
        old.status = 'failed'; issue.status = 'needs_review'; issue.reasoning = 'Old failure'
        session.commit()
        fresh = maintenance.prepare_run(session, scope_type='papers', paper_ids=[paper.id], force=True)
        maintenance.execute_run(session, fresh, Curator(), max_calls=1); session.commit()
        current = maintenance.backlog(session, scope_type='papers', paper_ids=[paper.id])
        assert current['checked_papers'] == 1 and current['pending_papers'] == 0
        assert current['items'][0]['status'] == 'needs_review'
        assert current['items'][0]['error'] is None


def test_supported_review_cannot_bypass_rejected_canonical_identity(tmp_path):
    from test_knowledge_steward_review import paper_source, existing_alias_entity
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = paper_source(session)
        entity = existing_alias_entity(session)
        session.add(KnowledgeCandidate(id='rejected', paper_id=paper.id, entity_type='method',
            name=entity.name, normalized_name=entity.normalized_name, entity_id=entity.id,
            aliases_json=json.dumps(['ReAct']), status='rejected', evidence_json='[]'))
        session.add(KnowledgeCandidate(id='pending-alias', paper_id=paper.id, entity_type='method',
            name='ReAct', normalized_name='react', role='used', status='new', evidence_json='[]'))
        session.flush()
        report = apply_batch(session, paper, {'object_reviews': [{'candidate_id': 'pending-alias',
            'verdict': 'supported', 'confidence': .99, 'reason': 'The source names the method.',
            'citations': [{'chunk_id': paper.chunks[0].id, 'quote': 'ReAct'}]}]}, build_bundle(session, paper))
        assert session.get(KnowledgeCandidate, 'pending-alias').status == 'new'
        assert report['protected'] >= 1


def test_pending_evidence_gets_review_budget_before_incidental_neighbors(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = source(session)
        paper.chunks.append(PaperChunk(id='refs', page=2, section='References', content='References'))
        paper.chunks.extend(PaperChunk(id=f'appendix-{i:03}', page=3+i, section='A Appendix',
            content=(f'Evidence block {i}. ' + 'Neighbor detail. '*180)) for i in range(25))
        session.flush()
        for key in (0, 4, 24):
            session.add(KnowledgeCandidate(id=f'pending-{key}', paper_id=paper.id, name=f'Object {key}',
                normalized_name=f'object {key}', entity_type='concept', role='used', status='new',
                evidence_json=json.dumps([{'chunk_id':f'appendix-{key:03}', 'quote':f'Evidence block {key}.'}])))
        session.flush()
        bundle = build_bundle(session, paper)
        assert 'appendix-024' in {c['chunk_id'] for c in bundle['review_chunks']}
