"""Regression coverage for repeated analyses becoming duplicate knowledge."""
import json
import pytest
from datetime import datetime, timedelta, timezone
from itertools import permutations
from types import SimpleNamespace

from sqlalchemy import select

from app.models import KnowledgeCandidate, KnowledgeChange, KnowledgeEntity, KnowledgeRelation, Paper, PaperChunk
from app.providers.base import KnowledgeCandidateEntry, KnowledgeRelationEntry, VerifiedCitation
from app.services.knowledge import confirm_candidate, persist_candidates, reject_candidate
from test_knowledge_service import make_db


def source(session, paper_id='p'):
    paper = Paper(id=paper_id, title='MemGPT', tags_json='[]')
    paper.chunks = [
        PaperChunk(id=paper_id+'-a', page=1, content='MemGPT uses Multi-Session Chat (MSC) with external memory.'),
        PaperChunk(id=paper_id+'-b', page=2, content='MSC is used to evaluate MemGPT memory retrieval.'),
    ]
    session.add(paper)
    session.flush()
    return paper


def entry(paper, name='MemGPT', kind='method', aliases=None, block=0):
    chunk = paper.chunks[block]
    return KnowledgeCandidateEntry(kind, name, name.lower(), aliases or [], 'Grounded description',
        'proposed' if kind == 'method' else 'used', .9,
        [VerifiedCitation(chunk, chunk.content, name, 'explicit')])


def edge(paper, block=0):
    chunk = paper.chunks[block]
    return KnowledgeRelationEntry('uses_dataset', 'MemGPT', 'memgpt', 'MSC', 'msc',
        'Uses MSC', .9, [VerifiedCitation(chunk, chunk.content, 'Uses MSC', 'explicit')])


def test_reanalysis_reuses_identity_and_accumulates_sources(tmp_path):
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        first, _ = persist_candidates(session, paper, [entry(paper)], [], run_id='first')
        confirm_candidate(session, first[0], description='My curated definition')
        session.commit()
        again, _ = persist_candidates(session, paper, [entry(paper, block=1)], [], run_id='second')
        session.commit()
        assert again[0].id == first[0].id
        assert again[0].status == 'confirmed'
        assert again[0].description == 'My curated definition'
        assert len(json.loads(again[0].evidence_json)) == 2
        assert len(session.scalars(select(KnowledgeCandidate)).all()) == 1


def test_reanalysis_does_not_resurrect_rejected_object(tmp_path):
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        first, _ = persist_candidates(session, paper, [entry(paper)], [], run_id='first')
        reject_candidate(session, first[0])
        session.commit()
        again, _ = persist_candidates(session, paper, [entry(paper, block=1)], [], run_id='second')
        assert again[0].id == first[0].id
        assert again[0].status == 'rejected'


def test_declared_aliases_survive_confirmation_and_resolve_later_relations(tmp_path):
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, relations = persist_candidates(session, paper,
            [entry(paper), entry(paper, 'Multi-Session Chat (MSC)', 'dataset', ['MSC'])],
            [edge(paper)], run_id='first')
        for row in rows:
            confirm_candidate(session, row)
        session.commit()
        dataset = rows[1]
        assert json.loads(dataset.entity.aliases_json) == ['MSC']
        assert relations[0].target_candidate_id == dataset.id
        again, edges = persist_candidates(session, paper,
            [entry(paper, 'MSC', 'dataset', block=1)], [edge(paper, 1)], run_id='second')
        session.commit()
        assert again[0].id == dataset.id
        assert edges[0].id == relations[0].id
        assert edges[0].source_candidate_id == rows[0].id
        assert len(json.loads(edges[0].evidence_json)) == 2
        assert len(session.scalars(select(KnowledgeRelation)).all()) == 1


