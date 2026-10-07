"""A scientific correction must reach the UI even when another claim is rejected."""
import json

import fitz
import pytest

from app.models import Paper
from app.providers.base import ProviderError


class ReviewProvider:
    name = 'ReviewPublicationTest'
    mode = 'remote'
    configured = True
    base_url = 'https://model.example'
    model = 'review-model'
    wire_api = 'responses'
    reasoning_effort = 'high'
    last_usage = {}
    response_model = model

    def __init__(self, failure=None, *, tldr=False):
        self.failure = failure
        self.tldr = tldr

    def complete_json(self, system, payload, **options):
        if 'chunks' in payload:
            facts = [{'content': 'The measured result is 71 of 100.',
                      'source_ids': [payload['chunks'][0]['source_id']]}]
            if self.failure == 'extract':
                facts.append({'content': 'Unverifiable extraction.', 'source_ids': ['foreign']})
            return {'facts': facts}
        if payload.get('stage') == 'review_card_science':
            if self.failure == 'outage':
                raise ProviderError('Safe service outage', code='authentication')
            items = []
            for item in payload['items']:
                if item['field'] == 'main_results':
                    items.append({'field': 'main_results', 'decision': 'corrected',
                        'value': {'content': 'This evaluation retrieves 71 of 100 correct passages.',
                                  'citation_ids': item['citation_ids']}})
                elif item['field'] in ('tldr[1]', 'tldr[2]'):
                    items.append({'field': item['field'], 'decision': 'supported'})
                elif self.failure != 'missing':
                    items.append({'field': item['field'], 'decision': 'unsupported'})
            return {'items': items}
        refs = payload['facts'][0]['citation_ids']
        card = {
            'method': {'content': 'A usable retrieval method.', 'citation_ids': refs},
            'main_results': {'content': 'The accuracy is always 100 percent.', 'citation_ids': refs},
            'claims': [{'content': 'All tasks always achieve 100 percent.', 'citation_ids': refs}]}
        if self.tldr:
            card['tldr'] = [{'content': content, 'citation_ids': refs} for content in
                            ('All tasks achieve 100 percent.', 'A retrieval evaluation.', 'A measured sample.')]
        return {'card': card}


def previous_remote(client):
    client.app.state.intelligence_worker.stop()
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), 'The method retrieves 71 of 100 correct passages.')
        data = document.tobytes()
    paper = client.post('/api/papers/import', files={'file': ('paper.pdf', data)}).json()
    with client.app.state.database.sessions() as session:
        stored = session.get(Paper, paper['id'])
        stored.analysis.mode = 'remote'
        stored.intelligence_status = 'completed'
        stored.intelligence_report_json = json.dumps({'prior': 'ready'})
        session.commit()
    return client.get('/api/papers/' + paper['id']).json()


def analyze(client, monkeypatch, paper, provider):
    monkeypatch.setattr('app.api.intelligence.get_model_provider', lambda: provider)
    response = client.post('/api/intelligence/tasks', json={'paper_ids': [paper['id']], 'force': True})
    assert response.status_code == 200
    assert client.app.state.intelligence_worker.process_next(provider)
    return client.get('/api/papers/' + paper['id']).json()


def test_valid_reviewed_partial_publishes_corrected_results_and_removes_unsupported_claim(client, monkeypatch):
    prior = previous_remote(client)
    after = analyze(client, monkeypatch, prior, ReviewProvider())
    task = after['intelligence_task']
    assert task['status'] == 'partial'
    assert task['report']['science_review']['checked_items'] == 2
    assert task['report']['science_review']['corrected_items'] == 1
    assert task['report']['science_review']['rejected_items'] == 1
    assert after['analysis']['card']['main_results']['content'] == 'This evaluation retrieves 71 of 100 correct passages.'
    assert after['analysis']['card']['claims'] == []
    assert not task['report']['retained_previous_card']
    assert after['intelligence_report'] == task['report']
    assert after['evidence'] != prior['evidence']


@pytest.mark.parametrize('failure', ['missing', 'outage', 'extract', 'deferred'])
def test_incomplete_or_malformed_review_preserves_previous_remote_card(client, monkeypatch, failure):
    prior = previous_remote(client)
    if failure == 'deferred':
        import app.providers.science_review as science
        original = science.prepare_reviews
        monkeypatch.setattr(science, 'prepare_reviews',
            lambda analysis, parts: original(analysis, parts, max_batches=1, max_items=1))
    after = analyze(client, monkeypatch, prior, ReviewProvider(failure))
    assert after['intelligence_task']['status'] == 'partial'
    assert after['intelligence_task']['report']['retained_previous_card']
    assert after['analysis'] == prior['analysis']
    assert after['evidence'] == prior['evidence']
    assert after['intelligence_report'] == prior['intelligence_report']


def test_scientific_tldr_deletion_publishes_surviving_card_without_resurrecting_old_lines(client, monkeypatch):
    prior = previous_remote(client)
    after = analyze(client, monkeypatch, prior, ReviewProvider(tldr=True))
    report = after['intelligence_task']['report']
    assert after['intelligence_task']['status'] == 'partial'
    assert report['science_review']['cardinality_drops'] == [
        {'field': 'tldr', 'reason': 'science_rejection', 'surviving_entries': 2}]
    assert not report['retained_previous_card']
    assert after['analysis']['card']['tldr'] == []
    assert after['analysis']['card']['main_results']['content'].startswith('This evaluation')


@pytest.mark.parametrize('changed', ['cardinality_three', 'cardinality_negative', 'false_tldr_cause', 'empty_card'])
def test_inconsistent_publication_reports_cannot_replace_a_ready_card(client, monkeypatch, changed):
    from copy import deepcopy
    from app.providers.base import AnalysisResult
    from app.services.intelligence import publish_reviewed_partial
    prior = previous_remote(client)
    after = analyze(client, monkeypatch, prior, ReviewProvider())
    report = deepcopy(after['intelligence_report'])
    analysis = AnalysisResult(card={'main_results': object()}, citations=[object()])
    if changed == 'empty_card':
        analysis = AnalysisResult()
    else:
        count = {'cardinality_three': 3, 'cardinality_negative': -1, 'false_tldr_cause': 2}[changed]
        report['science_review']['card_invalid_entries'] = count
        report['science_review']['cardinality_drops'] = [
            {'field': 'tldr', 'reason': 'science_rejection', 'surviving_entries': count}]
        report['invalid_entries'] += count
    assert not publish_reviewed_partial(report, analysis)
