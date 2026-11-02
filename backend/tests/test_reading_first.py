"""Reading-first admission uses isolated stores and no external model calls."""
import json
import threading
import time
import pytest
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.models import IntelligenceTask, Paper, PaperChunk, TranslationJob
from app.providers.profiles import ProfileStore


def test_background_admission_foreground_overtakes_waiting_analysis(tmp_path):
    from app.providers.priority import scheduled_work
    store = ProfileStore(tmp_path / 'models.json')
    release, entered = threading.Event(), threading.Event()
    order = []
    def run(name, rank):
        with scheduled_work(rank) if rank else nullcontext():
            with store.capacity('api', 1):
                order.append(name)
                if name == 'first':
                    entered.set()
                    assert release.wait(3)
    with ThreadPoolExecutor(3) as pool:
        a = pool.submit(run, 'first', 3)
        assert entered.wait(1)
        b = pool.submit(run, 'second', 3)
        foreground = pool.submit(run, 'foreground', 0)
        deadline = time.monotonic()+1
        while not store.priority.foreground_busy() and time.monotonic()<deadline:
            time.sleep(.005)
        release.set()
        for future in (a,b,foreground):
            future.result(2)
    assert order == ['first', 'foreground', 'second']


def test_official_queue_waits_for_current_call_without_cancelling_it(tmp_path):
    from app.providers.priority import scheduled_work, check_background
    store = ProfileStore(tmp_path / 'models.json')
    store.set_codex_concurrency(1)
    entered, release = threading.Event(), threading.Event()
    order = []
    def background():
        with scheduled_work(2), store.capacity('codex-subscription', 1):
            entered.set()
            assert release.wait(3)
            check_background()
            order.append('saved')
    def foreground():
        with store.capacity('codex-subscription', 1):
            order.append('answered')
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(background)
        assert entered.wait(1)
        b = pool.submit(foreground)
        time.sleep(.05)
        assert not b.done()
        release.set()
        a.result(2)
        b.result(2)
    assert order == ['saved', 'answered']


def test_queued_analysis_does_not_block_requested_api_pretranslation(client, monkeypatch):
    from app.services.translation_queue import enqueue
    from test_translation_queue import Translator
    worker = client.app.state.research_worker
    worker.stop()
    client.app.state.intelligence_worker.stop()
    provider = Translator()
    provider.name = 'ApiFixture'
    monkeypatch.setattr(worker.profiles, 'provider', lambda _: provider)
    monkeypatch.setattr(worker.profiles.codex, 'status', lambda **kw: (_ for _ in ()).throw(AssertionError('API must not read official quota')))
    with worker.database.sessions() as db:
        db.add(Paper(id='reading-paper', title='Reading first'))
        db.flush()
        db.add(PaperChunk(id='reading-source', paper_id='reading-paper', page=1,
            section='Introduction', content='A persistent memory stores information for future questions.'))
        db.add(IntelligenceTask(id='queued-analysis', paper_id='reading-paper'))
        db.commit()
        result = enqueue(worker, db, 'reading-paper', 'full', [], provider=provider)
    assert result['total'] == 1
    assert worker.process_next()
    with worker.database.sessions() as db:
        assert db.get(TranslationJob, result['id']).status == 'completed'
        assert db.get(IntelligenceTask, 'queued-analysis').status == 'queued'


def test_unavailable_official_quota_does_not_starve_a_separate_api_job(client, monkeypatch):
    from app.services.translation_queue import enqueue
    from test_translation_queue import Translator
    worker = client.app.state.research_worker
    worker.stop(); client.app.state.intelligence_worker.stop()
    official, api = Translator(), Translator()
    official.profile_id, api.profile_id = 'official', 'api'
    api.name = 'ApiFixture'
    monkeypatch.setattr(worker.profiles, 'provider', lambda key: official if key == 'official' else api)
    monkeypatch.setattr(worker.profiles.codex, 'status', lambda **kw: {'authenticated': True, 'limits': []})
    with worker.database.sessions() as db:
        db.add(Paper(id='connections', title='Independent connection queues'))
        db.flush()
        db.add(PaperChunk(id='connection-source', paper_id='connections', page=1, section='Introduction',
            content='The architecture stores earlier observations and retrieves them in a later task.'))
        db.commit()
        first = enqueue(worker, db, 'connections', 'full', [], provider=official)
        second = enqueue(worker, db, 'connections', 'full', [], provider=api)
    assert worker.process_next()
    assert len(api.calls) == 1 and official.calls == []
    with worker.database.sessions() as db:
        assert db.get(TranslationJob, first['id']).status == 'queued'
        assert db.get(TranslationJob, second['id']).status == 'completed'