def test_same_name_different_types_and_different_papers_are_separate(tmp_path):
    db = make_db(tmp_path)
    with db.sessions() as session:
        a, b = source(session), source(session, 'other')
        rows, _ = persist_candidates(session, a, [entry(a, 'MSC', 'dataset'), entry(a, 'MSC', 'benchmark')], [], run_id='a')
        others, _ = persist_candidates(session, b, [entry(b, 'MSC', 'dataset')], [], run_id='b')
        assert len({r.id for r in [*rows, *others]}) == 3


def test_legacy_duplicate_repair_preserves_decisions_quotes_and_relation_endpoints(tmp_path):
    from app.services.knowledge_identity import reconcile_paper

    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, relations = persist_candidates(session, paper,
            [entry(paper), entry(paper, 'MSC', 'dataset')], [edge(paper)], run_id='first')
        confirm_candidate(session, rows[0])
        reject_candidate(session, rows[1])
        session.commit()
        duplicate = KnowledgeCandidate(id='legacy-duplicate', paper_id=paper.id, entity_type='method',
            name='MemGPT', normalized_name='memgpt', status='new', role='cited', confidence=.9,
            aliases_json='[]', evidence_json=json.dumps([{'chunk_id':paper.chunks[1].id, 'quote':paper.chunks[1].content}]), run_id='old-second')
        session.add(duplicate)
        session.flush()
        session.add(KnowledgeRelation(id='legacy-edge', paper_id=paper.id, relation='uses_dataset',
            source_name='MemGPT', source_normalized_name='memgpt', target_name='MSC', target_normalized_name='msc',
            source_candidate_id=duplicate.id, target_candidate_id=rows[1].id,
            evidence_json=relations[0].evidence_json, status='candidate', run_id='old-second'))
        session.commit()
        counts = reconcile_paper(session, paper)
        session.commit()
        assert counts == {'candidates':1, 'relations':1}
        assert len(session.scalars(select(KnowledgeCandidate)).all()) == 2
        assert rows[0].status == 'confirmed' and rows[1].status == 'rejected'
        assert len(json.loads(rows[0].evidence_json)) == 2
        relation = session.scalars(select(KnowledgeRelation)).one()
        assert relation.source_candidate_id == rows[0].id
        assert relation.target_candidate_id == rows[1].id
        archives = session.scalars(select(KnowledgeChange).where(KnowledgeChange.action == 'duplicate_archived')).all()
        assert {r.subject_id for r in archives} == {'legacy-duplicate', 'legacy-edge'}
        assert json.loads(next(r.before_json for r in archives if r.subject_id == duplicate.id))['run_id'] == 'old-second'
        assert reconcile_paper(session, paper) == {'candidates':0, 'relations':0}


def test_ambiguous_acronym_does_not_merge_distinct_objects(tmp_path):
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, _ = persist_candidates(session, paper, [entry(paper, 'Memory controller', aliases=['MC']),
            entry(paper, 'Monte Carlo', aliases=['MC'])], [], run_id='first')
        assert len(rows) == 2 and rows[0].id != rows[1].id


def test_new_alias_in_same_run_keeps_all_evidence(tmp_path):
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, _ = persist_candidates(session, paper, [entry(paper, 'MSC', 'dataset', block=0),
            entry(paper, 'Multi-Session Chat', 'dataset', ['MSC'], block=1)], [], run_id='first')
        session.flush()
        assert len(rows) == 1
        assert len(json.loads(rows[0].evidence_json)) == 2


def test_confirming_candidate_checks_alias_namespace(tmp_path):
    import pytest
    from fastapi import HTTPException
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        session.add(KnowledgeEntity(id='existing', entity_type='method', name='Another method',
            normalized_name='another method', aliases_json='["MC"]', status='active'))
        session.flush()
        rows, _ = persist_candidates(session, paper, [entry(paper, 'Memory controller', aliases=['MC'])], [], run_id='first')
        # A shared acronym must not silently rename/merge established objects.
        with pytest.raises(HTTPException) as error:
            confirm_candidate(session, rows[0])
        assert error.value.status_code == 409


