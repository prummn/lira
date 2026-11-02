from __future__ import annotations
import json
import fitz
import pytest
from fastapi.testclient import TestClient
from app.models import Paper, PaperChunk


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


def test_legacy_local_refresh_clears_stale_remote_intelligence_state(client: TestClient) -> None:
    from datetime import datetime, timezone
    from app.models import Paper
    from app.services.intelligence import queue_tasks
    paper = card_paper(client)
    with client.app.state.database.sessions() as session:
        stored = session.get(Paper, paper['id'])
        stored.analysis.mode = 'remote'
        stored.analysis.provider = 'RemoteProvider'
        stored.analysis.card_json = json.dumps({'title': stored.title,
            'method': {'content': 'Published remote method.', 'evidence_ids': []}})
        stored.intelligence_status = 'completed'
        stored.intelligence_report_json = json.dumps({'result_fingerprint': 'stale-remote-fingerprint'})
        stored.intelligence_analyzed_at = datetime.now(timezone.utc)
        session.commit()
    response = client.post(f"/api/papers/{paper['id']}/analyze")
    assert response.status_code == 200
    with client.app.state.database.sessions() as session:
        stored = session.get(Paper, paper['id'])
        assert stored.analysis.mode == 'extractive'
        assert stored.intelligence_status == 'unanalyzed'
        assert stored.intelligence_report_json is None
        assert stored.intelligence_analyzed_at is None
        class RemoteProvider:
            mode, configured, name, model = 'remote', True, 'RemoteProvider', 'remote-model'
        task = queue_tasks(session, [stored.id], RemoteProvider(), force=False)[0]
        assert task.status == 'queued'


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


def test_selection_question_receives_natural_language_and_expanded_paper_context(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.base import AnswerResult, VerifiedCitation

    paper = card_paper(client)
    selected_chunk = next(chunk for chunk in paper['chunks'] if 'LocalCorpus' in chunk['content'])
    seen: dict[str, object] = {}

    class RecordingProvider:
        name = 'RecordingProvider'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask(self, question, chunks):
            seen['question'] = question
            seen['chunks'] = chunks
            selected = next(chunk for chunk in chunks if chunk.id == selected_chunk['id'])
            return AnswerResult(
                'EM 是论文中用于判断答案是否完全匹配的指标。',
                [],
                False,
                [VerifiedCitation(selected, 'LocalCorpus', 'EM 是论文中用于判断答案是否完全匹配的指标。', 'llm_summary')],
            )

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: RecordingProvider())
    response = client.post(
        f"/api/papers/{paper['id']}/explain",
        json={
            'chunk_id': selected_chunk['id'],
            'selected_text': 'LocalCorpus',
            'question': '这里的 EM 指的是什么？',
            'context_scope': 'auto',
            'history': [{'question': '这句话在比较什么？', 'answer': '它在比较 ReAct 与 CoT。'}],
        },
    )
    assert response.status_code == 200
    assert '这里的 EM 指的是什么' in seen['question']
    assert '这句话在比较什么' in seen['question']
    assert len(seen['chunks']) > 1
    assert response.json()['answer'].startswith('EM 是论文中')
    assert response.json()['context_scope'] == 'section'


def test_translation_selection_keeps_english_evidence_and_adds_translation_hint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.base import AnswerResult, VerifiedCitation

    paper = card_paper(client)
    selected_chunk = next(chunk for chunk in paper['chunks'] if 'LocalCorpus' in chunk['content'])
    seen: dict[str, object] = {}

    class RecordingProvider:
        name = 'TranslationSelectionFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask(self, question, chunks):
            seen['question'] = question
            selected = next(chunk for chunk in chunks if chunk.id == selected_chunk['id'])
            return AnswerResult('已使用英文原文核对译文选段。', [], False,
                                [VerifiedCitation(selected, 'LocalCorpus', '已使用英文原文核对译文选段。', 'llm_summary')])

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: RecordingProvider())
    response = client.post(f"/api/papers/{paper['id']}/explain", json={
        'chunk_id': selected_chunk['id'], 'selected_text': 'LocalCorpus',
        'translated_text': '本地语料', 'question': '这个译文对应的英文是什么意思？',
    })
    assert response.status_code == 200, response.text
    assert '所选原文：LocalCorpus' in seen['question']
    assert '用户在译文中选中的对应片段' in seen['question']
    assert '本地语料' in seen['question']
    assert response.json()['citations'][0]['source_text'] == 'LocalCorpus'


