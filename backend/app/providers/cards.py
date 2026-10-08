"""Complete Paper Card keys and conservative, verbatim extraction by source section."""
from __future__ import annotations
import re
from ..models import PaperChunk
from .base import AnalysisResult, CardEntry, VerifiedCitation
from .validation import chunk_body

SINGLE_FIELDS = ('one_sentence_summary','problem','motivation','background','core_idea','method','main_results','limitations','abstract_zh','abstract_en')
LIST_FIELDS = ('contributions','datasets','metrics','baselines','ablation_findings','future_work','claims','related_methods','prerequisite_concepts','section_summaries','tldr')
CARD_ALIASES = {'one_sentence_summary':'one_liner','main_results':'findings'}
CARD_LIMITS = {'max_citation_ids': 10, 'max_citation_chars': 8000, 'max_content_chars': 8000}


def field_schema(field: str, *, indexed: bool = False) -> dict:
    """Describe the same cardinality/limits enforced by the local validator."""
    entry = {'type': 'object', 'required': ['content', 'citation_ids'],
        'properties': {
            'content': {'type': 'string', 'minLength': 1, 'maxLength': CARD_LIMITS['max_content_chars']},
            'citation_ids': {'type': 'array', 'minItems': 1,
                'maxItems': CARD_LIMITS['max_citation_ids'], 'uniqueItems': True,
                'items': {'type': 'string'}}}}
    if field == 'section_summaries':
        entry['required'].append('section')
        entry['properties']['section'] = {'type': ['string', 'null'],
            'description': 'Exact shared source section of all citation_ids; never infer a heading.'}
    if field in SINGLE_FIELDS or indexed:
        return entry
    return {'type': 'array', 'items': entry,
        'minItems': 3 if field == 'tldr' else 1,
        'maxItems': 5 if field == 'tldr' else 100}


def card_schema() -> dict:
    properties = {field: {'anyOf': [field_schema(field), {'type': 'null'}]}
                  for field in SINGLE_FIELDS}
    for field in LIST_FIELDS:
        schema = field_schema(field)
        properties[field] = {'anyOf': [schema, {'type': 'array', 'maxItems': 0}]} if field == 'tldr' else {**schema, 'minItems': 0}
    return {'type': 'object', 'properties': properties}


def extractive_card(chunks: list[PaperChunk], analysis: AnalysisResult) -> dict[str, CardEntry | list[CardEntry] | None]:
    useful = [chunk for chunk in chunks if len(chunk_body(chunk)) > 30]
    card: dict[str,CardEntry | list[CardEntry] | None] = {field:None for field in SINGLE_FIELDS}
    card.update({field:[] for field in LIST_FIELDS})
    def entry(chunk: PaperChunk) -> CardEntry:
        content = chunk_body(chunk)
        return CardEntry(content,[VerifiedCitation(chunk,content,content,'explicit')],chunk.section)
    for card_field,analysis_field in (('one_sentence_summary','one_liner'),('problem','problem'),('method','method'),('main_results','findings'),('limitations','limitations')):
        content = getattr(analysis,analysis_field)
        source = next((chunk for chunk in useful if chunk_body(chunk) == content),None)
        if source:
            card[card_field] = entry(source)
    singles = {'motivation':('motivation','动机'),'background':('background','背景'),'core_idea':('core idea','核心思路')}
    lists = {'contributions':('contribution','贡献'),'datasets':('dataset','数据集'),'metrics':('metric','评估指标'),'baselines':('baseline','基线'),'ablation_findings':('ablation','消融'),'future_work':('future work','未来工作'),'claims':('claims','主张'),'related_methods':('related method','related work'),'prerequisite_concepts':('prerequisite','前置知识')}
    for field,terms in singles.items():
        source = next((chunk for chunk in useful if any(term in (chunk.section or '').casefold() for term in terms)),None)
        if source:
            card[field] = entry(source)
    for field,terms in lists.items():
        card[field] = [entry(chunk) for chunk in useful if any(term in (chunk.section or '').casefold() for term in terms)]
    abstract = next((chunk for chunk in useful if any(term in (chunk.section or '').casefold() for term in ('abstract','摘要'))),None)
    if abstract:
        content = chunk_body(abstract)
        chinese = len(re.findall(r'[\u3400-\u9fff]',content))
        latin = len(re.findall(r'[a-zA-Z]',content))
        card['abstract_zh' if chinese > latin else 'abstract_en'] = entry(abstract)
    card['section_summaries'] = [entry(chunk) for chunk in useful if chunk.section and 'references' not in chunk.section.casefold()]
    highlights: list[CardEntry] = []
    for field in ('one_sentence_summary','problem','method','main_results','limitations','core_idea','motivation'):
        item = card[field]
        if isinstance(item,CardEntry) and not any(previous.content == item.content for previous in highlights):
            highlights.append(item)
    card['tldr'] = highlights[:5] if len(highlights) >= 3 else []
    return card