def test_reading_preparation_survives_restart_and_manual_analysis_can_override(client):
    from app.services.intelligence import queue_tasks
    from types import SimpleNamespace
    client.app.state.intelligence_worker.stop()
    provider = SimpleNamespace(mode='remote', configured=True, profile_id='chosen')
    with client.app.state.database.sessions() as db:
        db.add(Paper(id='prep', title='Preparation'))
        db.commit()
        task = queue_tasks(db, ['prep'], provider, reading_first=True)[0]
        task_id = task.id
    with client.app.state.database.sessions() as db:
        task = db.get(IntelligenceTask, task_id)
        assert task.phase == 'prepare_reading'
        assert json.loads(task.report_json)['workflow']['profile_id'] == 'chosen'
        assert queue_tasks(db, ['prep'], provider)[0].id == task_id
        assert json.loads(task.report_json)['workflow']['analysis_requested'] is True


def test_long_synthesis_keeps_every_fact_and_full_local_evidence_without_reduction():
    from app.providers import harness as h
    from copy import deepcopy
    facts, pool = [], {}
    for i in range(360):
        key = f'E{i:05d}'
        text = f'Experiment {i} measures retention under condition {i}. ' + 'Detailed source evidence. ' * 22
        pool[key] = {'chunk_id': f'chunk-{i}', 'section': 'Results', 'source_text': text}
        facts.append({'id': f'fact-{i}', 'content': f'Experiment {i} has condition {i}.',
            'section': 'Results', 'citation_ids': [key]})
    originals = deepcopy(pool)
    context = h._synthesis_context(facts, pool)
    assert len(json.dumps(context, ensure_ascii=False)) <= h.SYNTHESIS_CHARS
    assert len(context['facts']) == len(facts)
    assert {e['id'] for e in context['evidence']} == set(pool)
    assert pool == originals
    assert context['evidence_view'] == 'indexed_excerpts'
    for evidence in context['evidence']:
        assert evidence['source_text'] in pool[evidence['id']]['source_text']


def test_compact_synthesis_citations_and_scientific_review_still_use_full_originals(monkeypatch):
    from app.providers import harness as h
    from app.providers.science_review import _source
    text = 'The mechanism stores source evidence. ' * 45 + 'An important negative result occurs in the final experiment.'
    chunk = PaperChunk(id='original', paper_id='p', page=9, section='Results', content=text)
    part = h.SourcePart('original:0:'+str(len(text)), chunk.id, 0, len(text), 9, 'Results', text)
    parts = {part.part_id: part}
    facts, invalid = h._facts([{'content': 'The final experiment reports a negative result.',
        'citations': [{'part_id': part.part_id, 'chunk_id': chunk.id, 'source_text': text}]}], parts)
    assert invalid == 0
    pool = h._citation_pool(facts, parts)
    monkeypatch.setattr(h, 'SYNTHESIS_CHARS', 800)
    context = h._synthesis_context(facts, pool)
    assert context['evidence_view'] == 'indexed_excerpts'
    assert len(context['evidence'][0]['source_text']) < len(text)
    card, invalid = h._card({'main_results': {'content': 'The final experiment reports a negative result.',
        'citation_ids': facts[0]['citation_ids']}}, facts, parts, [chunk], 'model', 'prompt', pool)
    assert invalid == 0
    citation = card.card['main_results'].citations[0]
    assert citation.source_text == text
    assert _source(citation, parts)[1] == text


def test_compact_evidence_preserves_each_sources_exact_section_even_for_cross_section_facts():
    from app.providers.evidence_view import compact_evidence_context
    evidence = [{'id': f'E{i:05d}', 'section': f'{i % 7} Exact original heading',
        'source_text': 'A long original passage about memory and retrieval. ' * 20}
        for i in range(40)]
    context = {'facts': [{'content': 'This mechanism spans multiple source sections.',
        'section': evidence[0]['section'], 'citation_ids': [e['id'] for e in evidence]}],
        'evidence': evidence}
    view = compact_evidence_context(context, 12000)
    assert view.get('evidence_view') == 'indexed_excerpts'
    lookup = {key: group['section'] for group in view.get('evidence_sections', [])
        for key in group['citation_ids']}
    assert lookup == {item['id']: item['section'] for item in evidence}
    assert len(json.dumps(view, ensure_ascii=False)) <= 12000
    assert view['facts'] == context['facts']


