import fitz

from app.models import KnowledgeCandidate


def import_paper(client):
    with fitz.open() as doc:
        page = doc.new_page(); page.insert_text((40, 60), 'We evaluate the ReAct method on HotpotQA.')
        data = doc.tobytes()
    response = client.post('/api/papers/import', files={'file': ('react.pdf', data)}, data={'analyze': 'false'})
    assert response.status_code == 201
    return response.json()


def test_get_paper_knowledge_and_confirm_candidate(client):
    paper = import_paper(client)
    with client.app.state.database.sessions() as session:
        # use the imported paper's first chunk to create a review fixture
        from app.models import PaperChunk
        chunk = session.query(PaperChunk).filter(PaperChunk.paper_id == paper['id']).first()
        row = KnowledgeCandidate(id='kc-api', paper_id=paper['id'], entity_type='dataset', name='HotpotQA', normalized_name='hotpotqa', role='used', confidence=.9, evidence_json='[{"chunk_id":"%s","page":1,"quote":"HotpotQA"}]' % chunk.id, status='new')
        session.add(row); session.commit()
    package = client.get(f"/api/papers/{paper['id']}/knowledge")
    assert package.status_code == 200 and package.json()['candidates'][0]['name'] == 'HotpotQA'
    assert package.json()['candidates'][0]['layer'] == 'evaluation'
    assert package.json()['candidates'][0]['importance'] == 'core'
    confirmed = client.post('/api/knowledge/candidates/kc-api/confirm', json={})
    assert confirmed.status_code == 200 and confirmed.json()['status'] == 'confirmed'
    assert client.get('/api/knowledge/entities?entity_type=dataset').json()['items'][0]['name'] == 'HotpotQA'


def test_directory_exposes_paper_local_context_without_erasing_global_identity(client):
    import json
    from app.models import KnowledgeEntity,Paper,PaperChunk
    paper=import_paper(client)
    with client.app.state.database.sessions() as session:
        entity=KnowledgeEntity(id='context-entity',entity_type='method',name='ReAct',normalized_name='react',description='An old attribution',status='active')
        session.add(entity);session.flush()
        session.add(KnowledgeCandidate(id='context-candidate',paper_id=paper['id'],entity_id=entity.id,entity_type='method',name='ReAct',normalized_name='react',role='used',status='confirmed',
            evidence_json=json.dumps([{'chunk_id':paper['chunks'][0]['id'],'quote':'ReAct'}]),
            conflict_json=json.dumps({'_steward_context':{'verdict':'incidental','reason':'Reproduced example from a prior study.'}})))
        session.commit()
    item=next(x for x in client.get('/api/knowledge/entities').json()['items'] if x['id']=='context-entity')
    assert item['context_only'] is True and item['contextual_paper_count']==1
    assert item['context_summary']=='Reproduced example from a prior study.'
    assert item['description']=='An old attribution'
    with client.app.state.database.sessions() as session:
        session.add(Paper(id='own-study',title='Another study'));session.flush()
        session.add(PaperChunk(id='own-chunk',paper_id='own-study',content='We introduce ReAct.'));session.flush()
        session.add(KnowledgeCandidate(id='own-candidate',paper_id='own-study',entity_id='context-entity',entity_type='method',name='ReAct',normalized_name='react',role='proposed',status='confirmed',evidence_json='[{"chunk_id":"own-chunk","quote":"ReAct"}]'))
        session.commit()
    all_item=next(x for x in client.get('/api/knowledge/entities').json()['items'] if x['id']=='context-entity')
    assert all_item['context_only'] is False and all_item['contextual_paper_count']==1
    scoped=client.get('/api/knowledge/entities',params={'paper_ids':paper['id']}).json()['items'][0]
    assert scoped['context_only'] is True


def test_paragraph_endpoint_is_additive_when_provider_unavailable(client):
    paper = import_paper(client)
    chunk_id = paper['chunks'][0]['id']
    response = client.post(f"/api/papers/{paper['id']}/knowledge/paragraph", json={'paragraph_id': chunk_id})
    assert response.status_code == 409
    assert '模型' in response.json()['detail']
    assert client.get(f"/api/papers/{paper['id']}/knowledge").json()['candidates'] == []


