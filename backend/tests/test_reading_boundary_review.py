"""Model review can decide boundaries, never rewrite immutable paper sources."""
import json

import pytest
from sqlalchemy import select

from app.models import ModelCallCache, Paper, PaperChunk
from app.providers.base import ProviderError


class BoundaryProvider:
    name = 'BoundaryFixture'
    model = 'boundary-fixture'
    response_model = None
    mode = 'remote'
    configured = True
    translation_available = False
    last_usage = {}

    def __init__(self, *, join=True, confidence=.99, invalid=None):
        self.calls = []
        self.join, self.confidence, self.invalid = join, confidence, invalid

    def complete_json(self, system, payload, **kwargs):
        self.calls.append(payload)
        if self.invalid == 'failure':
            raise ProviderError('模型连接超时，请重试',504)
        return {'decisions':[{'boundary_id':item['boundary_id'] if self.invalid != 'id' else 'invented',
            'same_paragraph':self.join if self.invalid != 'boolean' else 'true',
            'confidence':self.confidence,'reason':'The sentence resumes after a figure.'}
            for item in payload['boundaries']]}


class FailAfterFirstBoundaryProvider(BoundaryProvider):
    def complete_json(self, system, payload, **kwargs):
        if self.calls:
            self.calls.append(payload)
            raise ProviderError('模型连接在继续检查时超时，请重试', 504)
        return super().complete_json(system, payload, **kwargs)


def seed_fragments(client):
    with client.app.state.database.sessions() as session:
        paper = Paper(id='boundary-paper',title='Boundary review fixture')
        paper.chunks = [PaperChunk(id='boundary-left',paper_id=paper.id,page=1,section='Introduction',
            content='The architecture is evaluated on the following',bbox_json=json.dumps([54,100,295,135]),page_width=612,page_height=792),
            PaperChunk(id='boundary-caption',paper_id=paper.id,page=1,section='Introduction',
            content='Figure 1: A comparison of benchmark results.',bbox_json=json.dumps([54,200,295,220]),page_width=612,page_height=792),
            PaperChunk(id='boundary-right',paper_id=paper.id,page=1,section='Introduction',
            content='HotpotQA and other benchmarks for factual reasoning.',bbox_json=json.dumps([54,270,295,305]),page_width=612,page_height=792)]
        session.add(paper)
        session.commit()
    return '/api/papers/boundary-paper/reading-paragraphs'


def test_boundary_review_merges_preserves_sources_and_survives_offline_reload(client,monkeypatch):
    path = seed_fragments(client)
    provider = BoundaryProvider()
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    before = client.get(path).json()
    left = before['paragraphs'][0]
    assert left['review_needed'] is True
    result = client.post(path+'/review',json={'paragraph_id':left['id']})
    assert result.status_code == 200, result.text
    data = result.json()
    joined = next(p for p in data['paragraphs'] if p['id'] == data['selected_paragraph_id'])
    assert 'following HotpotQA' in joined['text']
    assert len(joined['anchors']) == 2
    assert 'Figure 1' not in joined['source_text']
    assert data['review']['merged'] == 1
    assert len(provider.calls) == 1
    again = client.post(path+'/review',json={'paragraph_id':joined['id']})
    assert again.status_code == 200 and len(provider.calls) == 1
    from app.providers.mock import MockProvider
    monkeypatch.setattr('app.api.papers.get_model_provider',MockProvider)
    restored = client.get(path).json()
    assert restored['paragraphs'][0]['id'] == joined['id']
    assert restored['paragraphs'][0]['review_needed'] is False
    with client.app.state.database.sessions() as session:
        assert session.get(PaperChunk,'boundary-left').content == 'The architecture is evaluated on the following'
        assert session.get(PaperChunk,'boundary-right').content.startswith('HotpotQA')


def test_cached_boundary_review_is_readable_when_provider_is_temporarily_offline(client,monkeypatch):
    path = seed_fragments(client)
    provider = BoundaryProvider()
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: provider)
    first = client.get(path).json()['paragraphs'][0]
    reviewed = client.post(path + '/review', json={'paragraph_id': first['id']}).json()
    selected_id = reviewed['selected_paragraph_id']

    class OfflineProvider:
        configured = False
        translation_available = False
        name = 'Offline'

    monkeypatch.setattr('app.api.papers.get_model_provider', OfflineProvider)
    cached = client.post(path + '/review', json={'paragraph_id': selected_id})

    assert cached.status_code == 200, cached.text
    assert cached.json()['review']['checked'] == 0
    assert cached.json()['review']['cached'] is True


@pytest.mark.parametrize(('join','confidence'),[(False,.99),(True,.65)])
def test_separate_or_uncertain_decision_is_cached_without_merging(client,monkeypatch,join,confidence):
    path = seed_fragments(client)
    provider = BoundaryProvider(join=join,confidence=confidence)
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    paragraph = client.get(path).json()['paragraphs'][0]
    for _ in range(2):
        response = client.post(path+'/review',json={'paragraph_id':paragraph['id']})
        assert response.status_code == 200, response.text
        assert len(response.json()['paragraphs']) == 3
    assert len(provider.calls) == 1


