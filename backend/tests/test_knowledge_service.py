import json

from sqlalchemy import select

from app.db import Database
from app.models import KnowledgeEntity, Paper, PaperChunk
from app.providers.base import KnowledgeCandidateEntry, KnowledgeRelationEntry, VerifiedCitation
from app.services.knowledge import confirm_candidate, normalize_name, persist_candidates


def make_db(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'knowledge.db').as_posix()}")
    database.migrate()
    return database


def test_normalize_name_handles_unicode_and_punctuation():
    assert normalize_name('  Hotpot‑QA / v1 ') == 'hotpot qa v1'


def test_reconcile_marks_new_and_alias_and_confirmation_is_idempotent(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = Paper(id='p', title='Paper', reading_status='unread', analysis_status='ready', tags_json='[]', metadata_sources_json='{}', metadata_warnings_json='[]')
        chunk = PaperChunk(id='c', paper_id='p', page=2, section='Experiments', content='We evaluate on Hotpot QA and compare with ReAct.')
        paper.chunks.append(chunk); session.add(paper); session.flush()
        entity = KnowledgeEntity(id='ke', entity_type='dataset', name='HotpotQA', normalized_name='hotpot qa', aliases_json=json.dumps(['Hotpot QA']), status='active')
        session.add(entity); session.flush()
        citation = VerifiedCitation(chunk, 'Hotpot QA', 'uses dataset', 'explicit')
        rows, _ = persist_candidates(session, paper, [KnowledgeCandidateEntry('dataset', 'Hotpot QA', 'hotpot qa', [], 'dataset', 'used', .9, [citation])], [], run_id='run')
        session.commit()
        assert rows[0].status == 'alias'
        confirm_candidate(session, rows[0], name='HotpotQA')
        session.commit()
        assert rows[0].status == 'confirmed'
        assert session.scalar(select(KnowledgeEntity).where(KnowledgeEntity.normalized_name == 'hotpotqa')) is not None


def test_relation_without_evidence_is_dropped(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = Paper(id='p', title='Paper', reading_status='unread', analysis_status='ready', tags_json='[]', metadata_sources_json='{}', metadata_warnings_json='[]')
        chunk = PaperChunk(id='c', paper_id='p', page=1, content='A builds on B.')
        paper.chunks.append(chunk); session.add(paper); session.flush()
        rows, relations = persist_candidates(session, paper, [], [KnowledgeRelationEntry('builds_on', 'A', 'a', 'B', 'b', None, .8, [])], run_id='run')
        assert rows == [] and relations == []
