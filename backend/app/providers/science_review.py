"""Bounded review of scientific scope using immutable local original passages.

This helper is deliberately independent of transport and task persistence. A
model decision is evidence for a second pass, never a proof of scientific truth.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
import json
import re

from .base import AnalysisResult, ProviderError
from .cards import CARD_LIMITS
from .validation import canonical_quote

MAX_BATCHES = 4
MAX_ITEMS = 12
MAX_PAYLOAD_CHARS = 36000
RISK = re.compile(r'\d|\b[A-Z][A-Z0-9_]{1,}\b|优于|低于|超过|显著|全部|所有|仅|只有|不能|三[个级种]|提升|降低|提高|(?i:\b(?:only|all|outperforms?|significantly|better|worse|improves?)\b)')
SOURCE_SCOPE = re.compile(r'\bonly (?:consider|include|use|when|if)\b|possible explanation|\bsubset\b|single run|we hypothesi[sz]e|we speculate', re.I)
OVERVIEW = ('one_sentence_summary', 'main_results', 'limitations', 'tldr')
DETAILS = ('method', 'ablation_findings', 'section_summaries', 'claims', 'abstract_zh', 'abstract_en')
CAPTION = re.compile(r'^\s*(?:Table|Figure|Fig\.?|表|图)\s*\d+[.:：\s]', re.I)


@dataclass(frozen=True)
class ReviewBatch:
    payload: dict
    sources: dict[str, dict]


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _entries(analysis):
    for field, values in analysis.card.items():
        if isinstance(values, list):
            for index, entry in enumerate(values):
                yield f'{field}[{index}]', field, entry
        elif values:
            yield field, field, values


def _source(citation, parts):
    for part in parts.values():
        if part.chunk_id == citation.chunk.id:
            quote = canonical_quote(part.content, citation.source_text)
            if quote is not None:
                return part, quote
    raise ProviderError('科学复核无法定位原始引用，已有结果已保留')


def serialize_card(analysis, parts) -> dict:
    card = {}
    def serialize(entry, section_summary):
        citations = []
        for cite in entry.citations:
            part, quote = _source(cite, parts)
            citations.append({'part_id': part.part_id, 'chunk_id': part.chunk_id, 'source_text': quote})
        value = {'content': entry.content, 'citations': citations}
        if section_summary:
            value['section'] = entry.section
        return value
    for field, values in analysis.card.items():
        card[field] = ([serialize(value, field == 'section_summaries') for value in values]
                       if isinstance(values, list) else serialize(values, False) if values else None)
    return {'card': card, 'concepts': analysis.concepts}


def _context_order(catalog, anchors, pages, context_pages):
    """Distribute context across source pages, close to citations and table captions."""
    groups = defaultdict(list)
    for part in catalog:
        if part.page in context_pages:
            groups[part.page].append(part)
    queues = []
    for page in sorted(groups, key=lambda value: (value not in pages, value)):
        group = groups[page]
        cited_positions = {index for index, part in enumerate(group) if part.part_id in anchors}
        captions = {index for index, part in enumerate(group) if CAPTION.match(part.content)}
        seeds = cited_positions | captions
        for position in cited_positions:
            nearest = min(captions, key=lambda index: (abs(index - position), index), default=None)
            if nearest is not None and abs(nearest - position) <= 8:
                # Include the actual interval between a caption and its cited
                # row before unrelated prose; headers/comparators live there.
                seeds.update(range(min(nearest, position), max(nearest, position) + 1))
        if page - 1 in pages:
            seeds.add(0)
        if page + 1 in pages:
            seeds.add(len(group) - 1)
        if not seeds:
            seeds.add(0)
        queues.append(sorted(((index, part) for index, part in enumerate(group) if part.part_id not in anchors),
            key=lambda item: (min(abs(item[0] - seed) for seed in seeds), item[0])))
    for offset in range(max((len(queue) for queue in queues), default=0)):
        for queue in queues:
            if offset < len(queue):
                yield queue[offset][1]


def prepare_reviews(analysis, parts, *, max_batches=MAX_BATCHES, max_items=MAX_ITEMS,
                    max_payload_chars=MAX_PAYLOAD_CHARS):
    if not 1 <= max_batches <= MAX_BATCHES or not 1 <= max_items <= MAX_ITEMS or max_payload_chars < 1000:
        raise ValueError('Invalid scientific-review limits')
    max_payload_chars = min(max_payload_chars, MAX_PAYLOAD_CHARS)
    entries = list(_entries(analysis))
    selected = [item for field in OVERVIEW for item in entries if item[1] == field]
    details = [item for field in DETAILS for item in entries
               if item[1] == field and (field in ('ablation_findings', 'section_summaries') or RISK.search(item[2].content)
                    or any(SOURCE_SCOPE.search(cite.source_text) for cite in item[2].citations))]
    # A late confidence-analysis restriction or conjecture must not lose its
    # turn merely because earlier sections contain many routine metric values.
    details.sort(key=lambda item: not any(SOURCE_SCOPE.search(cite.source_text) for cite in item[2].citations))
    selected += details
    catalog = sorted(parts.values(), key=lambda part: (part.page or 0, part.chunk_id, part.start))
    ids = {part.part_id: f'R{index:05d}' for index, part in enumerate(catalog, 1)}
    sources = {ids[part.part_id]: {'part_id': part.part_id, 'chunk_id': part.chunk_id,
        'source_text': part.content, 'start': part.start, 'end': part.end,
        'section': part.section, 'page': part.page} for part in catalog}
    quote_ids = {}
    parent_ids = {}
    def citation_id(citation):
        part, quote = _source(citation, parts)
        parent = ids[part.part_id]
        if quote == part.content:
            return parent
        key = (part.part_id, quote)
        if key not in quote_ids:
            sid = f'R{len(sources) + 1:05d}'
            start = part.start + part.content.index(quote)
            sources[sid] = {**sources[parent], 'source_text': quote,
                            'start': start, 'end': start + len(quote)}
            quote_ids[key] = sid
            parent_ids[sid] = parent
        return quote_ids[key]
    def source_payload(sid):
        return {'id': sid, 'source_text': sources[sid]['source_text'],
                'section': sources[sid]['section'], 'page': sources[sid]['page']}
    batches, position, partial = [], 0, False
    while position < len(selected) and len(batches) < max_batches:
        items, cited = [], set()
        while position < len(selected) and len(items) < max_items:
            path, field, entry = selected[position]
            refs = list(dict.fromkeys(citation_id(cite) for cite in entry.citations))
            item = {'field': path, 'content': entry.content, 'citation_ids': refs}
            if field == 'section_summaries': item['section'] = entry.section
            candidate_ids = cited | set(refs)
            candidate = {'stage': 'review_card_science', 'limits': dict(CARD_LIMITS), 'items': [*items, item],
                'sources': [source_payload(sid) for sid in sorted(candidate_ids)]}
            if len(encoded(candidate)) > max_payload_chars:
                break
            items.append(item)
            cited = candidate_ids
            position += 1
        if not items:
            # An oversized slot is deferred, never silently declared supported.
            break
        pages = {sources[sid]['page'] for sid in cited if sources[sid]['page'] is not None}
        context_pages = pages | {neighbor for page in pages for neighbor in (page - 1, page + 1)
                                 if neighbor > 0}
        payload = {'stage': 'review_card_science', 'limits': dict(CARD_LIMITS), 'items': items,
                   'sources': [source_payload(sid) for sid in sorted(cited)]}
        included = set(cited)
        # Include the containing passages before other same-page context.
        # citation_ids still identify only the exact old quotes, so a header or
        # comparator in this extra context must be cited by a correction.
        parents = {parent_ids[sid] for sid in cited if sid in parent_ids}
        anchors = {sources[sid]['part_id'] for sid in cited}
        ordered = [part for part in catalog if ids[part.part_id] in parents]
        ordered.extend(_context_order(catalog, anchors, pages, context_pages))
        for part in ordered:
            sid = ids[part.part_id]
            if part.page not in context_pages or sid in included:
                continue
            candidate = {**payload, 'sources': [*payload['sources'], source_payload(sid)]}
            if len(encoded(candidate)) <= max_payload_chars:
                payload = candidate
                included.add(sid)
            else:
                partial = True
        batches.append(ReviewBatch(payload, {sid: sources[sid] for sid in included}))
    scheduled = sum(len(batch.payload['items']) for batch in batches)
    return batches, {'scope': 'overview_sections_and_risky_claims', 'candidate_items': len(selected),
        'scheduled_items': scheduled, 'deferred_items': len(selected) - scheduled,
        'unreviewed_card_entries': len(entries) - scheduled, 'context_partial': partial,
        'batches': len(batches), 'scientific_correctness_proven': False}


def _get(raw, path):
    match = re.fullmatch(r'([a-z_]+)(?:\[(\d+)\])?', path)
    field, index = match[1], match[2]
    values = raw['card'][field]
    return values[int(index)] if index is not None else values


def _set(raw, path, value):
    match = re.fullmatch(r'([a-z_]+)(?:\[(\d+)\])?', path)
    field, index = match[1], match[2]
    if index is None: raw['card'][field] = value
    else: raw['card'][field][int(index)] = value


def apply_review(raw, batch, response, validate):
    """Accept only explicit, unique decisions with locally valid originals."""
    patched = deepcopy(raw)
    supplied = response.get('items') if isinstance(response, dict) else None
    supplied = supplied if isinstance(supplied, list) and len(supplied) <= MAX_ITEMS * 2 else []
    counts = Counter(item.get('field') for item in supplied
                     if isinstance(item, dict) and isinstance(item.get('field'), str))
    replies = {item['field']: item for item in supplied
               if isinstance(item, dict) and isinstance(item.get('field'), str)}
    result = {'supported_fields': [], 'corrected_fields': [], 'rejected_fields': [],
              'checked_fields': [], 'rejection_reasons': {}}
    for item in batch.payload['items']:
        path = item['field']
        reply = replies.get(path) if counts[path] == 1 else None
        if reply and reply.get('decision') == 'supported' and 'value' not in reply:
            result['supported_fields'].append(path)
            result['checked_fields'].append(path)
            continue
        value = reply.get('value') if reply and reply.get('decision') == 'corrected' else None
        content = value.get('content') if isinstance(value, dict) else None
        refs = value.get('citation_ids') if isinstance(value, dict) else None
        valid = (isinstance(content, str) and 1 <= len(content.strip()) <= CARD_LIMITS['max_content_chars']
            and isinstance(refs, list) and 1 <= len(refs) <= CARD_LIMITS['max_citation_ids']
            and all(isinstance(sid, str) and sid in batch.sources for sid in refs))
        if valid:
            sources = [batch.sources[sid] for sid in dict.fromkeys(refs)]
            mapped = {'content': content.strip(), 'citations': [
                {key: source[key] for key in ('part_id', 'chunk_id', 'source_text')} for source in sources]}
            if path.startswith('section_summaries['):
                mapped['section'] = value.get('section')
                valid = isinstance(mapped['section'], str) and all(source['section'] == mapped['section'] for source in sources)
            if valid:
                try:
                    valid = validate(path, mapped, sources)
                except ProviderError:
                    valid = False
            if valid:
                _set(patched, path, mapped)
                result['corrected_fields'].append(path)
                result['checked_fields'].append(path)
                continue
        _set(patched, path, None)
        result['rejected_fields'].append(path)
        explicit = reply is not None and reply.get('decision') == 'unsupported' and 'value' not in reply
        result['rejection_reasons'][path] = 'science_support' if explicit else 'science_review_format'
        if explicit: result['checked_fields'].append(path)
    return patched, result


def run_science_review(analysis, parts, call, validate):
    """Run bounded review stages; transport/cancellation/usage belong to caller.

    validate(raw, sources) returns the normally validated card and invalid
    count, adding only this batch's immutable originals to its allowed scope.
    A provider error leaves a visible pending review and preserves usable data.
    """
    batches, report = prepare_reviews(analysis, parts)
    report.update(checked_items=0, corrected_items=0, rejected_items=0,
                  pending_items=0, card_invalid_entries=0, cardinality_drops=[], results=[], invalid_response_batches=[])
    raw = serialize_card(analysis, parts)
    allowed = {}
    changed = False
    for index, batch in enumerate(batches):
        try:
            response = call(batch.payload)
        except ProviderError as error:
            report['pending_items'] = sum(len(item.payload['items']) for item in batches[index:])
            report['failure_code'] = error.code
            break
        def validate_entry(path, value, sources):
            field = path.split('[', 1)[0]
            candidate_field = 'claims' if field == 'tldr' and '[' in path else field
            candidate = {candidate_field: [value] if '[' in path else value}
            result, invalid = validate(candidate, sources)
            return invalid == 0 and bool(result.card.get(candidate_field))
        raw, result = apply_review(raw, batch, response, validate_entry)
        allowed.update(batch.sources)
        report['results'].append(result)
        report['checked_items'] += len(result['checked_fields'])
        report['corrected_items'] += len(result['corrected_fields'])
        report['rejected_items'] += len(result['rejected_fields'])
        if any(reason == 'science_review_format' for reason in result['rejection_reasons'].values()):
            report['invalid_response_batches'].append(index)
        changed |= bool(result['corrected_fields'] or result['rejected_fields'])
    if changed:
        tldr = raw.get('card', {}).get('tldr')
        surviving = sum(item is not None for item in tldr) if isinstance(tldr, list) else 0
        deleted_tldr = any(path.startswith('tldr[') and reason == 'science_support'
            for outcome in report['results'] for path, reason in outcome['rejection_reasons'].items())
        try:
            analysis, report['card_invalid_entries'] = validate(raw, list(allowed.values()))
        except ProviderError:
            # No original rejected claim is resurrected to avoid an empty card.
            # The task layer must publish these diagnostics then retain any
            # previous durable card instead of publishing this empty result.
            report['card_invalid_entries'] = surviving if 0 < surviving < 3 else 0
            report['no_supported_card'] = True
            analysis = AnalysisResult(model_version=analysis.model_version,
                prompt_version=analysis.prompt_version, concepts=list(analysis.concepts))
            analysis.card = {field: [] if isinstance(value, list) else None
                             for field, value in raw['card'].items()}
        if deleted_tldr and 0 < surviving < 3 and report['card_invalid_entries'] == surviving:
            report['cardinality_drops'] = [{'field': 'tldr', 'reason': 'science_rejection',
                                           'surviving_entries': surviving}]
    report['partial'] = bool(report['deferred_items'] or report['pending_items']
                             or report['rejected_items'] or report['card_invalid_entries']
                             or report.get('no_supported_card'))
    return analysis, report
