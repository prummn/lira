from __future__ import annotations
import json
import fitz
import pytest
from fastapi.testclient import TestClient


def card_paper(client: TestClient) -> dict:
    sections = [
        ('Abstract', 'We study corpus retrieval with an auditable evaluation protocol.'),
        ('1 Motivation', 'Readers need to trace research claims to original passages.'),
        ('2 Background', 'A verifier checks a candidate retrieval passage against a query.'),
        ('3 Core Idea', 'Retain provenance metadata throughout the retrieval pipeline.'),
        ('4 Method', 'Rank corpus chunks by keyword overlap before verifying support.'),
        ('5 Contributions', 'We release a reproducible retrieval pipeline and evaluation script.'),
        ('6 Datasets', 'The only dataset is LocalCorpus, containing 100 curated passages.'),
        ('7 Metrics', 'We report passage recall at five candidates.'),
        ('8 Baselines', 'The comparison baseline is exact keyword matching.'),
        ('9 Results', 'The pipeline retrieves 71 of 100 relevant passages.'),
        ('10 Ablation', 'Removing the verifier reduces recall to 62 of 100 passages.'),
        ('11 Limitations', 'The dataset contains only English research passages.'),
        ('12 Future Work', 'We plan to evaluate retrieval on additional languages.'),
        ('13 Claims', 'Every reported retrieval decision is accompanied by a source passage.'),
        ('14 Related Methods', 'Related retrieval systems also retain document identifiers.'),
        ('15 Prerequisite Concepts', 'The reader should understand recall and passage ranking.'),
    ]
    with fitz.open() as document:
        for start in (0,8):
            page = document.new_page()
            y = 50
            for heading,content in sections[start:start+8]:
                page.insert_text((50,y),heading,fontsize=12)
                assert page.insert_textbox(fitz.Rect(50,y+8,540,y+55),content,fontsize=10) >= 0
                y += 85
        data = document.tobytes()
    response = client.post('/api/papers/import',files={'file':('card.pdf',data)})
    assert response.status_code == 201
    return response.json()


def test_mock_full_card_every_item_has_real_evidence_and_missing_language_stays_empty(client: TestClient) -> None:
    paper = card_paper(client)
    card = paper['analysis']['card']
    assert isinstance(card['title'],str)
    for field in ('one_sentence_summary','problem','motivation','background','core_idea','method','main_results','limitations','abstract_en','abstract_zh','contributions','datasets','metrics','baselines','ablation_findings','future_work','claims','related_methods','prerequisite_concepts','section_summaries','tldr'):
        assert field in card
    for field in ('motivation','background','core_idea','method','main_results','limitations','abstract_en'):
        assert card[field]
    for field in ('contributions','datasets','metrics','baselines','ablation_findings','future_work','claims','related_methods','prerequisite_concepts','section_summaries'):
        assert card[field]
    assert card['abstract_zh'] is None
    assert 3 <= len(card['tldr']) <= 5
    evidence = {e['id']:e for e in paper['evidence']}
    for field,value in card.items():
        if field == 'title' or value is None:
            continue
        items = value if isinstance(value,list) else [value]
        for item in items:
            assert item['evidence_ids']
            assert all(i in evidence for i in item['evidence_ids'])
            assert item['content'] in '\n\n'.join(evidence[i]['source_text'] for i in item['evidence_ids'])
            assert all(evidence[i]['source_type'] == 'explicit' for i in item['evidence_ids'])
    persisted = client.get(f"/api/papers/{paper['id']}").json()
    assert persisted['analysis']['card'] == card
    assert paper['analysis']['one_liner'] == card['one_sentence_summary']['content']
    assert paper['analysis']['findings'] == card['main_results']['content']


def test_mock_does_not_guess_datasets_or_chinese_abstract_from_results(demo_client: TestClient) -> None:
    paper = demo_client.get('/api/papers/paper-001').json()
    card = paper['analysis']['card']
    assert card['datasets'] == []
    assert card['abstract_zh'] is None
    assert card['prerequisite_concepts'] == []


@pytest.mark.parametrize('style',['technical','simple','mathematical','prerequisites'])
def test_selection_explanation_is_honest_local_excerpt(client: TestClient,style: str) -> None:
    paper = card_paper(client)
    chunk = next(c for c in paper['chunks'] if 'LocalCorpus' in c['content'])
    response = client.post(f"/api/papers/{paper['id']}/explain",json={'chunk_id':chunk['id'],'selected_text':'LocalCorpus','style':style})
    assert response.status_code == 200
    data = response.json()
    assert data['provider'] == 'MockProvider'
    assert data['mode'] == 'extractive'
    assert '摘录' in data['answer']
    assert 'LocalCorpus' in data['answer']
    assert data['citations'][0]['source_text'] == 'LocalCorpus'
    assert data['citations'][0]['chunk_id'] == chunk['id']
    assert data['citations'][0]['bbox'] == chunk['bbox']


def test_selection_explanation_rejects_invented_or_wrong_paper_text(client: TestClient) -> None:
    paper = card_paper(client)
    url = f"/api/papers/{paper['id']}/explain"
    chunk = paper['chunks'][0]
    for body in [{'chunk_id':chunk['id'],'selected_text':'invented nonexistent text','style':'technical'}, {'chunk_id':chunk['id'],'selected_text':' ','style':'simple'}, {'chunk_id':chunk['id'],'selected_text':'Abstract','style':'unknown'}]:
        response = client.post(url,json=body)
        assert response.status_code == 422
        assert isinstance(response.json()['detail'],str)
    assert client.post(url,json={'chunk_id':'other-paper-chunk','selected_text':'Abstract','style':'simple'}).status_code == 404


def test_remote_card_validates_each_field_and_ignores_model_title(client: TestClient,monkeypatch: pytest.MonkeyPatch) -> None:
    from test_remote_provider import provider_for
    paper = card_paper(client)
    chunk = next(c for c in paper['chunks'] if 'LocalCorpus' in c['content'])
    provider = provider_for({'card':{'title':'Invented title', 'datasets':[{'content':'LocalCorpus 是一个包含 100 个段落的数据集。','citations':[{'chunk_id':chunk['id'],'source_text':'LocalCorpus, containing 100 curated passages.'}]}], 'metrics':[{'content':'A made-up metric','citations':[{'chunk_id':chunk['id'],'source_text':'FictionalMetric'}]}]}})
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    response = client.post(f"/api/papers/{paper['id']}/analyze")
    assert response.status_code == 200
    result = response.json()
    assert result['analysis']['card']['title'] == paper['title']
    assert result['analysis']['card']['datasets'][0]['content'].startswith('LocalCorpus')
    assert result['analysis']['card']['metrics'] == []
    assert result['evidence'][0]['source_type'] == 'llm_summary'


def test_remote_explain_uses_only_selected_chunk_and_style(client: TestClient,monkeypatch: pytest.MonkeyPatch) -> None:
    from test_remote_provider import provider_for
    paper = card_paper(client)
    chunk = next(c for c in paper['chunks'] if 'LocalCorpus' in c['content'])
    provider = provider_for({'answer':'LocalCorpus 是该评估使用的数据集。','citations':[{'chunk_id':chunk['id'],'source_text':'LocalCorpus'}],'insufficient_evidence':False})
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    response = client.post(f"/api/papers/{paper['id']}/explain",json={'chunk_id':chunk['id'],'selected_text':'LocalCorpus','style':'simple'})
    assert response.status_code == 200
    assert response.json()['mode'] == 'remote'
    assert response.json()['citations'][0]['source_type'] == 'llm_summary'