def test_selection_explanation_accepts_a_long_visual_selection_across_pdf_blocks(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A browser selection can cross many extraction blocks and columns."""
    from app.providers.base import AnswerResult, VerifiedCitation

    paper = card_paper(client)
    pieces = [
        'We introduce a new deep memory retrieval (DMR) task based on',
        'the MSC dataset designed to test the consistency of a conversational agent.',
        'In DMR, the conversational agent is asked a question by the user',
        'that explicitly refers back to a prior conversation and has a very narrow',
        'expected answer range. We generated the DMR question-answer (QA) pairs',
        'using a separate LLM that was instructed to write a question from one user',
        'to another that could only be answered correctly using knowledge gained',
        'from the past.',
    ]
    with client.app.state.database.sessions() as session:
        session.add(PaperChunk(
            id='selection-anchor-wrong', paper_id=paper['id'], page=5,
            section='3.1.1. Deep memory retrieval task', content='Page header and unrelated table text',
            bbox_json=json.dumps([40, 40, 300, 60]), page_width=612, page_height=792,
        ))
        for index, content in enumerate(pieces):
            session.add(PaperChunk(
                id=f'selection-piece-{index:02d}', paper_id=paper['id'], page=5,
                section='3.1.1. Deep memory retrieval task', content=content,
                bbox_json=json.dumps([55, 100 + index * 45, 290, 135 + index * 45]),
                page_width=612, page_height=792,
            ))
        session.commit()
    seen: dict[str, object] = {}

    class RecordingProvider:
        name = 'LongSelectionFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask(self, question, chunks):
            seen['chunks'] = chunks
            anchor = next(chunk for chunk in chunks if chunk.id == 'selection-piece-00')
            return AnswerResult('已读取跨块选区。', [], False,
                                [VerifiedCitation(anchor, anchor.content, '已读取跨块选区。', 'llm_summary')])

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: RecordingProvider())
    selected_text = ' '.join(pieces)
    response = client.post(f"/api/papers/{paper['id']}/explain", json={
        'chunk_id': 'selection-anchor-wrong', 'selected_text': selected_text,
        'question': '这部分实验在做什么？', 'context_scope': 'auto',
    })
    assert response.status_code == 200, response.text
    assert response.json()['answer'] == '已读取跨块选区。'
    assert any(chunk.id == 'selection-piece-00' for chunk in seen['chunks'])


def test_visual_question_accepts_page_image_and_uses_vision_provider(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.base import AnswerResult, VerifiedCitation

    paper = card_paper(client)
    page_chunk = paper['chunks'][0]
    seen: dict[str, object] = {}

    class VisionProvider:
        name = 'VisionFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask_with_image(self, question, chunks, image_data_url):
            seen.update(question=question, chunks=chunks, image=image_data_url)
            return AnswerResult('图像中展示了一个趋势。', [], False, [VerifiedCitation(page_chunk_obj, page_chunk_obj.content, '图像中展示了一个趋势。', 'llm_summary')])

        def ask(self, question, chunks):
            raise AssertionError('visual questions must use the vision path')

    from app.models import PaperChunk
    page_chunk_obj = PaperChunk(id=page_chunk['id'], paper_id=paper['id'], page=page_chunk['page'], content=page_chunk['content'], section=page_chunk['section'], bbox_json=json.dumps(page_chunk['bbox']))
    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: VisionProvider())
    response = client.post(f"/api/papers/{paper['id']}/explain", json={
        'page': page_chunk['page'],
        'image_data_url': 'data:image/png;base64,ZmFrZQ==',
        'question': '这张图展示了什么？',
    })
    assert response.status_code == 200
    assert seen['image'] == 'data:image/png;base64,ZmFrZQ=='
    assert response.json()['visual_used'] is True


def test_visual_region_context_accepts_canonical_bbox_and_preserves_chart_identity(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.base import AnswerResult

    paper = card_paper(client)

    class VisionProvider:
        name = 'VisionFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask_with_image(self, question, chunks, image_data_url):
            return AnswerResult('表格中的 Apply 是修复成功率。', [], False, [])

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: VisionProvider())
    response = client.post(f"/api/papers/{paper['id']}/explain", json={
        'page': 1,
        'bbox': [48, 120, 548, 290],
        'visual_kind': 'table',
        'visual_label': 'Table 5',
        'image_data_url': 'data:image/png;base64,ZmFrZQ==',
        'selected_text': 'Table 5: SWE-bench results',
        'question': 'Apply 指标是什么意思？',
    })
    assert response.status_code == 200, response.text
    conversations = client.get(f"/api/conversations?kind=explanation&paper_id={paper['id']}").json()['items']
    assert conversations[0]['context']['bbox'] == [48.0, 120.0, 548.0, 290.0]
    assert conversations[0]['context']['visual_kind'] == 'table'
    assert conversations[0]['context']['visual_label'] == 'Table 5'


def test_selection_context_preserves_cross_page_paragraph_order(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.explanation import selection_context

    paper_data = card_paper(client)
    with client.app.state.database.sessions() as session:
        paper = session.get(Paper, paper_data['id'])
        assert paper is not None
        chunks = list(paper.chunks)
        selected = next(chunk for chunk in chunks if 'LocalCorpus' in chunk.content)
        ordered = [selected, next(chunk for chunk in chunks if chunk.id != selected.id)]
        monkeypatch.setattr('app.services.explanation.paragraphs_for', lambda _paper: [{'source_text': selected.content + ' ' + ordered[1].content, 'anchors': [{'chunk_id': chunk.id} for chunk in ordered]}])
        result, _ = selection_context(paper, selected, 'LocalCorpus', 'paragraph')
        assert [chunk.id for chunk in result[:2]] == [selected.id, ordered[1].id]


def test_selection_question_can_opt_in_to_external_evidence(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.base import AnswerResult, VerifiedCitation
    from app.services.external_search import ExternalSnippet

    paper = card_paper(client)
    selected_chunk = next(chunk for chunk in paper['chunks'] if 'LocalCorpus' in chunk['content'])
    calls = {'count': 0}

    class ExternalProvider:
        name = 'ExternalFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask(self, question, chunks):
            calls['count'] += 1
            if calls['count'] <= 2:
                return AnswerResult('原文证据不足。', [], True)
            external = next(chunk for chunk in chunks if getattr(chunk, 'source_type', None) == 'external')
            return AnswerResult('外部资料补充了 EM 的定义。', [], False, [VerifiedCitation(external, external.content.split('\n', 1)[1], '外部资料补充了 EM 的定义。', 'external')])

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: ExternalProvider())
    monkeypatch.setattr('app.api.papers.search_external', lambda query: [ExternalSnippet('Exact Match', 'Exact Match\nExact match compares a predicted answer with the reference answer.', 'https://example.com/paper')])
    response = client.post(f"/api/papers/{paper['id']}/explain", json={'chunk_id': selected_chunk['id'], 'selected_text': 'LocalCorpus', 'question': 'EM 是什么？', 'allow_external': True})
    assert response.status_code == 200
    data = response.json()
    assert data['external_sources'] is True
    assert data['context_scope'] == 'external'
    assert calls['count'] == 3
    assert data['citations'][0]['source_type'] == 'external'
    assert data['citations'][0]['source_url'] == 'https://example.com/paper'


def test_auto_selection_question_escalates_to_full_paper_only_after_abstention(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.base import AnswerResult, VerifiedCitation

    paper = card_paper(client)
    selected_chunk = next(chunk for chunk in paper['chunks'] if 'LocalCorpus' in chunk['content'])
    seen: list[int] = []

    class EscalatingProvider:
        name = 'EscalatingFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask(self, question, chunks):
            seen.append(len(chunks))
            if len(seen) == 1:
                return AnswerResult('原文证据不足。', [], True)
            selected = next(chunk for chunk in chunks if chunk.id == selected_chunk['id'])
            return AnswerResult('全文中找到了答案。', [], False, [VerifiedCitation(selected, 'LocalCorpus', '全文中找到了答案。', 'llm_summary')])

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: EscalatingProvider())
    response = client.post(f"/api/papers/{paper['id']}/explain", json={'chunk_id': selected_chunk['id'], 'selected_text': 'LocalCorpus', 'question': '这个术语是什么？', 'context_scope': 'auto'})
    assert response.status_code == 200
    assert seen[1] > seen[0]
    assert response.json()['context_scope'] == 'full'


def test_selection_question_accepts_text_spanning_stored_chunks(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PDF text layer may split one visual selection at a column/page boundary."""
    from app.models import PaperChunk
    from app.providers.base import AnswerResult, VerifiedCitation

    paper = card_paper(client)
    with client.app.state.database.sessions() as session:
        session.add_all([
            PaperChunk(id='continuation-a', paper_id=paper['id'], page=8, section='3 Results', content='The model first reads the context before'),
            PaperChunk(id='continuation-b', paper_id=paper['id'], page=8, section='3 Results', content='it decides which memory operation to call.'),
        ])
        session.commit()
    seen = {}

    class RecordingProvider:
        name = 'SelectionFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask(self, question, chunks):
            seen['chunks'] = chunks
            selected = next(chunk for chunk in chunks if chunk.id == 'continuation-a')
            return AnswerResult('这是一个跨块选段。', [], False, [VerifiedCitation(selected, selected.content, '这是一个跨块选段。', 'llm_summary')])

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: RecordingProvider())
    response = client.post(f"/api/papers/{paper['id']}/explain", json={
        'chunk_id': 'continuation-a', 'selected_text': 'The model first reads the context before it decides which memory operation to call.',
        'question': '这段话在说什么？',
    })
    assert response.status_code == 200, response.text
    assert any(chunk.id == 'continuation-b' for chunk in seen['chunks'])