def test_paragraph_extraction_uses_all_source_blocks_and_is_idempotent(client, monkeypatch):
    import json
    from app.models import PaperChunk
    from app.providers.base import AnalysisResult, KnowledgeCandidateEntry, VerifiedCitation
    paper = import_paper(client)
    first = paper['chunks'][0]['id']
    with client.app.state.database.sessions() as session:
        session.add(PaperChunk(id='continued', paper_id=paper['id'], page=2, content='HotpotQA provides the evaluation examples.'))
        session.commit()
    monkeypatch.setattr('app.api.knowledge.paragraphs_for', lambda _: [{'id':'whole-paragraph',
        'refs':[{'chunk_id':first},{'chunk_id':'continued'}],
        'anchors':[{'chunk_id':first},{'chunk_id':'continued'}]}])
    seen = []
    class Provider:
        mode = 'remote'
        configured = True
        def analyze(self, chunks):
            seen.append([c.id for c in chunks])
            last = next(c for c in chunks if c.id == 'continued')
            return AnalysisResult(knowledge_candidates=[KnowledgeCandidateEntry('dataset', 'HotpotQA', 'hotpotqa', [],
                'Evaluation data', 'used', .9, [VerifiedCitation(last, last.content, 'Data', 'explicit')])])
    monkeypatch.setattr('app.api.knowledge.get_model_provider', lambda:Provider())
    for _ in range(2):
        response = client.post(f"/api/papers/{paper['id']}/knowledge/paragraph", json={'paragraph_id':'whole-paragraph'})
        assert response.status_code == 202, response.text
        assert len(response.json()['candidates']) == 1
    assert seen == [[first,'continued'],[first,'continued']]


def test_paragraph_provider_error_is_visible_and_keeps_previous_knowledge(client, monkeypatch):
    from app.providers.base import ProviderError
    paper = import_paper(client)
    class Broken:
        mode = 'remote'
        configured = True
        def analyze(self, chunks):
            raise ProviderError('模型连接暂时不可用，请重试', 502)
    monkeypatch.setattr('app.api.knowledge.get_model_provider', lambda:Broken())
    response = client.post(f"/api/papers/{paper['id']}/knowledge/paragraph", json={'paragraph_id':paper['chunks'][0]['id']})
    assert response.status_code == 502
    assert '重试' in response.json()['detail']


def test_knowledge_overview_is_lightweight_and_scoped(client):
    paper = import_paper(client)
    with client.app.state.database.sessions() as session:
        from app.models import PaperChunk
        chunk = session.query(PaperChunk).filter(PaperChunk.paper_id == paper['id']).first()
        session.add(KnowledgeCandidate(
            id='kc-overview', paper_id=paper['id'], entity_type='method', name='ReAct',
            normalized_name='react', role='proposed', confidence=.95,
            evidence_json='[{"chunk_id":"%s","page":1,"quote":"ReAct"}]' % chunk.id,
            status='confirmed',
        ))
        session.commit()
    response = client.get(f"/api/knowledge/overview?paper_ids={paper['id']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload['candidates'][0]['name'] == 'ReAct'
    assert payload['relations'] == []


def test_batch_review_is_paper_scoped_and_atomic(client):
    import json
    paper = import_paper(client)
    with client.app.state.database.sessions() as session:
        for cid, pid, quote in [('batch-a',paper['id'],'ReAct'),('batch-b',paper['id'],'HotpotQA')]:
            session.add(KnowledgeCandidate(id=cid,paper_id=pid,entity_type='method',name=quote,normalized_name=quote.lower(),
                status='new',role='cited',confidence=.9,evidence_json=json.dumps([{'chunk_id':paper['chunks'][0]['id'],'quote':quote}])))
        session.commit()
    url = f"/api/papers/{paper['id']}/knowledge/review"
    invalid = client.post(url, json={'candidate_ids':['batch-a','missing'],'decision':'confirm'})
    assert invalid.status_code == 404
    assert all(c['status']=='new' for c in client.get(f"/api/papers/{paper['id']}/knowledge").json()['candidates'])
    response = client.post(url, json={'candidate_ids':['batch-a','batch-b'],'decision':'confirm'})
    assert response.status_code == 200, response.text
    assert all(c['status']=='confirmed' for c in response.json()['candidates'])
    assert response.json()['paper_status'] == 'settled'


def test_confirmation_requires_a_quote_in_this_paper(client):
    paper = import_paper(client)
    with client.app.state.database.sessions() as session:
        session.add(KnowledgeCandidate(id='bad-evidence',paper_id=paper['id'],entity_type='method',name='Made-up',
            normalized_name='made up',status='new',role='cited',confidence=.9,evidence_json='[{"chunk_id":"missing","quote":"made up"}]'))
        session.commit()
    response = client.post('/api/knowledge/candidates/bad-evidence/confirm',json={})
    assert response.status_code == 422