def test_library_repair_recovers_previously_lost_aliases_and_is_a_noop_twice(tmp_path):
    from app.services.knowledge_identity import reconcile_library
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, _ = persist_candidates(session, paper,[entry(paper, 'Multi-Session Chat', 'dataset', ['MSC'])],[],run_id='first')
        confirm_candidate(session, rows[0])
        rows[0].entity.aliases_json = '[]'  # Old confirmation code lost these.
        session.commit()
        reconcile_library(session)
        session.commit()
        assert json.loads(rows[0].entity.aliases_json) == ['MSC']
        changes = len(session.scalars(select(KnowledgeChange)).all())
        reconcile_library(session)
        session.commit()
        assert len(session.scalars(select(KnowledgeChange)).all()) == changes


def test_repair_never_accepts_a_relationship_with_rejected_endpoint(tmp_path):
    from app.services.knowledge_identity import reconcile_paper
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, edges = persist_candidates(session,paper,[entry(paper),entry(paper,'MSC','dataset')],[edge(paper)],run_id='first')
        for row in rows:confirm_candidate(session,row)
        edges[0].status='confirmed'
        reject_candidate(session,rows[1])
        session.commit()
        reconcile_paper(session,paper)
        session.commit()
        assert edges[0].status == 'unresolved'
        assert paper.knowledge_status == 'needs_review'


def test_archived_ids_redirect_to_the_retained_object(tmp_path):
    from app.services.knowledge_identity import archived_row, reconcile_paper
    db=make_db(tmp_path)
    with db.sessions() as session:
        paper=source(session)
        rows,_=persist_candidates(session,paper,[entry(paper)],[],run_id='first')
        duplicate=KnowledgeCandidate(id='old-id',paper_id=paper.id,entity_type='method',name='MemGPT',normalized_name='memgpt',
            status='new',role='proposed',confidence=.9,evidence_json=rows[0].evidence_json)
        session.add(duplicate);session.commit()
        reconcile_paper(session,paper);session.commit()
        assert archived_row(session,KnowledgeCandidate,'old-id').id == rows[0].id


def test_ambiguous_short_name_is_order_independent(tmp_path):
    db = make_db(tmp_path)
    for index, names in enumerate(permutations(['MC', 'Memory controller', 'Monte Carlo'])):
        with db.sessions() as session:
            paper = source(session, str(index))
            rows, _ = persist_candidates(session, paper,
                [entry(paper, name, aliases=[] if name == 'MC' else ['MC']) for name in names], [], run_id='batch')
            assert len(rows) == 3, names
            session.commit()


def test_retry_preserves_manually_edited_relation_identity_and_description(tmp_path):
    from app.services.knowledge_curation import edit_relation
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, edges = persist_candidates(session, paper,
            [entry(paper), entry(paper, 'MSC', 'dataset')], [edge(paper)], run_id='first')
        original_id = edges[0].id
        edit_relation(session, edges[0], SimpleNamespace(source_candidate_id=rows[0].id,
            target_candidate_id=rows[1].id, relation='evaluated_on', description='My correction'))
        session.commit()
        incoming = edge(paper, 1)
        incoming.description = 'A longer model-generated description that must not overwrite my correction'
        _, repeated = persist_candidates(session, paper, [], [incoming], run_id='again')
        session.commit()
        assert repeated[0].id == original_id
        assert repeated[0].relation == 'evaluated_on'
        assert repeated[0].description == 'My correction'
        assert len(json.loads(repeated[0].evidence_json)) == 2
        # Same edited predicate must preserve the manual definition too.
        incoming.relation = 'evaluated_on'
        _, repeated = persist_candidates(session, paper, [], [incoming], run_id='third')
        assert repeated[0].description == 'My correction'
        assert len(session.scalars(select(KnowledgeRelation)).all()) == 1