def test_visual_question_can_use_an_image_only_page(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.base import AnswerResult
    from app.models import PaperChunk

    paper = card_paper(client)
    with client.app.state.database.sessions() as session:
        session.query(PaperChunk).filter(PaperChunk.paper_id == paper['id']).delete()
        session.commit()
    seen = {}

    class VisionProvider:
        name = 'VisionFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask_with_image(self, question, chunks, image_data_url):
            seen.update(chunks=chunks, image=image_data_url)
            return AnswerResult('页面图像中没有可引用的文字，但图表显示了上升趋势。', [], False, [])

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: VisionProvider())
    response = client.post(f"/api/papers/{paper['id']}/explain", json={
        'page': 1, 'image_data_url': 'data:image/png;base64,ZmFrZQ==', 'question': '图表展示了什么？',
    })
    assert response.status_code == 200, response.text
    assert seen['chunks'] == []
    assert response.json()['visual_used'] is True


def test_mechanism_question_routes_related_sections_before_generation(client: TestClient) -> None:
    from app.services.explanation import selection_context
    from app.models import PaperChunk

    paper_data = card_paper(client)
    with client.app.state.database.sessions() as session:
        paper = session.get(Paper, paper_data['id'])
        assert paper is not None
        selected = PaperChunk(id='mechanism-anchor', paper_id=paper.id, page=3,
                              section='2.3 Function executor',
                              content='The output string is parsed and valid function arguments are executed.')
        later = PaperChunk(id='mechanism-followup', paper_id=paper.id, page=4,
                            section='2.4 Control flow and function chaining',
                            content='A yield waits for the next external event while a heartbeat requests immediate follow-up inference.')
        paper.chunks.extend([selected, later])
        session.commit()
        result, scope = selection_context(
            paper, selected, selected.content,
            scope='auto',
            question='模型输出什么时候作为 function 参数解析，什么时候作为普通文字返回用户？',
        )
        assert scope == 'related'
        assert [chunk.id for chunk in result][:2] == ['mechanism-anchor', 'mechanism-followup']
        visual_result, visual_scope = selection_context(
            paper, selected, selected.content,
            scope='auto',
            question='模型输出什么时候作为 function 参数解析，什么时候作为普通文字返回用户？',
            visual=True,
        )
        assert visual_scope == 'related'
        assert visual_result.index(later) < 5


