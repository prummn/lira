"""Old PDF section labels must be reconciled before a scientific model request."""
import json
import hashlib
from pathlib import Path

import fitz
import pytest

from app.models import Paper
from app.providers.base import ProviderError
from app.services.intelligence import queue_tasks


class ObservingProvider:
    name = 'ObserveSourceSections'
    mode = 'remote'
    configured = True
    base_url = 'https://model.example'
    model = 'test'
    wire_api = 'responses'
    reasoning_effort = 'high'
    response_model = None
    last_usage = {}

    def __init__(self):
        self.observed = []

    def complete_json(self, system, payload, **options):
        self.observed.extend(payload.get('chunks', []))
        raise ProviderError('Stop after observing the first request', code='authentication')


def imported_old_sections(client):
    client.app.state.intelligence_worker.stop()
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), 'Section Recovery Study', fontsize=18)
        page.insert_text((50, 120), '4.3 Experimental Settings', fontsize=12, fontname='hebo')
        page.insert_text((50, 155), 'The method retrieves 71 of 100 correct passages.', fontsize=11)
        page.insert_text((50, 180), 'The evaluation uses a fixed sample of retrieval queries.', fontsize=11)
        data = document.tobytes()
    response = client.post('/api/papers/import', files={'file': ('sections.pdf', data)})
    assert response.status_code == 201
    paper = response.json()
    with client.app.state.database.sessions() as session:
        stored = session.get(Paper, paper['id'])
        target = next(chunk for chunk in stored.chunks if 'retrieves 71' in chunk.content)
        assert target.section == '4.3 Experimental Settings'
        target.section = '4.2 Baselines'
        for evidence in stored.evidence:
            if evidence.chunk_id == target.id:
                evidence.section = target.section
        stored.title = 'My manually curated title'
        stored.abstract = 'My retained abstract'
        stored.is_favorite = True
        stored.reading_status = 'reading'
        stored.metadata_sources_json = json.dumps({'title': 'manual', 'abstract': 'manual'})
        session.commit()
    return client.get('/api/papers/' + paper['id']).json()


def test_actual_worker_reidentifies_old_sections_before_first_model_request_without_rewriting_sources(client):
    prior = imported_old_sections(client)
    provider = ObservingProvider()
    database = client.app.state.database
    with database.sessions() as session:
        queue_tasks(session, [prior['id']], provider, force=True)
    assert client.app.state.intelligence_worker.process_next(provider)
    observed = next(item for item in provider.observed if 'retrieves 71' in item['content'])
    assert observed['section'] == '4.3 Experimental Settings'
    after = client.get('/api/papers/' + prior['id']).json()
    for key in ('title', 'abstract', 'is_favorite', 'reading_status', 'metadata_sources', 'authors'):
        assert after[key] == prior[key]
    assert after['analysis'] == prior['analysis']
    assert [{k: v for k, v in row.items() if k != 'section'} for row in after['chunks']] == [
        {k: v for k, v in row.items() if k != 'section'} for row in prior['chunks']]
    assert [{k: v for k, v in row.items() if k != 'section'} for row in after['evidence']] == [
        {k: v for k, v in row.items() if k != 'section'} for row in prior['evidence']]
    changed = next(chunk for chunk in after['chunks'] if 'retrieves 71' in chunk['content'])
    assert changed['section'] == '4.3 Experimental Settings'
    assert all(e['section'] == changed['section'] for e in after['evidence'] if e['chunk_id'] == changed['id'])
    report = after['intelligence_task']['report']['source_structure']
    assert report['changed_chunks'] == 1
    assert report['unmatched_chunks'] == 0
    assert report['retained_card_uses_previous_structure'] is True


def test_second_failed_attempt_preserves_known_stale_structure_after_zero_new_section_changes(client):
    prior = imported_old_sections(client)
    provider = ObservingProvider()
    database = client.app.state.database
    for _ in range(2):
        with database.sessions() as session:
            queue_tasks(session, [prior['id']], provider, force=True)
        assert client.app.state.intelligence_worker.process_next(provider)
    after = client.get('/api/papers/' + prior['id']).json()
    report = after['intelligence_task']['report']['source_structure']
    assert report['changed_chunks'] == 0
    assert report['retained_card_uses_previous_structure'] is True
    assert after['intelligence_report']['source_structure_stale'] is True
    assert after['analysis'] == prior['analysis']


@pytest.mark.parametrize('interruption', ['cancel', 'section', 'content', 'file'])
def test_cancel_or_concurrent_source_edit_during_local_parse_prevents_new_model_calls(client, monkeypatch, interruption):
    from app.services import intelligence
    prior = imported_old_sections(client)
    provider = ObservingProvider()
    database = client.app.state.database
    with database.sessions() as session:
        task_id = queue_tasks(session, [prior['id']], provider, force=True)[0].id
    original = intelligence.prepare_source_sections
    def interrupted(*args):
        result = original(*args)
        if interruption == 'cancel':
            assert client.post('/api/intelligence/tasks/' + task_id + '/cancel').json()['status'] == 'cancelled'
        elif interruption == 'file':
            path = Path(args[0])
            path.write_bytes(path.read_bytes() + b'changed after parsing')
        else:
            with database.sessions() as session:
                paper = session.get(Paper, prior['id'])
                chunk = next(item for item in paper.chunks if 'retrieves 71' in item.content)
                if interruption == 'section':
                    chunk.section = 'Concurrent metadata edit'
                else:
                    chunk.content += ' Concurrent source edit.'
                session.commit()
        return result
    monkeypatch.setattr(intelligence, 'prepare_source_sections', interrupted)
    assert client.app.state.intelligence_worker.process_next(provider)
    assert provider.observed == []
    after = client.get('/api/papers/' + prior['id']).json()
    assert after['analysis'] == prior['analysis']
    changed = next(item for item in after['chunks'] if 'retrieves 71' in item['content'])
    assert changed['section'] == ('Concurrent metadata edit' if interruption == 'section' else '4.2 Baselines')
    if interruption != 'cancel':
        report = after['intelligence_task']['report']['source_structure']
        assert report['applied'] is False
        assert report['changed_chunks'] == 0


