from app.models import PaperChunk
from app.providers.harness import SourcePart, _card, analyze_full_paper
from app.db import Database
from app.providers.base import ProviderError


def test_synthesized_knowledge_candidates_are_source_scoped():
    chunk = PaperChunk(id='c', paper_id='p', page=2, section='Introduction', content='ReAct evaluates on HotpotQA.')
    part = SourcePart('c:0:31', 'c', 0, len(chunk.content), 2, 'Introduction', chunk.content)
    facts = [{'id': 'fact-1', 'content': '实验使用 HotpotQA。', 'section': 'Introduction', 'citations': [{'part_id': part.part_id, 'chunk_id': 'c', 'source_text': 'ReAct evaluates on HotpotQA.', 'start': 0, 'end': len(chunk.content)}], 'citation_ids': ['E00001'], 'source_fact_ids': ['fact-1']}]
    pool = {'E00001': {'part_id': part.part_id, 'chunk_id': 'c', 'source_text': chunk.content, 'section': 'Introduction', 'start': 0, 'end': len(chunk.content)}}
    entry = {'content': 'ReAct', 'citation_ids': ['E00001']}
    data = {'card': {'one_sentence_summary': entry, 'tldr': [entry, entry, entry]}, 'knowledge_candidates': [{'entity_type': 'dataset', 'name': 'HotpotQA', 'role': 'used', 'confidence': .95, 'description': '评测数据集', 'citation_ids': ['E00001']}], 'knowledge_relations': []}
    result, invalid = _card(data, facts, {part.part_id: part}, [chunk], 'test-model', 'test-prompt', pool)
    assert invalid == 0
    assert result.knowledge_candidates[0].name == 'HotpotQA'
    assert result.knowledge_candidates[0].citations[0].source_text == chunk.content


def test_invalid_knowledge_citation_is_rejected():
    chunk = PaperChunk(id='c', paper_id='p', page=2, section='Introduction', content='ReAct evaluates on HotpotQA.')
    part = SourcePart('c:0:31', 'c', 0, len(chunk.content), 2, 'Introduction', chunk.content)
    facts = [{'id': 'fact-1', 'content': '实验使用 HotpotQA。', 'section': 'Introduction', 'citations': [{'part_id': part.part_id, 'chunk_id': 'c', 'source_text': chunk.content, 'start': 0, 'end': len(chunk.content)}], 'citation_ids': ['E00001'], 'source_fact_ids': ['fact-1']}]
    pool = {'E00001': {'part_id': part.part_id, 'chunk_id': 'c', 'source_text': chunk.content, 'section': 'Introduction', 'start': 0, 'end': len(chunk.content)}}
    data = {'card': {'one_sentence_summary': {'content': 'ReAct', 'citation_ids': ['E00001']}}, 'knowledge_candidates': [{'entity_type': 'dataset', 'name': 'HotpotQA', 'role': 'used', 'confidence': .95, 'citation_ids': ['missing']}], 'knowledge_relations': []}
    result, _ = _card(data, facts, {part.part_id: part}, [chunk], 'test-model', 'test-prompt', pool)
    assert result.knowledge_candidates == []


def test_missing_knowledge_fields_trigger_a_bounded_intake_call(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'knowledge.db').as_posix()}")
    database.migrate()
    chunk = PaperChunk(id='c', paper_id='p', page=2, section='Introduction', content='ReAct evaluates on HotpotQA.')

    class Provider:
        name = 'KnowledgeFallbackProvider'
        model = 'knowledge-model'
        reasoning_effort = 'high'
        response_model = model
        last_usage = {}

        def __init__(self):
            self.calls = []

        def complete_json(self, system, payload, **options):
            self.calls.append((payload, options))
            if 'chunks' in payload:
                source = payload['chunks'][0]
                return {'facts': [{'content': 'The paper evaluates a method on a QA dataset.', 'source_ids': [source['source_id']]}]}
            if payload.get('stage') == 'knowledge_intake':
                citation_id = payload['facts'][0]['citation_ids'][0]
                return {'knowledge_candidates': [{'entity_type': 'dataset', 'name': 'HotpotQA', 'role': 'used', 'confidence': .95, 'description': 'QA benchmark', 'citation_ids': [citation_id]}], 'knowledge_relations': []}
            if payload.get('stage') == 'review_card_science':
                items = [{'field': item['field'], 'decision': 'supported'} for item in payload['items']]
                if items:
                    first = payload['items'][0]
                    items[0] = {'field': first['field'], 'decision': 'corrected',
                        'value': {'content': first['content'], 'citation_ids': first['citation_ids']}}
                return {'items': items}
            citation_id = payload['facts'][0]['citation_ids'][0]
            return {'card': {'one_sentence_summary': {'content': 'ReAct evaluates on HotpotQA.', 'citation_ids': [citation_id]}, 'tldr': [{'content': 'ReAct evaluates on HotpotQA.', 'citation_ids': [citation_id]}] * 3}}

    provider = Provider()
    result = analyze_full_paper(database, provider, [chunk])

    assert [item.name for item in result.analysis.knowledge_candidates] == ['HotpotQA']
    assert any(payload.get('stage') == 'knowledge_intake' for payload, _ in provider.calls)
    assert result.report['knowledge_fallback']['triggered'] is True