def test_model_requested_context_expansion_runs_once_and_returns_final_answer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.base import AnswerResult, VerifiedCitation
    from app.models import PaperChunk

    paper = card_paper(client)
    selected_data = next(chunk for chunk in paper['chunks'] if 'LocalCorpus' in chunk['content'])
    selected = PaperChunk(id=selected_data['id'], paper_id=paper['id'], page=selected_data['page'],
                          section=selected_data['section'], content=selected_data['content'],
                          bbox_json=None)
    seen: list[int] = []

    class ExpandingProvider:
        name = 'ExpandingFixture'
        mode = 'remote'
        configured = True
        translation_available = True

        def ask(self, question, chunks):
            seen.append(len(chunks))
            if len(seen) == 1:
                return AnswerResult('当前段落还不够。', [], False,
                                    [VerifiedCitation(selected, 'LocalCorpus', '当前段落还不够。', 'llm_summary')],
                                    needs_more_context=True)
            return AnswerResult('全文补充后可以确定。', [], False,
                                [VerifiedCitation(selected, 'LocalCorpus', '全文补充后可以确定。', 'llm_summary')])

    monkeypatch.setattr('app.api.papers.get_model_provider', lambda: ExpandingProvider())
    response = client.post(f"/api/papers/{paper['id']}/explain", json={
        'chunk_id': selected.id, 'selected_text': 'LocalCorpus',
        'question': '这个术语在全文中承担什么作用？',
    })
    assert response.status_code == 200, response.text
    assert seen[1] > seen[0]
    assert response.json()['answer'] == '全文补充后可以确定。'
    assert response.json()['context_scope'] == 'full'
    assert response.json()['needs_more_context'] is False
