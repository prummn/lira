"""Adversarial regressions for source-backed automatic curation.

Every case uses an isolated temporary database and a local fake provider.
No external model or the user's library is accessed.
"""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import (KnowledgeCandidate, KnowledgeEntity, KnowledgeMaintenanceRun,
                        KnowledgeRelation, Paper, PaperChunk)
from app.providers.base import ProviderError
from app.services.knowledge_curation import edit_entity, record, snapshot
from app.services.knowledge_maintenance import execute_run, prepare_run
from app.services.knowledge_steward import apply_batch, build_bundle
from test_knowledge_service import make_db


def paper_source(session, identifier='p'):
    paper = Paper(id=identifier, title=identifier)
    paper.chunks = [PaperChunk(id='chunk-' + identifier, page=1, section='Introduction',
        content='TraceBench evaluates ReAct on HotpotQA. ReAct means Reasoning and Acting.')]
    session.add(paper)
    session.flush()
    return paper


def object_decision(paper, name, *, kind='method', entity_id=None, quote=None):
    return {'name': name, 'entity_type': kind, 'role': 'used', 'description': 'A source-backed object',
        'aliases': [], 'entity_id': entity_id, 'confidence': .99,
        'citations': [{'chunk_id': paper.chunks[0].id, 'quote': quote or name}]}


def existing_alias_entity(session):
    entity = KnowledgeEntity(id='canonical', entity_type='method', name='Reasoning and Acting',
        normalized_name='reasoning and acting', aliases_json=json.dumps(['ReAct']))
    session.add(entity)
    session.flush()
    return entity


