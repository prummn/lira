"""A citation formatting failure must not masquerade as missing paper evidence."""
import pytest

from app.models import PaperChunk
from app.providers.base import ProviderError
from app.providers.openai_compatible import OpenAICompatibleProvider


def answer_provider(monkeypatch, quote, *, insufficient=False, visual=False):
    provider = OpenAICompatibleProvider(api_key='test')
    monkeypatch.setattr(provider, '_answer_json', lambda *args: {
        'answer': ('这里没有报告环境构建耗时，因此无法比较耗时。' if insufficient else
                   '先从任务出发，或先建立可复用环境，这是两种不同的收集顺序。'),
        'insufficient_evidence': insufficient,
        'citations': [] if insufficient else [{'chunk_id': 'source', 'source_text': quote}],
        'unknowns': ['这里没有报告环境构建耗时。'], 'needs_more_context': insufficient,
    })
    return provider


SOURCE = ('SWE-bench identifies task instances first. It builds an environment for each. '
          'SWE-smith defines an environment first, then synthesizes many tasks within it.')


@pytest.mark.parametrize('visual', [False, True])
@pytest.mark.parametrize('ellipsis', [' ... ', ' […] ', ' … '])
def test_elided_answer_quote_recovers_a_contiguous_original_span(monkeypatch, visual, ellipsis):
    quote = 'SWE-bench identifies task instances first.' + ellipsis + 'SWE-smith defines an environment first,'
    provider = answer_provider(monkeypatch, quote)
    chunk = PaperChunk(id='source', paper_id='paper', page=3, content=SOURCE)
    result = (provider.ask_with_image('两种流程有什么区别？', [chunk], 'image') if visual
              else provider.ask('两种流程有什么区别？', [chunk]))
    assert not result.insufficient_evidence
    assert len(result.citations) == 1
    assert result.citations[0].source_text in SOURCE
    assert 'It builds an environment for each.' in result.citations[0].source_text


@pytest.mark.parametrize('quote', [
    'SWE-bench identifies task instances first. ... It invents an unavailable environment.',
    'SWE-smith defines an environment first, ... SWE-bench identifies task instances first.',
    'SWE-bench ... tasks',
])
def test_fabricated_reversed_or_tiny_excerpt_does_not_become_verified(monkeypatch, quote):
    provider = answer_provider(monkeypatch, quote)
    with pytest.raises(ProviderError) as error:
        provider.ask('两种流程有什么区别？', [PaperChunk(id='source', content=SOURCE)])
    assert error.value.code == 'invalid_response'
    assert '引文' in str(error.value)


def test_real_missing_context_retains_the_models_specific_explanation(monkeypatch):
    provider = answer_provider(monkeypatch, '', insufficient=True)
    result = provider.ask('环境构建耗时多少？', [PaperChunk(id='source', content=SOURCE)])
    assert result.insufficient_evidence
    assert result.answer.startswith('这里没有报告环境构建耗时')
    assert result.unknowns == ['这里没有报告环境构建耗时。']
    assert result.needs_more_context


def test_analysis_citations_keep_the_original_strict_contract():
    chunk = PaperChunk(id='source', content=SOURCE)
    quote = 'SWE-bench identifies task instances first. ... SWE-smith defines an environment first,'
    citations, valid = OpenAICompatibleProvider._citations(
        [{'chunk_id': 'source', 'source_text': quote}], {'source': SOURCE}, {'source': chunk}, 'claim')
    assert not valid and not citations


@pytest.mark.parametrize('other_block', [False, True])
def test_elisions_cannot_reach_unseen_text_or_another_source(monkeypatch, other_block):
    first = 'SWE-bench identifies task instances first.'
    last = 'SWE-smith defines an environment first,'
    provider = answer_provider(monkeypatch, first + ' ... ' + last)
    chunks = ([PaperChunk(id='source', content=first), PaperChunk(id='other', content=last)]
              if other_block else [PaperChunk(id='source', content=first + ' filler' * 700 + last)])
    with pytest.raises(ProviderError) as error:
        provider.ask('两种流程有什么区别？', chunks)
    assert error.value.code == 'invalid_response'