def preparation_inputs(client):
    prior = imported_old_sections(client)
    with client.app.state.database.sessions() as session:
        paper = session.get(Paper, prior['id'])
        path, sha = paper.pdf_path, paper.sha256
        chunks = list(paper.chunks)
        session.expunge_all()
    return path, sha, chunks


@pytest.mark.parametrize('defect', ['changed_pdf', 'dimension', 'duplicate', 'mixed'])
def test_unproven_source_identity_or_membership_never_authorizes_section_replacement(client, monkeypatch, defect):
    from app.services import source_sections
    from app.services.pdf import ParsedBlock, ParsedPDF
    path, sha, chunks = preparation_inputs(client)
    target = next(chunk for chunk in chunks if 'retrieves 71' in chunk.content)
    if defect == 'changed_pdf':
        Path(path).write_bytes(Path(path).read_bytes() + b'changed')
        expected = 'pdf_changed'
    elif defect == 'dimension':
        target.page_width += 1
        expected = 'dimension_mismatch'
    else:
        bounds = tuple(json.loads(target.bbox_json))
        if defect == 'duplicate':
            block = ParsedBlock(target.page, '4.3 Experimental Settings', target.content, bounds,
                                target.page_width, target.page_height)
            parsed = ParsedPDF(1, None, [block, block])
            expected = 'ambiguous'
        else:
            middle = (bounds[1] + bounds[3]) / 2
            chunks = [target]
            target.content = 'First section.\nSecond section.'
            parsed = ParsedPDF(1, None, [
                ParsedBlock(target.page, 'First', 'First section.', (bounds[0], bounds[1], bounds[2], middle), target.page_width, target.page_height),
                ParsedBlock(target.page, 'Second', 'Second section.', (bounds[0], middle, bounds[2], bounds[3]), target.page_width, target.page_height)])
            expected = 'mixed'
        monkeypatch.setattr(source_sections, 'parse_pdf', lambda data: parsed)
    before = source_sections.source_digest(chunks)
    plan = source_sections.prepare_source_sections(path, sha, chunks)
    assert target.id not in plan.changes
    assert plan.report['complete'] is False
    assert plan.report.get('failure_code') == expected or plan.report['match_types'].get(expected) == 1
    assert source_sections.source_digest(chunks) == before


@pytest.mark.parametrize('defect', ['missing', 'corrupt', 'no_hash'])
def test_unavailable_local_pdf_is_reported_without_rewriting_stored_sources(client, defect):
    from app.services.source_sections import prepare_source_sections
    path, sha, chunks = preparation_inputs(client)
    if defect == 'missing':
        Path(path).unlink()
    elif defect == 'corrupt':
        data = b'%PDF-broken'
        Path(path).write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
    else:
        sha = None
    plan = prepare_source_sections(path, sha, chunks)
    assert not plan.changes
    assert plan.report['available'] is False
    assert plan.report['complete'] is False
    assert plan.report['failure_code'] == {'missing': 'missing_pdf', 'corrupt': 'parse_failure', 'no_hash': 'missing_pdf_identity'}[defect]


@pytest.mark.parametrize('edited_field', ['pdf_path', 'sha256'])
def test_concurrent_pdf_identity_change_during_model_work_cannot_publish_old_pdf_analysis(client, edited_field):
    prior = imported_old_sections(client)
    database = client.app.state.database
    class UpdatingProvider(ObservingProvider):
        def complete_json(self, system, payload, **options):
            if 'chunks' in payload:
                original = payload['chunks'][0]
                return {'facts': [{'content': original['content'], 'source_ids': [original['source_id']]}]}
            if payload.get('stage') == 'review_card_science':
                return {'items': [{'field': item['field'], 'decision': 'supported'} for item in payload['items']]}
            with database.sessions() as session:
                paper = session.get(Paper, prior['id'])
                if edited_field == 'pdf_path':
                    replacement = Path(paper.pdf_path).with_name('replacement.pdf')
                    replacement.write_bytes(Path(paper.pdf_path).read_bytes())
                    paper.pdf_path = str(replacement)
                else:
                    paper.sha256 = '0' * 64
                session.commit()
            return {'card': {'main_results': {'content': 'New candidate result.', 'citation_ids': payload['facts'][0]['citation_ids']}}}
    provider = UpdatingProvider()
    with database.sessions() as session:
        queue_tasks(session, [prior['id']], provider, force=True)
    assert client.app.state.intelligence_worker.process_next(provider)
    after = client.get('/api/papers/' + prior['id']).json()
    assert after['analysis'] == prior['analysis']
    assert after['intelligence_task']['status'] == 'failed'
    assert '原文在分析期间发生变化' in after['intelligence_task']['error']