def test_latest_human_decision_wins_and_archive_retains_timestamps(tmp_path):
    from app.services.knowledge_identity import reconcile_paper
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, _ = persist_candidates(session, paper, [entry(paper)], [], run_id='first')
        confirm_candidate(session, rows[0])
        duplicate = KnowledgeCandidate(id='later-rejection', paper_id=paper.id, entity_type='method',
            name='MemGPT', normalized_name='memgpt', status='new', evidence_json=rows[0].evidence_json)
        session.add(duplicate); session.flush()
        reject_candidate(session, duplicate)
        session.flush()
        for change in session.scalars(select(KnowledgeChange)).all():
            change.created_at = datetime.now(timezone.utc) + timedelta(days=1 if change.subject_id == duplicate.id else -1)
        session.commit()
        reconcile_paper(session, paper); session.commit()
        keeper = session.scalars(select(KnowledgeCandidate)).one()
        assert keeper.status == 'rejected'
        archive = session.scalars(select(KnowledgeChange).where(KnowledgeChange.action == 'duplicate_archived')).one()
        assert json.loads(archive.before_json)['created_at']
        assert json.loads(archive.before_json)['updated_at']


def test_library_repair_respects_intentionally_removed_aliases(tmp_path):
    from app.services.knowledge_curation import edit_entity
    from app.services.knowledge_identity import reconcile_library
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, _ = persist_candidates(session, paper, [entry(paper, 'Multi-Session Chat', 'dataset', ['MSC'])], [], run_id='first')
        confirm_candidate(session, rows[0])
        entity = rows[0].entity
        edit_entity(session, entity, SimpleNamespace(name=entity.name, entity_type='dataset', aliases=[], description='My definition', links=[]))
        session.commit()
        reconcile_library(session); session.commit()
        assert json.loads(entity.aliases_json) == []
        reject_candidate(session, rows[0])
        confirm_candidate(session, rows[0])
        session.commit()
        assert json.loads(entity.aliases_json) == []


def test_archived_legacy_correction_is_respected_on_replay(tmp_path):
    from app.services.knowledge_curation import edit_relation, review_relation
    from app.services.knowledge_identity import reconcile_paper
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, edges = persist_candidates(session,paper,[entry(paper),entry(paper,'MSC','dataset')],[edge(paper)],run_id='first')
        original = edges[0]
        original.id = 'legacy-random-id'
        session.flush()
        edit_relation(session, original, SimpleNamespace(source_candidate_id=rows[0].id,target_candidate_id=rows[1].id,
            relation='evaluated_on',description='My correction'))
        session.flush()
        newer = KnowledgeRelation(id='newer-id',paper_id=paper.id,relation='evaluated_on',source_name='MemGPT',source_normalized_name='memgpt',
            target_name='MSC',target_normalized_name='msc',source_candidate_id=rows[0].id,target_candidate_id=rows[1].id,
            status='candidate',evidence_json=original.evidence_json)
        session.add(newer);session.flush()
        review_relation(session,newer,'reject');session.commit()
        reconcile_paper(session,paper);session.commit()
        _, replayed = persist_candidates(session,paper,[],[edge(paper,1)],run_id='again')
        session.commit()
        assert replayed[0].id == 'newer-id'
        assert replayed[0].status == 'rejected'
        assert len(session.scalars(select(KnowledgeRelation)).all()) == 1


def test_legacy_known_object_keeps_its_canonical_identity(tmp_path):
    from app.services.knowledge_identity import reconcile_paper
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, _ = persist_candidates(session,paper,[entry(paper)],[],run_id='first')
        session.add(KnowledgeEntity(id='canonical',entity_type='method',name='MemGPT',normalized_name='memgpt',status='active'))
        session.flush()
        session.add(KnowledgeCandidate(id='later-known',paper_id=paper.id,entity_id='canonical',entity_type='method',name='MemGPT',
            normalized_name='memgpt',status='known',evidence_json=rows[0].evidence_json))
        session.commit()
        reconcile_paper(session,paper);session.commit()
        keeper=session.scalars(select(KnowledgeCandidate)).one()
        assert keeper.entity_id == 'canonical'
        assert keeper.status == 'known'