def test_rejected_candidate_cannot_be_recreated_under_canonical_alias(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = paper_source(session)
        entity = existing_alias_entity(session)
        rejected = KnowledgeCandidate(id='researcher-rejected', paper_id=paper.id, entity_id=entity.id,
            entity_type='method', name=entity.name, normalized_name=entity.normalized_name,
            aliases_json=json.dumps(['ReAct']), status='rejected', role='used',
            evidence_json=json.dumps([{'chunk_id': paper.chunks[0].id, 'quote': 'ReAct'}]))
        session.add(rejected)
        session.flush()
        record(session, rejected, 'reject_candidate', {})
        session.flush()
        report = apply_batch(session, paper, {'candidates': [object_decision(paper, 'ReAct')]},
                             build_bundle(session, paper))
        session.flush()
        candidates = list(session.scalars(select(KnowledgeCandidate)))
        assert [(row.id, row.status) for row in candidates] == [(rejected.id, 'rejected')]
        assert report['protected'] >= 1


def test_old_relation_predicate_cannot_bypass_researcher_correction(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = paper_source(session)
        apply_batch(session, paper, {'candidates': [
            object_decision(paper, 'TraceBench', kind='benchmark'), object_decision(paper, 'ReAct'),
        ]}, build_bundle(session, paper))
        candidates = {row.name: row for row in session.scalars(select(KnowledgeCandidate))}
        relation = KnowledgeRelation(id='researcher-corrected', paper_id=paper.id, relation='builds_on',
            source_name='TraceBench', source_normalized_name='tracebench',
            target_name='ReAct', target_normalized_name='react',
            source_candidate_id=candidates['TraceBench'].id, target_candidate_id=candidates['ReAct'].id,
            status='confirmed', evidence_json=json.dumps([{'chunk_id': paper.chunks[0].id,
                'quote': 'TraceBench evaluates ReAct on HotpotQA.'}]))
        session.add(relation)
        session.flush()
        before = snapshot(relation)
        relation.relation = 'compares_with'
        record(session, relation, 'edit_relation', before)
        session.flush()
        decision = {'source_name': 'TraceBench', 'target_name': 'ReAct', 'relation': 'builds_on',
            'description': 'An old model inference the researcher already corrected', 'confidence': .99,
            'citations': [{'chunk_id': paper.chunks[0].id,
                          'quote': 'TraceBench evaluates ReAct on HotpotQA.'}]}
        report = apply_batch(session, paper, {'relations': [decision]}, build_bundle(session, paper))
        session.flush()
        assert [(row.id, row.relation) for row in session.scalars(select(KnowledgeRelation))] == [
            (relation.id, 'compares_with')]
        assert report['protected'] >= 1


def test_steward_cannot_restore_researcher_removed_entity_alias(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = paper_source(session)
        entity = existing_alias_entity(session)
        edit_entity(session, entity, SimpleNamespace(name=entity.name, entity_type='method',
            aliases=[], description='My canonical definition', links=[]))
        session.flush()
        assert json.loads(entity.aliases_json) == []
        item = object_decision(paper, 'ReAct', entity_id=entity.id,
                               quote='ReAct means Reasoning and Acting.')
        apply_batch(session, paper, {'candidates': [item]}, build_bundle(session, paper))
        session.flush()
        assert json.loads(entity.aliases_json) == []
        assert entity.description == 'My canonical definition'


def test_confirming_legacy_candidate_persists_this_batches_verified_evidence(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = paper_source(session)
        row = KnowledgeCandidate(id='legacy-empty-evidence', paper_id=paper.id, entity_type='method',
            name='ReAct', normalized_name='react', role='used', status='new', evidence_json='[]')
        session.add(row)
        session.flush()
        apply_batch(session, paper, {'candidates': [object_decision(paper, 'ReAct')]},
                    build_bundle(session, paper))
        session.flush()
        assert row.status == 'confirmed'
        assert any(item['chunk_id'] == paper.chunks[0].id and item['quote'] == 'ReAct'
                   for item in json.loads(row.evidence_json))


def test_repeated_invalid_paper_does_not_starve_other_papers(tmp_path):
    class FailFirstPaper:
        mode = 'remote'
        configured = True
        last_usage = {}

        def __init__(self):
            self.calls = []
            self.failing_paper = None

        def audit_knowledge_bundle(self, bundle):
            self.calls.append(bundle['paper_id'])
            self.failing_paper = self.failing_paper or bundle['paper_id']
            if bundle['paper_id'] == self.failing_paper:
                raise ProviderError('Repeated invalid reply for one paper', code='invalid_curation')
            return {'summary': 'No source-backed changes needed'}

    database = make_db(tmp_path)
    with database.sessions() as session:
        paper_source(session, 'a')
        paper_source(session, 'b')
        session.commit()
        run = prepare_run(session, scope_type='papers', paper_ids=['a', 'b'])
        provider = FailFirstPaper()
        for _ in range(3):
            execute_run(session, run, provider, max_calls=1)
            session.commit()
        assert set(provider.calls) == {'a', 'b'}


def test_legacy_run_without_recoverable_paper_scope_is_explicitly_stale(tmp_path):
    class NeverCalled:
        mode = 'remote'
        configured = True
        last_usage = {}

        def audit_knowledge_bundle(self, bundle):
            raise AssertionError('The lost scope cannot be guessed from unrelated library papers')

    database = make_db(tmp_path)
    with database.sessions() as session:
        paper_source(session)
        run = KnowledgeMaintenanceRun(id='legacy-without-scope', scope_type='papers', scope_id=None,
            status='partial', source_fingerprint='legacy-fingerprint',
            usage_json=json.dumps({'paper_count': 1, 'audit_issue_ids': [], 'call_times': []}))
        session.add(run)
        session.commit()
        execute_run(session, run, NeverCalled(), max_calls=1)
        session.commit()
        assert run.status == 'failed'
        assert run.error_message


def contextualized_method(session, verdict):
    paper = paper_source(session)
    apply_batch(session, paper, {'candidates': [
        object_decision(paper, 'TraceBench', kind='benchmark'), object_decision(paper, 'ReAct'),
    ]}, build_bundle(session, paper))
    rows = {row.name: row for row in session.scalars(select(KnowledgeCandidate))}
    target = rows['ReAct']
    before = snapshot(target)
    target.description = 'The researcher retains this canonical identity'
    record(session, target, 'confirm_candidate', before)
    session.flush()
    quote = 'ReAct is only a reproduced prior-study example in this benchmark.'
    paper.chunks[0].content += ' ' + quote
    apply_batch(session, paper, {'object_reviews': [{
        'candidate_id': target.id, 'verdict': verdict, 'confidence': .99,
        'reason': 'The source belongs to a reproduced prior-study example',
        'citations': [{'chunk_id': paper.chunks[0].id, 'quote': quote}],
    }]}, build_bundle(session, paper))
    session.flush()
    assert target.status == 'confirmed'
    assert json.loads(target.conflict_json)['_steward_context']['verdict'] == verdict
    return paper, rows


@pytest.mark.parametrize('verdict', ['incidental', 'incorrect'])
def test_later_batch_cannot_add_confirmed_edge_to_contextual_object(tmp_path, verdict):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper, rows = contextualized_method(session, verdict)
        decision = {'source_name': 'TraceBench', 'target_name': 'ReAct',
            'relation': 'requires_concept', 'description': 'A later model proposes a dependency',
            'confidence': .99, 'citations': [{'chunk_id': paper.chunks[0].id,
                'quote': 'TraceBench evaluates ReAct on HotpotQA.'}]}
        report = apply_batch(session, paper, {'relations': [decision]}, build_bundle(session, paper))
        session.flush()
        edges = list(session.scalars(select(KnowledgeRelation)))
        assert not any(edge.status == 'confirmed' for edge in edges)
        assert report['relations_confirmed'] == 0
        assert rows['ReAct'].status == 'confirmed'
        assert json.loads(rows['ReAct'].conflict_json)['_steward_context']['verdict'] == verdict


@pytest.mark.parametrize('verdict', ['incidental', 'incorrect'])
def test_supported_review_cannot_reconfirm_edge_to_contextual_object(tmp_path, verdict):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper, rows = contextualized_method(session, verdict)
        quote = 'TraceBench evaluates ReAct on HotpotQA.'
        # A subsequent extraction can leave a fresh unresolved edge. Reviewing
        # it must respect the existing source-context decision on its endpoint.
        edge = KnowledgeRelation(id='later-unresolved-edge', paper_id=paper.id,
            source_name='TraceBench', source_normalized_name='tracebench',
            target_name='ReAct', target_normalized_name='react', relation='requires_concept',
            status='unresolved', evidence_json=json.dumps([{
                'chunk_id': paper.chunks[0].id, 'quote': quote}]))
        session.add(edge)
        session.flush()
        report = apply_batch(session, paper, {'reviews': [{
            'relation_id': edge.id, 'verdict': 'supported', 'confidence': .99,
            'reason': 'A later review proposes supporting the dependency',
            'citations': [{'chunk_id': paper.chunks[0].id, 'quote': quote}],
        }]}, build_bundle(session, paper))
        session.flush()
        assert edge.status != 'confirmed'
        assert report['relations_confirmed'] == 0
        assert rows['ReAct'].status == 'confirmed'
        assert json.loads(rows['ReAct'].conflict_json)['_steward_context']['verdict'] == verdict
