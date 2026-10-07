from app.models import PaperChunk
from app.providers.mock import MockProvider


def test_scientific_method_and_results_headings_produce_verbatim_cards():
    method = PaperChunk(id='architecture-source', paper_id='real-layout', page=2,
                        section='3 Model Architecture',
                        content='The Transformer follows this overall architecture using stacked self-attention and point-wise, fully connected layers for both the encoder and decoder.')
    results = PaperChunk(id='experiment-source', paper_id='real-layout', page=7,
                         section='6 Experiments',
                         content='On the WMT 2014 English-to-German translation task, the big transformer model outperforms the best previously reported models.')
    result = MockProvider().analyze([method, results])
    assert result.method == method.content
    assert result.findings == results.content
    assert result.card['method'].citations[0].chunk.id == method.id
    assert result.card['main_results'].citations[0].source_text in results.content


def test_numbered_subsection_retains_parent_results_context():
    heading = PaperChunk(id='results-heading', paper_id='attention-layout', page=7,
                        section='6 Results', content='6\nResults')
    result_source = PaperChunk(id='translation-results', paper_id='attention-layout', page=7,
                              section='6.1 Machine Translation',
                              content='On the English-to-German translation task, the model improves over the strongest previously reported systems.')
    unrelated = PaperChunk(id='references', paper_id='attention-layout', page=9,
                          section='References', content='Prior translation systems and their published scores are listed in the bibliography.')
    result = MockProvider().analyze([heading, result_source, unrelated])
    assert result.findings == result_source.content
    assert result.card['main_results'].citations[0].chunk.id == result_source.id
    answer = MockProvider().ask('论文的结果是什么？', [heading, result_source, unrelated])
    assert not answer.insufficient_evidence
    assert [chunk.id for chunk in answer.chunks] == [result_source.id]


def test_chinese_method_question_finds_architecture_source_without_inference():
    source = PaperChunk(id='architecture-source', paper_id='real-layout', page=2,
                        section='3 Model Architecture',
                        content='The Transformer follows this overall architecture using stacked self-attention and point-wise, fully connected layers for both the encoder and decoder.')
    result = MockProvider().ask('论文的方法是什么？', [source])
    assert not result.insufficient_evidence
    assert source.content in result.answer
    assert result.chunks[0].id == source.id


def test_split_section_headers_are_not_selected_as_scientific_evidence():
    header = PaperChunk(id='header', paper_id='bert-layout', page=2,
                       section='2.2 Unsupervised Fine-tuning Approaches',
                       content='2.2\nUnsupervised Fine-tuning Approaches')
    background = PaperChunk(id='background', paper_id='bert-layout', page=2,
                           section=header.section,
                           content='Prior work learns contextual representations from unlabeled text for transfer to downstream tasks.')
    method = PaperChunk(id='method', paper_id='bert-layout', page=3,
                       section='3.1 Pre-training',
                       content='3.1\nPre-training\nWe train the model with masked token prediction and a sentence relationship objective.')
    result = MockProvider().analyze([header, background, method])
    assert result.method == 'We train the model with masked token prediction and a sentence relationship objective.'
    assert all(c.id != header.id for c in result.evidence_chunks)
    assert result.card['method'].citations[0].chunk.id == method.id