def test_reanalysis_after_manual_reclassification_reuses_canonical_identity(tmp_path):
    from app.services.knowledge_curation import edit_entity
    from app.services.knowledge_audit import audit_paper_knowledge
    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        rows, _ = persist_candidates(session,paper,[entry(paper,'MSC','method')],[],run_id='first')
        confirm_candidate(session,rows[0])
        entity=rows[0].entity
        edit_entity(session,entity,SimpleNamespace(name='MSC',entity_type='dataset',aliases=[],description='Corrected type',links=[]))
        session.commit()
        repeated,_=persist_candidates(session,paper,[entry(paper,'MSC','dataset',block=1)],[],run_id='again')
        session.commit()
        assert repeated[0].id == rows[0].id
        assert len(session.scalars(select(KnowledgeCandidate)).all()) == 1
        audit=audit_paper_knowledge(paper)
        assert 'MSC' in audit.coverage['dataset']
        assert 'MSC' not in audit.coverage['method']
        assert audit.suggestions == []


@pytest.mark.parametrize('source_name,source_type,predicate,target_name,target_type', [
    ('DeepSWE', 'benchmark', 'contrasts_with', 'SWE-Bench Pro', 'benchmark'),
    ('NL2Repo-Bench', 'benchmark', 'uses_dataset', '104 repository tasks', 'dataset'),
    ('SWE-bench', 'benchmark', 'requires_concept', 'execution-based code testing', 'concept'),
    ('New benchmark', 'benchmark', 'builds_on', 'Prior dataset', 'dataset'),
    ('Reflexion', 'method', 'requires_concept', 'exact match (EM)', 'metric'),
    ('MultiPL-E', 'method', 'uses_dataset', 'HumanEval', 'benchmark'),
])
def test_research_object_types_attach_and_reconcile_without_retyping(
    tmp_path, source_name, source_type, predicate, target_name, target_type,
):
    from app.services.knowledge_curation import confirmable, review_relation
    from app.services.knowledge_identity import reconcile_paper

    db = make_db(tmp_path)
    with db.sessions() as session:
        paper = source(session)
        paper.chunks[0].content = f'{source_name} {predicate} {target_name}.'
        citation = VerifiedCitation(paper.chunks[0], paper.chunks[0].content, 'Explicit relation', 'explicit')
        relation = KnowledgeRelationEntry(predicate, source_name, source_name.lower(), target_name, target_name.lower(),
            'Explicit relation', .99, [citation])
        rows, edges = persist_candidates(session, paper, [
            entry(paper, source_name, source_type), entry(paper, target_name, target_type),
        ], [relation], run_id='first')
        edge_row = edges[0]
        assert edge_row.source_candidate_id == rows[0].id
        assert edge_row.target_candidate_id == rows[1].id
        assert edge_row.status == 'candidate'
        for row in rows:
            confirm_candidate(session, row)
        assert confirmable(session, edge_row)
        # Legacy dangling edges can be deterministically reconnected, while
        # explicit researcher rejections must survive the same repair.
        edge_row.source_candidate_id = None
        edge_row.target_candidate_id = None
        edge_row.status = 'unresolved'
        session.flush()
        reconcile_paper(session, paper)
        assert (edge_row.source_candidate_id, edge_row.target_candidate_id) == (rows[0].id, rows[1].id)
        assert edge_row.status == 'candidate'
        review_relation(session, edge_row, 'reject')
        _, repeated = persist_candidates(session, paper, [], [relation], run_id='again')
        assert repeated[0].id == edge_row.id
        assert repeated[0].status == 'rejected'
        assert [row.entity.entity_type for row in rows] == [source_type, target_type]
