import json

from app.db import Database
from app.models import KnowledgeCandidate, KnowledgeEntity, KnowledgeRelation, Paper, PaperChunk
from app.services.knowledge_audit import audit_paper_knowledge


def make_db(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    database.migrate()
    return database


def test_react_audit_distinguishes_covered_ignored_and_missing(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = Paper(id='react', title='ReAct', reading_status='unread', analysis_status='ready', tags_json='[]', metadata_sources_json='{}', metadata_warnings_json='[]')
        paper.chunks.append(PaperChunk(id='c1', paper_id='react', page=1, content='ReAct evaluates HotpotQA. Inner Monologue is discussed.'))
        session.add(paper)
        session.flush()
        entity = KnowledgeEntity(id='ke-react', entity_type='method', name='ReAct', normalized_name='react', aliases_json='[]', status='active')
        session.add(entity)
        session.add(KnowledgeEntity(id='ke-inner', entity_type='method', name='Inner Monologue', normalized_name='inner monologue', aliases_json='[]', status='active'))
        session.add(KnowledgeCandidate(id='kc-react', paper_id='react', entity_id='ke-react', entity_type='method', name='ReAct', normalized_name='react', role='proposed', status='confirmed', evidence_json=json.dumps([{'chunk_id':'c1','page':1,'quote':'ReAct'}])))
        session.commit()
        audit = audit_paper_knowledge(paper)
        assert audit.coverage['method']['ReAct']['state'] == 'confirmed'
        assert not audit.coverage['metric']
        assert any(item['name'] == 'Inner Monologue' for item in audit.suggestions)


def test_audit_is_paper_specific_type_aware_and_respects_ignored_objects(tmp_path):
    database = make_db(tmp_path)
    with database.sessions() as session:
        paper = Paper(id='memory', title='Memory', tags_json='[]')
        paper.chunks = [PaperChunk(id='body', page=1, section='Experiments', content='We use MSC. Zephyr improves memory.'),
            PaperChunk(id='refs', page=3, section='References', content='MemGPT. Inner Monologue.')]
        session.add(paper)
        for name, kind in [('MSC','dataset'),('MSC','benchmark'),('Zephyr','method'),('MemGPT','method')]:
            session.add(KnowledgeEntity(id=kind+name, name=name, normalized_name=name.lower(),entity_type=kind,status='active'))
        session.flush()
        paper.knowledge_candidates = [KnowledgeCandidate(id='msc', entity_type='dataset',name='MSC',normalized_name='msc',role='used',status='known',entity_id='datasetMSC'),
            KnowledgeCandidate(id='z',entity_type='method',name='Zephyr',normalized_name='zephyr',role='cited',status='rejected')]
        session.commit()
        audit = audit_paper_knowledge(paper)
        assert audit.coverage['dataset']['MSC']['state'] == 'confirmed'
        assert audit.coverage['benchmark']['MSC']['state'] == 'missing'
        assert audit.coverage['related_method']['Zephyr']['state'] == 'ignored'
        assert [(s['name'],s['entity_type']) for s in audit.suggestions] == [('MSC','benchmark')]
        assert not any('ReAct' in group or 'MemGPT' in group for group in audit.coverage.values())


def test_entity_dossier_route_and_relation_resolution(client):
    from app.models import PaperChunk
    with client.app.state.database.sessions() as session:
        paper = Paper(id='p', title='ReAct', reading_status='unread', analysis_status='ready', tags_json='[]', metadata_sources_json='{}', metadata_warnings_json='[]')
        chunk = PaperChunk(id='c', paper_id='p', page=1, content='ReAct builds on BUTLER.')
        paper.chunks.append(chunk)
        session.add(paper)
        session.flush()
        entity = KnowledgeEntity(id='ke-react', entity_type='method', name='ReAct', normalized_name='react', aliases_json='[]', status='active')
        session.add(entity)
        source = KnowledgeCandidate(id='kc-react', paper_id='p', entity_id='ke-react', entity_type='method', name='ReAct', normalized_name='react', status='confirmed', evidence_json=json.dumps([{'chunk_id':'c','page':1,'quote':'ReAct'}]))
        session.add(source)
        session.flush()
        relation = KnowledgeRelation(id='kr', paper_id='p', relation='builds_on', source_name='ReAct', source_normalized_name='react', target_name='BUTLER', target_normalized_name='butler', source_candidate_id='kc-react', status='unresolved', evidence_json=json.dumps([{'chunk_id':'c','page':1,'quote':'BUTLER'}]))
        session.add(relation)
        session.commit()
    response = client.get('/api/knowledge/entities/ke-react')
    assert response.status_code == 200
    assert response.json()['papers']
    assert response.json()['evidence']
    assert response.json()['relations']
    assert any(link['kind'] == 'search' for link in response.json()['links'])
    resolved = client.post('/api/knowledge/relations/kr/resolve', json={'target_name': 'BUTLER', 'target_type': 'method'})
    assert resolved.status_code == 200
    assert resolved.json()['status'] == 'confirmed'
    assert resolved.json()['target_candidate_id']
    repeated = client.post('/api/knowledge/relations/kr/resolve', json={'target_name': 'BUTLER', 'target_type': 'method'})
    assert repeated.status_code == 200
    assert repeated.json()['target_candidate_id'] == resolved.json()['target_candidate_id']