@pytest.mark.parametrize('invalid',['id','boolean','failure'])
def test_invalid_or_failed_model_review_cannot_modify_reading_units(client,monkeypatch,invalid):
    path = seed_fragments(client)
    provider = BoundaryProvider(invalid=invalid)
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    before = client.get(path).json()['paragraphs']
    response = client.post(path+'/review',json={'paragraph_id':before[0]['id']})
    assert response.status_code in {502,504}
    assert client.get(path).json()['paragraphs'] == before
    with client.app.state.database.sessions() as session:
        assert not session.scalars(select(ModelCallCache).where(ModelCallCache.operation == 'reading_boundary_decision_v1')).all()


def test_old_review_is_not_applied_after_source_changes(client,monkeypatch):
    path = seed_fragments(client)
    provider = BoundaryProvider()
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    before = client.get(path).json()['paragraphs'][0]
    assert client.post(path+'/review',json={'paragraph_id':before['id']}).status_code == 200
    with client.app.state.database.sessions() as session:
        session.get(PaperChunk,'boundary-left').content = 'This revised source has a different unfinished thought'
        session.commit()
    updated = client.get(path).json()
    assert len(updated['paragraphs']) == 3
    assert updated['paragraphs'][0]['review_needed'] is True


def test_explicit_section_boundary_is_never_sent_for_model_merging(client,monkeypatch):
    path = seed_fragments(client)
    with client.app.state.database.sessions() as session:
        session.get(PaperChunk,'boundary-right').section = 'Related Work'
        session.commit()
    provider = BoundaryProvider()
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    paragraph = client.get(path).json()['paragraphs'][0]
    response = client.post(path+'/review',json={'paragraph_id':paragraph['id']})
    assert response.status_code == 200, response.text
    assert response.json()['review']['checked'] == 0
    assert not provider.calls


def test_immediate_right_boundary_is_checked_before_distant_cached_neighbors(client,monkeypatch):
    path=seed_fragments(client)
    with client.app.state.database.sessions() as session:
        for index in range(7):
            session.add(PaperChunk(id=f'chain-{index}',paper_id='boundary-paper',page=2,section='Method',
                content=f'Fragment {index} discusses the memory mechanism without finishing the thought',
                bbox_json=json.dumps([54,60+index*60,295,90+index*60]),page_width=612,page_height=792))
        session.commit()
    provider=BoundaryProvider(join=False)
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    reading=client.get(path).json()
    selected=next(p for p in reading['paragraphs'] if p['text'].startswith('Fragment 4'))
    response=client.post(path+'/review',json={'paragraph_id':selected['id']})
    assert response.status_code==200,response.text
    assert any(b['left_end'].startswith('Fragment 4') and b['right_start'].startswith('Fragment 5') for b in provider.calls[0]['boundaries'])
    current=next(p for p in response.json()['paragraphs'] if p['id']==selected['id'])
    assert current['review_needed'] is False
    assert len(provider.calls) == 1, 'resolved selected boundaries must not trigger reviews of unrelated paragraphs'


def test_review_redirects_another_selected_fragment_into_the_merged_unit(client,monkeypatch):
    path=seed_fragments(client)
    provider=BoundaryProvider()
    monkeypatch.setattr('app.api.papers.get_model_provider',lambda:provider)
    before=client.get(path).json()['paragraphs']
    response=client.post(path+'/review',json={'paragraph_id':before[0]['id']})
    data=response.json()
    assert data['paragraph_redirects'][before[2]['id']]==data['selected_paragraph_id']


def test_review_drains_a_long_connected_fragment_chain(client,monkeypatch):
    """One review action must not leave the selected paragraph half-repaired."""
    path = seed_fragments(client)
    with client.app.state.database.sessions() as session:
        for index in range(10):
            session.add(PaperChunk(
                id=f'long-chain-{index}', paper_id='boundary-paper', page=2,
                section='Method',
                content=f'Fragment {index} carries an unfinished thought',
                bbox_json=json.dumps([54, 60 + index * 35, 295, 88 + index * 35]),
                page_width=612, page_height=792,
            ))
        session.commit()
    provider = BoundaryProvider()
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: provider)
    reading = client.get(path).json()
    selected = next(item for item in reading['paragraphs'] if item['id'].startswith('paragraph-')
                    and item['text'].startswith('Fragment 0'))

    response = client.post(path + '/review', json={'paragraph_id': selected['id']})

    assert response.status_code == 200, response.text
    data = response.json()
    joined = next(item for item in data['paragraphs'] if item['id'] == data['selected_paragraph_id'])
    assert joined['text'].count('Fragment ') == 10
    assert joined['review_needed'] is False
    assert data['review']['merged'] == 9
    assert len(provider.calls) > 1


def test_review_failure_after_an_earlier_batch_keeps_reading_units_unchanged(client,monkeypatch):
    path = seed_fragments(client)
    with client.app.state.database.sessions() as session:
        for index in range(8):
            session.add(PaperChunk(
                id=f'flaky-chain-{index}', paper_id='boundary-paper', page=2,
                section='Method',
                content=f'Fragment {index} carries an unfinished thought',
                bbox_json=json.dumps([54, 60 + index * 35, 295, 88 + index * 35]),
                page_width=612, page_height=792,
            ))
        session.commit()
    provider = FailAfterFirstBoundaryProvider()
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: provider)
    before = client.get(path).json()
    selected = next(item for item in before['paragraphs'] if item['text'].startswith('Fragment 0'))

    response = client.post(path + '/review', json={'paragraph_id': selected['id']})

    assert response.status_code == 504, response.text
    assert client.get(path).json()['paragraphs'] == before['paragraphs']
