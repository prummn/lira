"""Original Self-RAG review lost its late table headers to unrelated early prose."""
from collections import defaultdict
import json
from pathlib import Path

from app.models import PaperChunk
from app.providers.base import AnalysisResult, CardEntry, VerifiedCitation
from app.providers.harness import SourcePart, pack_windows, source_passages
from app.providers.science_review import encoded, prepare_reviews


def test_real_self_rag_table_header_comparator_and_caption_survive_bounded_context():
    frozen = json.loads((Path(__file__).parent / 'fixtures/self_review_context.json').read_text('utf-8'))
    parts = {item['part_id']: SourcePart(**item) for item in frozen['source_parts']}
    originals = defaultdict(list)
    for part in parts.values():
        originals[part.chunk_id].append(part)
    chunks = {key: PaperChunk(id=key, paper_id='self-rag', page=values[0].page,
        section=values[0].section, content=''.join(part.content for part in sorted(values, key=lambda part: part.start)))
        for key, values in originals.items()}
    card = {}
    for item in frozen['entries']:
        citations = [VerifiedCitation(chunks[parts[cite['part_id']].chunk_id],
            cite['source_text'], item['content'], 'llm_summary') for cite in item['citations']]
        entry = CardEntry(item['content'], citations, item['section'])
        if item['field'] in ('tldr', 'section_summaries', 'ablation_findings'):
            card.setdefault(item['field'], []).append(entry)
        else:
            card[item['field']] = entry
    batch = prepare_reviews(AnalysisResult(card=card), parts)[0][0]
    texts = [source['source_text'] for source in batch.payload['sources']]
    assert any('Short-form\nClosed-set' in text and '(pre)' in text for text in texts)
    assert any('Table 2: Overall experiment results' in text for text in texts)
    assert any('Ret-ChatGPT\n50.8\n65.7' in text for text in texts)
    assert any('a larger weight results in lower MAUVE scores' in text for text in texts)
    assert len(encoded(batch.payload)) <= 36000
    assert all(any(source['source_text'] in part.content for part in parts.values())
               for source in batch.payload['sources'])


def test_early_prose_does_not_starve_a_later_cited_table_or_page_continuation():
    chunks = [PaperChunk(id=f'early-{index:03d}', paper_id='paper', page=1, section='Introduction',
                        content='Unrelated introductory prose. ' * 12) for index in range(100)]
    result = PaperChunk(id='late-03', paper_id='paper', page=8, section='Results',
                        content='Ours 71; Baseline 66. Citation precision improves.')
    header = PaperChunk(id='late-02', paper_id='paper', page=8, section='Results',
                        content='Table 2. Dataset: ASQA; model: 7B; metric: citation precision.\n'
                        + 'The fixed experimental scope must be retained. ' * 8)
    continuation = PaperChunk(id='next-01', paper_id='paper', page=9, section='Results',
                              content='However, a larger weight reduces MAUVE scores.\n'
                              + 'This negative finding qualifies the preceding observation. ' * 8)
    chunks.extend([header, result, continuation])
    parts = {part.part_id: part for window in pack_windows(chunks) for part in source_passages(window).values()}
    entries = [CardEntry('Overview.', [VerifiedCitation(chunks[0], chunks[0].content, '', 'llm_summary')]),
               CardEntry('Precision improves.', [VerifiedCitation(result, result.content, '', 'llm_summary')])]
    batch = prepare_reviews(AnalysisResult(card={'one_sentence_summary': entries[0], 'main_results': entries[1]}),
                            parts, max_payload_chars=5000)[0][0]
    texts = [source['source_text'] for source in batch.payload['sources']]
    assert header.content in texts
    assert continuation.content in texts
    assert len(encoded(batch.payload)) <= 5000


def test_non_numeric_section_summary_still_requires_scientific_section_review():
    chunk = PaperChunk(id='ethics', paper_id='paper', page=11, section='Conclusion',
                       content='ETHICAL CONCERNS\nGenerated claims may not have full citation support.')
    parts = {part.part_id: part for window in pack_windows([chunk]) for part in source_passages(window).values()}
    entry = CardEntry('总结事实性改善并建议用户核查错误。',
                     [VerifiedCitation(chunk, chunk.content, '', 'llm_summary')], 'Conclusion')
    batches, report = prepare_reviews(AnalysisResult(card={'section_summaries': [entry]}), parts)
    assert report['scheduled_items'] == 1
    assert batches[0].payload['items'][0]['field'] == 'section_summaries[0]'


def test_review_request_exposes_the_citation_limit_that_rejected_a_real_thirteen_id_reply():
    chunk = PaperChunk(id='result', paper_id='paper', page=7, section='Results',
                       content='A source supporting the reported result.')
    parts = {part.part_id: part for window in pack_windows([chunk]) for part in source_passages(window).values()}
    entry = CardEntry('A reported result.', [VerifiedCitation(chunk, chunk.content, '', 'llm_summary')])
    batch = prepare_reviews(AnalysisResult(card={'main_results': entry}), parts)[0][0]
    assert batch.payload.get('limits') == {
        'max_citation_ids': 10, 'max_citation_chars': 8000, 'max_content_chars': 8000}