def test_section_repair_keeps_complete_related_evidence_without_resending_the_paper():
    from app.providers.card_recovery import section_repair_context
    context = {'facts': [
        {'content': 'A cross-section mechanism.', 'citation_ids': ['E1', 'E2']},
        {'content': 'An unrelated benchmark.', 'citation_ids': ['E3']}],
        'evidence': [{'id': key, 'section': key, 'source_text': 'Complete original source ' + key}
            for key in ('E1', 'E2', 'E3')]}
    targets = [{'field': 'section_summaries[0]', 'reason_codes': ['section_mismatch'],
        'rejected_value_complete': True, 'rejected_value': json.dumps({'citation_ids': ['E1']})}]
    scoped = section_repair_context(context, targets)
    assert scoped['facts'] == context['facts'][:1]
    assert scoped['evidence'] == context['evidence'][:2]
    targets[0]['reason_codes'] = ['invalid_citation_ids']
    assert section_repair_context(context, targets) is None


def test_scientific_review_has_its_own_visible_progress_phase(tmp_path):
    from app.providers.harness import analyze_full_paper
    from test_science_harness import setup, ScienceProvider
    db, chunks = setup(tmp_path)
    phases = []
    result = analyze_full_paper(db, ScienceProvider(), chunks,
        progress=lambda phase, *_: phases.append(phase))
    assert not result.report['partial']
    assert 'science_review' in phases
    assert phases.index('synthesize') < phases.index('science_review') < phases.index('complete')


def test_missing_knowledge_fields_are_recovered_with_visible_stage_without_repeat_extraction(tmp_path):
    from app.providers.harness import analyze_full_paper
    from test_science_harness import setup, ScienceProvider
    class Provider(ScienceProvider):
        def complete_json(self, system, payload, **options):
            if payload.get('stage') == 'knowledge_intake':
                self.calls.append(payload)
                return {'knowledge_candidates': [], 'knowledge_relations': []}
            result = super().complete_json(system, payload, **options)
            if 'card' in result:
                result.pop('knowledge_candidates', None)
                result.pop('knowledge_relations', None)
            return result
    db, chunks = setup(tmp_path)
    phases = []
    provider = Provider()
    result = analyze_full_paper(db, provider, chunks, progress=lambda phase, *_: phases.append(phase))
    assert result.report['knowledge_fallback']['completed']
    assert 'knowledge_intake' in phases
    assert sum('chunks' in payload for payload in provider.calls) == 1


@pytest.mark.parametrize('outcome', ['completed', 'failed', 'paused', 'cancelled'])
def test_import_preparation_precedes_analysis_and_terminal_translation_never_deadlocks(client, monkeypatch, outcome):
    from app.services.intelligence import queue_tasks
    from test_translation_queue import Translator
    from app.providers.base import ProviderError
    analysis = client.app.state.intelligence_worker
    research = client.app.state.research_worker
    analysis.stop()
    research.stop()
    provider = Translator()
    provider.name = 'ApiFixture'
    calls = []
    def complete_json(system, payload, **kw):
        calls.append(payload)
        raise ProviderError('Reached deep analysis after reading preparation')
    provider.complete_json = complete_json
    monkeypatch.setattr(analysis, 'provider_factory', lambda: provider)
    monkeypatch.setattr(research.profiles, 'provider', lambda _: provider)
    with analysis.database.sessions() as db:
        db.add(Paper(id='ordered', title='Reading workflow'))
        db.flush()
        db.add(PaperChunk(id='ordered-source', paper_id='ordered', page=1, section='Introduction',
            content='This architecture retrieves earlier observations from a persistent memory.'))
        db.commit()
        task_id = queue_tasks(db, ['ordered'], provider, reading_first=True)[0].id
    assert analysis.process_next()
    with analysis.database.sessions() as db:
        task = db.get(IntelligenceTask, task_id)
        assert task.status == 'queued' and task.phase == 'awaiting_translation'
        job_id = json.loads(task.report_json)['workflow']['translation_job_id']
    assert calls == []
    assert not analysis.process_next()
    if outcome == 'completed':
        assert research.process_next()
    else:
        with analysis.database.sessions() as db:
            db.get(TranslationJob, job_id).status = outcome
            db.commit()
    assert analysis.process_next()
    assert len(calls) == 1
    with analysis.database.sessions() as db:
        task = db.get(IntelligenceTask, task_id)
        assert task.status == 'failed' and 'Reached deep analysis' in task.error
        assert json.loads(task.report_json)['workflow']['translation_outcome'] == outcome


def test_manual_override_skips_wait_without_cancelling_pretranslation(client, monkeypatch):
    from app.services.intelligence import queue_tasks
    from app.services.reading_workflow import waiting_for_translation
    from test_translation_queue import Translator
    worker = client.app.state.intelligence_worker
    worker.stop()
    client.app.state.research_worker.stop()
    provider = Translator()
    monkeypatch.setattr(worker, 'provider_factory', lambda: provider)
    monkeypatch.setattr(worker.profiles, 'provider', lambda _: provider)
    with worker.database.sessions() as db:
        db.add(Paper(id='override', title='Manual override'))
        db.flush()
        db.add(PaperChunk(id='override-source', paper_id='override', page=1, section='Introduction',
            content='The method stores previous evidence in an external memory.'))
        db.commit()
        task_id = queue_tasks(db, ['override'], provider, reading_first=True)[0].id
    worker.process_next()
    with worker.database.sessions() as db:
        task = db.get(IntelligenceTask, task_id)
        assert waiting_for_translation(db, task)
        job_id = json.loads(task.report_json)['workflow']['translation_job_id']
        assert queue_tasks(db, ['override'], provider)[0].id == task_id
        assert not waiting_for_translation(db, task)
        assert db.get(TranslationJob, job_id).status == 'queued'


def test_prompt_update_during_generation_does_not_misreport_source_change(client, monkeypatch, tmp_path):
    """A result retains its generation version; only source edits block publishing."""
    from app.providers import harness
    from app.services.intelligence import queue_tasks
    from test_intelligence_jobs import FailingProvider, import_paper
    worker = client.app.state.intelligence_worker
    worker.stop()
    client.app.state.research_worker.stop()
    paper = import_paper(client)
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    for name in harness.PROMPT_NAMES:
        (prompts / name).write_text((harness.PROMPTS_DIR / name).read_text(encoding='utf-8-sig'), encoding='utf-8')
    monkeypatch.setattr(harness, 'PROMPTS_DIR', prompts)
    class Provider(FailingProvider):
        def complete_json(self, system, payload, **kwargs):
            if 'chunks' in payload:
                path = prompts / 'paper_synthesize.txt'
                path.write_text(path.read_text(encoding='utf-8')+'\nNew guidance for subsequent tasks.\n', encoding='utf-8')
                return {'facts': [{'content': 'The method retrieves passages.', 'source_ids': [payload['chunks'][0]['source_id']]}]}
            if payload.get('stage') == 'review_card_science':
                return {'items': [{'field': item['field'], 'decision': 'supported'} for item in payload['items']]}
            return {'method': {'content': 'The method retrieves passages.', 'citation_ids': payload['facts'][0]['citation_ids']}}
    provider = Provider()
    with worker.database.sessions() as db:
        task_id = queue_tasks(db, [paper['id']], provider)[0].id
    worker.process_next(provider)
    with worker.database.sessions() as db:
        task = db.get(IntelligenceTask, task_id)
        assert task.status == 'completed', task.error


def test_automatic_analysis_waits_at_quota_reserve_without_spending_a_generation(client, monkeypatch):
    from app.services.intelligence import queue_tasks
    from test_translation_queue import Translator
    from app.providers.base import ProviderError
    analysis, research = client.app.state.intelligence_worker, client.app.state.research_worker
    analysis.stop(); research.stop()
    provider = Translator()
    calls = []
    def generate(*args, **kw):
        calls.append('generation')
        raise ProviderError('Unexpected generation')
    provider.complete_json = generate
    monkeypatch.setattr(analysis, 'provider_factory', lambda: provider)
    monkeypatch.setattr(research.profiles, 'provider', lambda _: provider)
    monkeypatch.setattr(research.profiles.codex, 'status', lambda **kw: {'authenticated': True, 'limits': [
        {'name': 'primary', 'used_percent': 90, 'window_minutes': 300, 'resets_at': time.time()+300}]})
    with analysis.database.sessions() as db:
        db.add(Paper(id='quota-paper', title='Quota preparation'))
        db.flush()
        db.add(PaperChunk(id='quota-source', paper_id='quota-paper', page=1, section='Introduction',
            content='The system stores memories and retrieves them to answer future questions.'))
        db.commit()
        task_id = queue_tasks(db, ['quota-paper'], provider, reading_first=True)[0].id
    analysis.process_next()
    with analysis.database.sessions() as db:
        plan = json.loads(db.get(IntelligenceTask, task_id).report_json)['workflow']
        db.get(TranslationJob, plan['translation_job_id']).status = 'completed'
        db.commit()
    assert analysis.process_next()
    assert calls == []
    with analysis.database.sessions() as db:
        task = db.get(IntelligenceTask, task_id)
        assert task.status == 'queued' and task.phase == 'awaiting_quota'
        assert json.loads(task.report_json)['usage']['remote_calls'] == 0
    assert not analysis.process_next()  # wait is durable, not a retry storm
