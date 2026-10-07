"""Full-text window extraction, local evidence validation and bounded synthesis."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
import time
from collections.abc import Callable
from ..db import Database
from ..models import PaperChunk
from ..services.model_calls import CallResult, cache_validated_call, cached_call, evict_call, json_call
from ..services.structure import extract_structure
from .base import AnalysisResult, CardEntry, ProviderError, VerifiedCitation
from .cards import CARD_ALIASES, CARD_LIMITS, LIST_FIELDS, SINGLE_FIELDS
from .card_recovery import apply_repairs, preserves_entries, repair_targets, resolved_field
from .science_review import MAX_BATCHES, MAX_ITEMS, MAX_PAYLOAD_CHARS, run_science_review
from .openai_compatible import PROMPTS_DIR
from .validation import canonical_quote
from .usage import sanitize_usage

WINDOW_CHARS = 20000
REDUCE_CHARS = 48000
MAX_REDUCTION_FACTS = 24
SOURCE_CHARS = 600
MAX_TRANSPORT_RETRIES = 2
MAX_RECOVERY_CALLS = 6
ALGORITHM_VERSION = 'fullpaper-science-review-v8'
PROMPT_NAMES = ('paper_extract.txt', 'paper_reduce.txt', 'paper_synthesize.txt', 'paper_repair.txt', 'paper_review.txt')


def analysis_fingerprint(provider, chunks: list[PaperChunk], *, prompts: dict[str, str] | None = None) -> str:
    """Result identity includes scientific source location and all generation settings."""
    value = {'algorithm': ALGORITHM_VERSION,
        'prompts': prompts if prompts is not None else {name: (PROMPTS_DIR / name).read_text(encoding='utf-8-sig') for name in PROMPT_NAMES},
        'source': [{'id': chunk.id, 'content': chunk.content, 'page': chunk.page, 'section': chunk.section, 'bbox': chunk.bbox_json, 'page_width': chunk.page_width, 'page_height': chunk.page_height} for chunk in sorted(chunks, key=lambda item: (item.page or 0, item.id))],
        'provider': provider.name, 'endpoint': getattr(provider, 'base_url', ''), 'model': getattr(provider, 'model', ''),
        'wire_api': getattr(provider, 'wire_api', ''), 'reasoning_effort': getattr(provider, 'reasoning_effort', 'high'),
        'json_mode': getattr(provider, 'json_mode', ''), 'completion_parameter': getattr(provider, 'completion_parameter', ''),
        'window_chars': WINDOW_CHARS, 'source_chars': SOURCE_CHARS, 'max_window_parts': 128, 'reduce_chars': REDUCE_CHARS, 'max_reduction_facts': MAX_REDUCTION_FACTS, 'extract_output_tokens': 6000, 'synthesis_output_tokens': 10000, 'transport_retries': MAX_TRANSPORT_RETRIES, 'recovery_calls': MAX_RECOVERY_CALLS,
        'science_review_batches': MAX_BATCHES, 'science_review_items': MAX_ITEMS, 'science_review_chars': MAX_PAYLOAD_CHARS}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class AnalysisCancelled(RuntimeError):
    """Cancellation is checked at every network boundary."""


@dataclass(frozen=True)
class SourcePart:
    part_id: str
    chunk_id: str
    start: int
    end: int
    page: int | None
    section: str | None
    content: str


@dataclass(frozen=True)
class StagedAnalysis:
    analysis: AnalysisResult
    report: dict


def pack_windows(chunks: list[PaperChunk], max_chars: int = WINDOW_CHARS) -> list[list[SourcePart]]:
    if max_chars < 1:
        raise ValueError('Window budget must be positive')
    windows, current, size = [], [], 0
    for chunk in sorted(chunks, key=lambda item: (item.page or 0, item.id)):
        for start in range(0, len(chunk.content), max_chars):
            end = min(start + max_chars, len(chunk.content))
            part = SourcePart(f'{chunk.id}:{start}:{end}', chunk.id, start, end, chunk.page, chunk.section, chunk.content[start:end])
            if current and (size + len(part.content) > max_chars or len(current) >= 128):
                windows.append(current)
                current, size = [], 0
            current.append(part)
            size += len(part.content)
    if current:
        windows.append(current)
    return windows


def source_passages(window: list[SourcePart]) -> dict[str, SourcePart]:
    """Number bounded original slices; offsets remain relative to the PDF chunk."""
    sources = {}
    for part in window:
        start = 0
        while start < len(part.content):
            end = min(start + SOURCE_CHARS, len(part.content))
            if end < len(part.content):
                # Prefer an observed line boundary in the latter half of the
                # slice. Include its newline so every character is retained.
                boundary = part.content.rfind('\n', start + SOURCE_CHARS // 2, end)
                if boundary >= 0:
                    end = boundary + 1
            absolute_start, absolute_end = part.start + start, part.start + end
            source = SourcePart(f'{part.chunk_id}:{absolute_start}:{absolute_end}',
                part.chunk_id, absolute_start, absolute_end, part.page, part.section, part.content[start:end])
            sources[f'S{len(sources) + 1:05d}'] = source
            start = end
    return sources


def _verified_citations(raw: object, parts: dict[str, SourcePart], allowed: list[dict] | None = None, *, reject: Callable[[str], None] | None = None) -> list[dict] | None:
    def invalid(reason: str):
        if reject:
            reject(reason)
        return None
    if not isinstance(raw, list) or not 1 <= len(raw) <= CARD_LIMITS['max_citation_ids']:
        return invalid('invalid_citations')
    result = []
    for citation in raw:
        if not isinstance(citation, dict):
            return invalid('invalid_citations')
        part = parts.get(citation.get('part_id')) if isinstance(citation.get('part_id'), str) else None
        quote = citation.get('source_text')
        if part is None:
            return invalid('unknown_source')
        if citation.get('chunk_id') != part.chunk_id:
            return invalid('source_mismatch')
        if not isinstance(quote, str) or not 1 <= len(quote.strip()) <= 4000:
            return invalid('invalid_quote')
        source = canonical_quote(part.content, quote)
        if source is None:
            return invalid('quote_not_found')
        if allowed is not None and not any(item['part_id'] == part.part_id and canonical_quote(item['source_text'], source) is not None for item in allowed):
            return invalid('quote_outside_evidence')
        start = part.start + part.content.index(source)
        result.append({'part_id': part.part_id, 'chunk_id': part.chunk_id, 'source_text': source, 'start': start, 'end': start + len(source)})
    if sum(len(citation['source_text']) for citation in result) > CARD_LIMITS['max_citation_chars']:
        return invalid('citation_budget')
    return list({(item['part_id'], item['source_text']): item for item in result}.values())


def _facts(raw: object, parts: dict[str, SourcePart], allowed: list[dict] | None = None, *, sources: dict[str, SourcePart] | None = None, reject: Callable[[str, str], None] | None = None) -> tuple[list[dict], int]:
    if not isinstance(raw, list) or len(raw) > 100:
        raise ProviderError('模型抽取结果格式无效，已有结果已保留')
    result, invalid = [], 0
    for index, entry in enumerate(raw):
        content = entry.get('content') if isinstance(entry, dict) else None
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 4000:
            if reject:
                reject('invalid_content', f'facts[{index}]')
            invalid += 1
            continue
        raw_citations = entry.get('citations')
        if 'source_ids' in entry:
            ids = entry['source_ids']
            if (not isinstance(ids, list) or not 1 <= len(ids) <= CARD_LIMITS['max_citation_ids']
                or any(not isinstance(source_id, str) or source_id not in (sources or {}) for source_id in ids)):
                if reject:
                    reject('invalid_source_ids', f'facts[{index}]')
                invalid += 1
                continue
            raw_citations = [{'part_id': sources[source_id].part_id, 'chunk_id': sources[source_id].chunk_id,
                'source_text': sources[source_id].content} for source_id in dict.fromkeys(ids)]
        citations = _verified_citations(raw_citations, parts, allowed,
            reject=(lambda reason: reject(reason, f'facts[{index}]')) if reject else None)
        if citations is None:
            invalid += 1
            continue
        normalized = {'content': content.strip(), 'section': parts[citations[0]['part_id']].section, 'citations': citations}
        normalized['id'] = 'fact-' + hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
        result.append(normalized)
    return list({entry['id']: entry for entry in result}.values()), invalid


def _groups(facts: list[dict]) -> list[list[dict]]:
    groups, group, size = [], [], 0
    for fact in facts:
        length = len(json.dumps(fact, ensure_ascii=False))
        if length > REDUCE_CHARS:
            raise ProviderError('单个已验证事实超过归纳预算，已有结果已保留')
        if group and size + length > REDUCE_CHARS:
            groups.append(group)
            group, size = [], 0
        group.append(fact)
        size += length
    if group:
        groups.append(group)
    return groups


def _citation_pool(facts: list[dict], parts: dict[str, SourcePart]) -> dict[str, dict]:
    """An immutable ID maps to one previously verified, unmodified source excerpt."""
    pool, keys = {}, {}
    for fact in facts:
        refs = []
        for citation in fact['citations']:
            key = (citation['part_id'], citation['source_text'], citation['start'], citation['end'])
            if key not in keys:
                citation_id = f'E{len(pool) + 1:05d}'
                keys[key] = citation_id
                pool[citation_id] = {**citation, 'section': parts[citation['part_id']].section}
            refs.append(keys[key])
        fact['citation_ids'] = list(dict.fromkeys(refs))
        fact['source_fact_ids'] = [fact['id']]
    return pool


def _model_context(facts: list[dict], pool: dict[str, dict]) -> dict:
    refs = {citation_id for fact in facts for citation_id in fact['citation_ids']}
    return {'facts': [{'id': fact['id'], 'content': fact['content'], 'section': fact['section'], 'citation_ids': fact['citation_ids']} for fact in facts],
        'evidence': [{'id': citation_id, 'chunk_id': source['chunk_id'], 'section': source['section'], 'source_text': source['source_text']} for citation_id, source in pool.items() if citation_id in refs]}


def _context_size(facts: list[dict], pool: dict[str, dict]) -> int:
    return len(json.dumps(_model_context(facts, pool), ensure_ascii=False))


def _context_groups(facts: list[dict], pool: dict[str, dict]) -> list[list[dict]]:
    groups, group = [], []
    for fact in facts:
        if _context_size([fact], pool) > REDUCE_CHARS:
            raise ProviderError('单个已验证事实超过归纳预算，已有结果已保留')
        # Twelve output entries can pair 24 parents; two 4000-char excerpts fit the 8000-char citation cap.
        if group and (len(group) >= MAX_REDUCTION_FACTS or _context_size([*group, fact], pool) > REDUCE_CHARS):
            groups.append(group)
            group = []
        group.append(fact)
    if group:
        groups.append(group)
    return groups


def _id_citations(raw: object, pool: dict[str, dict], allowed_ids: set[str]) -> list[dict] | None:
    if not isinstance(raw, list) or not 1 <= len(raw) <= CARD_LIMITS['max_citation_ids'] or any(not isinstance(item, str) or item not in allowed_ids or item not in pool for item in raw):
        return None
    return [pool[item] for item in dict.fromkeys(raw)]


def _reduce_facts(raw: object, group: list[dict], pool: dict[str, dict], parts: dict[str, SourcePart], *, max_facts: int, reject: Callable[[str, str], None] | None = None) -> tuple[list[dict], int]:
    if not isinstance(raw, list) or len(raw) > 100:
        raise ProviderError('模型归纳格式无效，已有结果已保留')
    lookup = {fact['id']: fact for fact in group}
    allowed = {citation_id for fact in group for citation_id in fact['citation_ids']}
    reduced, covered, invalid = [], set(), 0
    for index, entry in enumerate(raw):
        content = entry.get('content') if isinstance(entry, dict) else None
        parents = entry.get('fact_ids') if isinstance(entry, dict) else None
        refs = entry.get('citation_ids') if isinstance(entry, dict) else None
        sources = _id_citations(refs, pool, allowed)
        reason = None
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 4000:
            reason = 'invalid_content'
        elif not isinstance(parents, list) or not parents or any(not isinstance(parent, str) or parent not in lookup for parent in parents):
            reason = 'invalid_parent_ids'
        elif sources is None:
            reason = 'invalid_citation_ids'
        elif any(not set(lookup[parent]['citation_ids']).intersection(refs) for parent in parents):
            reason = 'missing_parent_citations'
        if reason:
            if reject:
                reject(reason, f'facts[{index}]')
            invalid += 1
            continue
        citations = _verified_citations(sources, parts, reject=(lambda reason: reject(reason, f'facts[{index}]')) if reject else None)
        if not citations:
            invalid += 1
            continue
        lineage = sorted({source_id for parent in parents for source_id in lookup[parent]['source_fact_ids']})
        fact = {'content': content.strip(), 'section': parts[citations[0]['part_id']].section, 'citations': citations, 'citation_ids': list(dict.fromkeys(refs)), 'source_fact_ids': lineage}
        fact['id'] = 'fact-' + hashlib.sha256(json.dumps(fact, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
        reduced.append(fact)
        covered.update(parents)
    if not reduced or covered != set(lookup):
        if reject:
            reject('incomplete_lineage', 'facts')
        raise ProviderError('模型归纳遗漏了已验证事实或引用了范围外的证据，已有结果已保留')
    if len(reduced) > max_facts:
        raise ProviderError('模型归纳未遵守事实预算，已有结果已保留')
    return list({fact['id']: fact for fact in reduced}.values()), invalid


def _card(data: dict, facts: list[dict], parts: dict[str, SourcePart], chunks: list[PaperChunk], model: str, prompt_version: str, pool: dict[str, dict] | None = None, *, reject: Callable[[str, str], None] | None = None, additional_sources: list[dict] | None = None) -> tuple[AnalysisResult, int]:
    raw = data.get('card') if isinstance(data.get('card'), dict) else data
    allowed = [citation for fact in facts for citation in fact['citations']]
    lookup = {chunk.id: chunk for chunk in chunks}
    # The reviewer may need a previously uncited table header or comparator
    # row. Only trusted, unchanged passages from this paper's local catalog
    # can extend the quote scope; no fabricated parent fact is introduced.
    for source in additional_sources or []:
        if isinstance(source, dict) and source.get('chunk_id') in lookup:
            verified_source = _verified_citations([source], parts)
            if verified_source:
                allowed.extend(verified_source)
    result = AnalysisResult(model_version=model, prompt_version=prompt_version)
    invalid = 0
    def entry(value: object, field: str, section_summary: bool = False) -> CardEntry | None:
        nonlocal invalid
        if value is None:
            return None
        content = value.get('content') if isinstance(value, dict) else None
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= CARD_LIMITS['max_content_chars']:
            if reject:
                reject('invalid_content', field)
            invalid += 1
            return None
        sources = value.get('citations') if isinstance(value, dict) else None
        if isinstance(value, dict) and 'citation_ids' in value:
            allowed_ids = {citation_id for fact in facts for citation_id in fact['citation_ids']}
            sources = _id_citations(value['citation_ids'], pool or {}, allowed_ids)
            if sources is None:
                if reject:
                    reject('invalid_citation_ids', field)
                invalid += 1
                return None
        citations = _verified_citations(sources, parts, allowed, reject=(lambda reason: reject(reason, field)) if reject else None)
        if not citations:
            invalid += 1
            return None
        section = parts[citations[0]['part_id']].section
        if section_summary and value.get('section') is not None and any(parts[item['part_id']].section != value['section'] for item in citations):
            if reject:
                reject('section_mismatch', field)
            invalid += 1
            return None
        verified = [VerifiedCitation(lookup[item['chunk_id']], item['source_text'], content.strip(), 'llm_summary') for item in citations]
        result.citations.extend(verified)
        return CardEntry(content.strip(), verified, section)
    for field in SINGLE_FIELDS:
        value = entry(raw.get(field, raw.get(CARD_ALIASES.get(field, field))), field)
        result.card[field] = value
        if value and (legacy := CARD_ALIASES.get(field, field)) in {'one_liner', 'problem', 'method', 'findings', 'limitations'}:
            setattr(result, legacy, value.content)
    for field in LIST_FIELDS:
        values = raw.get(field, [])
        if not isinstance(values, list) or len(values) > 100:
            if reject:
                reject('invalid_list', field)
            invalid += 1
            values = []
        entries = [item for index, value in enumerate(values) if (item := entry(value, f'{field}[{index}]', field == 'section_summaries'))]
        if field == 'tldr' and entries and not 3 <= len(entries) <= 5:
            if reject:
                reject('tldr_count', field)
            invalid += len(entries)
            entries = []
        result.card[field] = entries
    # Only concepts actually occurring in submitted originals are retained.
    corpus = '\n'.join(part.content for part in parts.values()).casefold()
    concepts = data.get('concepts', [])
    if isinstance(concepts, list):
        result.concepts = list(dict.fromkeys(item for item in concepts if isinstance(item, str) and 1 <= len(item) <= 100 and item.casefold() in corpus))
    # Gather final citations from accepted entries only (invalid TLDR must not remain evidence).
    result.citations = [citation for value in result.card.values() for item in (value if isinstance(value, list) else [value] if value else []) for citation in item.citations]
    if not result.citations:
        raise ProviderError('模型没有返回可验证的论文卡片，已有结果已保留')
    return result, invalid


def _usage(calls: list[CallResult]) -> dict:
    remote = [call for call in calls if not call.cached]
    unknown = sum(call.usage.get('input_tokens', call.usage.get('prompt_tokens')) is None
        or call.usage.get('output_tokens', call.usage.get('completion_tokens')) is None for call in remote)
    def total(primary: str, alternate: str) -> int | float | None:
        values = [call.usage.get(primary, call.usage.get(alternate)) for call in remote]
        return None if any(value is None for value in values) else sum(values)
    return {'remote_calls': len(remote), 'cache_hits': len(calls) - len(remote), 'unknown_usage_calls': unknown,
        'input_tokens': total('input_tokens', 'prompt_tokens'), 'output_tokens': total('output_tokens', 'completion_tokens'),
        'calls': [{'cached': call.cached, 'model': call.model, 'usage': call.usage} for call in calls]}


def analyze_full_paper(database: Database, provider, chunks: list[PaperChunk], *, progress: Callable[[str, int, int, dict], None] | None = None, cancelled: Callable[[], bool] | None = None) -> StagedAnalysis:
    windows = pack_windows(chunks)
    if not windows:
        raise ProviderError('当前论文没有可分析的原文，已有结果已保留', 422)
    catalogs = [source_passages(window) for window in windows]
    parts = {part.part_id: part for sources in catalogs for part in sources.values()}
    prompts = {name: (PROMPTS_DIR / name).read_text(encoding='utf-8-sig') for name in PROMPT_NAMES}
    extract_prompt, reduce_prompt, synth_prompt, repair_prompt, review_prompt = (prompts[name] for name in PROMPT_NAMES)
    run_fingerprint = analysis_fingerprint(provider, chunks, prompts=prompts)
    prompt_version = 'staged:' + hashlib.sha256(json.dumps(prompts, sort_keys=True).encode()).hexdigest()[:64]
    report = {'prompt_version': prompt_version, 'coverage': {'total_chars': sum(len(part.content) for part in parts.values()), 'processed_chars': 0, 'total_windows': len(windows), 'processed_windows': 0, 'complete': False}, 'invalid_entries': 0, 'repaired_entries': 0, 'rejections': [], 'recoveries': [], 'structure': extract_structure(chunks)}
    calls: list[CallResult] = []
    descriptors: list[tuple[str, dict, str, int, str]] = []
    facts: list[dict] = []
    completed, total = 0, len(windows) + 1
    def check():
        if cancelled and cancelled():
            raise AnalysisCancelled()
    current_phase = 'extract'
    recovery_calls = 0
    def publish(phase: str):
        nonlocal current_phase
        current_phase = phase
        report['usage'] = _usage(calls)
        if progress:
            progress(phase, completed, total, report)
    def diagnostics(phase: str, **location):
        def reject(reason: str, field: str):
            # Persist generated codes and local positions, never upstream prose or credentials.
            if len(report['rejections']) < 100:
                report['rejections'].append({'phase': phase, **location, 'field': field, 'reason': reason})
        return reject
    def reserve_recovery() -> bool:
        nonlocal recovery_calls
        if recovery_calls >= MAX_RECOVERY_CALLS:
            return False
        recovery_calls += 1
        return True
    def call(system: str, payload: dict, operation: str, effort: str, budget: int = 6000) -> CallResult:
        check()
        for attempt in range(MAX_TRANSPORT_RETRIES + 1):
            try:
                response = json_call(database, provider, system, payload, operation, budget, effort)
                break
            except ProviderError as error:
                calls.append(CallResult({}, sanitize_usage(getattr(provider, 'last_usage', {})), False, getattr(provider, 'response_model', None) or getattr(provider, 'model', '')))
                publish(current_phase)
                if not getattr(error, 'retryable', False) or attempt == MAX_TRANSPORT_RETRIES or not reserve_recovery():
                    raise
                requested = getattr(error, 'retry_after', None)
                delay = min(30.0, max(0.0, requested if isinstance(requested, (int, float)) else 2 ** attempt))
                report['recoveries'].append({'phase': current_phase, 'operation': operation,
                    'kind': 'transport_retry', 'attempt': attempt + 1, 'code': error.code, 'delay_seconds': delay})
                publish(current_phase)
                while delay > 0:
                    check()
                    step = min(.25, delay)
                    time.sleep(step)
                    delay -= step
                check()
        calls.append(response)
        descriptors.append((system, payload, operation, budget, effort))
        publish(current_phase)
        check()
        return response
    for index, sources in enumerate(catalogs):
        window = list(sources.values())
        publish('extract')
        window_ids = {part.part_id: part for part in window}
        # Structure is scoped to the current window; its index cannot grow model context without bound.
        ids = {part.chunk_id for part in window}
        structure = {key: [item for item in values if item['chunk_id'] in ids and ('start' not in item or any(part.chunk_id == item['chunk_id'] and part.start <= item['start'] and part.end >= item['end'] for part in window))] for key, values in report['structure'].items()}
        response = call(extract_prompt, {'window_index': index, 'windows_total': len(windows),
            'chunks': [{'source_id': source_id, **asdict(part)} for source_id, part in sources.items()], 'structure': structure}, 'paper_extract', 'medium')
        try:
            verified, invalid = _facts(response.data.get('facts'), window_ids, sources=sources, reject=diagnostics('extract', window_index=index))
        except ProviderError:
            evict_call(database, provider, *descriptors[-1])
            raise
        if invalid:
            evict_call(database, provider, *descriptors[-1])
        facts.extend(verified)
        report['invalid_entries'] += invalid
        report['coverage']['processed_chars'] += sum(len(part.content) for part in window)
        report['coverage']['processed_windows'] += 1
        completed += 1
        publish('extract')
    facts = list({fact['id']: fact for fact in facts}.values())
    report['verified_facts'] = len(facts)
    report['coverage']['complete'] = True
    if not facts:
        for descriptor in descriptors:
            evict_call(database, provider, *descriptor)
        raise ProviderError('模型抽取没有可验证的事实，已有结果已保留')
    source_fact_ids = {fact['id'] for fact in facts}
    pool = _citation_pool(facts, parts)
    for level in range(8):
        # Group capacity applies only when reduction is needed, not to final synthesis.
        if _context_size(facts, pool) <= REDUCE_CHARS:
            break
        groups = _context_groups(facts, pool)
        total += len(groups)
        reduced = []
        previous_size = _context_size(facts, pool)
        level_descriptors_start = len(descriptors)
        for group_index, group in enumerate(groups):
            publish('reduce')
            max_facts = max(1, min(12, (len(group) + 1) // 2))
            payload = {**_model_context(group, pool), 'stage': 'reduce', 'level': level, 'max_facts': max_facts, 'target_context_chars': int(_context_size(group, pool) * 0.7)}
            checkpoint = cached_call(database, provider, repair_prompt, payload, 'paper_corrected_reduce_v1', 6000, 'high')
            if checkpoint:
                try:
                    checkpoint_facts, checkpoint_invalid = _reduce_facts(checkpoint.data.get('facts'), group, pool, parts, max_facts=max_facts)
                    if checkpoint_invalid or _context_size(checkpoint_facts, pool) >= _context_size(group, pool):
                        raise ProviderError('已缓存归纳仍包含未验证条目')
                except ProviderError:
                    evict_call(database, provider, repair_prompt, payload, 'paper_corrected_reduce_v1', 6000, 'high')
                    checkpoint = None
            if checkpoint:
                response = checkpoint
                calls.append(response)
                descriptors.append((repair_prompt, payload, 'paper_corrected_reduce_v1', 6000, 'high'))
                publish('reduce')
                check()
            else:
                response = call(reduce_prompt, payload, 'paper_reduce', 'medium')
            rejection_start = len(report['rejections'])
            try:
                verified, invalid = _reduce_facts(response.data.get('facts'), group, pool, parts, max_facts=max_facts, reject=diagnostics('reduce', level=level, group_index=group_index))
            except ProviderError:
                evict_call(database, provider, *descriptors[-1])
                publish('reduce')
                if not reserve_recovery():
                    raise
                aliases = {f'F{index:05d}': fact['id'] for index, fact in enumerate(group, 1)}
                correction = {**payload, 'stage': 'repair_reduce', 'validation_errors': [
                    {'field': item['field'], 'reason': item['reason']} for item in report['rejections'][rejection_start:]]}
                correction['facts'] = [{**fact, 'id': alias} for alias, fact in zip(aliases, payload['facts'])]
                response = call(repair_prompt, correction, 'paper_repair_reduce_v1', 'high')
                entries = response.data.get('facts')
                if isinstance(entries, list):
                    entries = [{**entry, 'fact_ids': [aliases.get(parent, 'unknown-parent') for parent in entry['fact_ids']]}
                        if isinstance(entry, dict) and isinstance(entry.get('fact_ids'), list)
                        and all(isinstance(parent, str) for parent in entry['fact_ids']) else entry for entry in entries]
                try:
                    verified, invalid = _reduce_facts(entries, group, pool, parts, max_facts=max_facts,
                        reject=diagnostics('repair_reduce', level=level, group_index=group_index))
                except ProviderError:
                    evict_call(database, provider, *descriptors[-1])
                    publish('reduce')
                    raise
                for item in report['rejections'][rejection_start:]:
                    if item['phase'] == 'reduce':
                        item['resolved'] = True
                if not invalid and _context_size(verified, pool) < _context_size(group, pool):
                    cache_validated_call(database, provider, repair_prompt, payload, 'paper_corrected_reduce_v1',
                        CallResult({'facts': entries}, response.usage, response.cached, response.model), 6000, 'high')
                report['recoveries'].append({'phase': 'reduce', 'kind': 'group_correction',
                    'level': level, 'group_index': group_index, 'retained_parents': len(group)})
            if not verified:
                evict_call(database, provider, *descriptors[-1])
                raise ProviderError('模型归纳没有可验证的事实，已有结果已保留')
            if invalid:
                evict_call(database, provider, *descriptors[-1])
            reduced.extend(verified)
            report['invalid_entries'] += invalid
            completed += 1
            publish('reduce')
        facts = list({fact['id']: fact for fact in reduced}.values())
        if _context_size(facts, pool) >= previous_size:
            for descriptor in descriptors[level_descriptors_start:]:
                evict_call(database, provider, *descriptor)
            raise ProviderError('模型归纳未缩减上下文，已有结果已保留')
    if _context_size(facts, pool) > REDUCE_CHARS:
        raise ProviderError('论文超过本轮归纳预算，已保留阶段缓存和已有结果')
    retained = {source_id for fact in facts for source_id in fact['source_fact_ids']}
    report['fact_coverage'] = {'total': len(source_fact_ids), 'retained': len(retained), 'complete': retained == source_fact_ids}
    if retained != source_fact_ids:
        raise ProviderError('归纳未保留全部已验证事实的来源，已有结果已保留')
    publish('synthesize')
    response = call(synth_prompt, {**_model_context(facts, pool), 'coverage': report['coverage'], 'fact_coverage': report['fact_coverage']}, 'paper_synthesize', getattr(provider, 'reasoning_effort', 'high'), 10000)
    synth_descriptor = descriptors[-1]
    rejection_start = len(report['rejections'])
    card_error = None
    try:
        analysis, invalid = _card(response.data, facts, parts, chunks, response.model, prompt_version, pool, reject=diagnostics('synthesize'))
    except ProviderError as error:
        card_error = error
        analysis, invalid = None, len(report['rejections']) - rejection_start
    targets = repair_targets(response.data, report['rejections'][rejection_start:])
    if targets and reserve_recovery():
        correction = {**_model_context(facts, pool), 'stage': 'repair_card', 'targets': targets}
        check()
        try:
            corrected = call(repair_prompt, correction, 'paper_repair_card_v1', 'high')
        except ProviderError as error:
            # Repair is optional when a validated partial card already exists.
            # An outage must not throw away its accepted entries.
            report['recoveries'].append({'phase': 'synthesize', 'kind': 'card_correction_failed',
                'code': error.code, 'requested_fields': [target['field'] for target in targets]})
        else:
            validate = lambda data: _card(data, facts, parts, chunks, corrected.model, prompt_version, pool)
            patched, resolved = apply_repairs(response.data, targets, corrected.data.get('repairs'), validate)
            if resolved:
                try:
                    repaired, remaining = validate(patched)
                    if not preserves_entries(analysis, repaired):
                        raise ProviderError('字段纠错不能丢弃已核验的卡片条目')
                except ProviderError:
                    resolved = set()
                else:
                    analysis, card_error = repaired, None
                    report['repaired_entries'] += max(0, invalid - remaining)
                    invalid = remaining
                    for item in report['rejections'][rejection_start:]:
                        if resolved_field(item['field'], resolved):
                            item['resolved'] = True
            report['recoveries'].append({'phase': 'synthesize', 'kind': 'card_correction',
                'requested_fields': [target['field'] for target in targets], 'resolved_fields': sorted(resolved)})
            if invalid or card_error:
                evict_call(database, provider, *descriptors[-1])
    if invalid or card_error:
        evict_call(database, provider, *synth_descriptor)
    if card_error:
        publish('synthesize')
        raise card_error
    report['invalid_entries'] += invalid
    review_descriptors = []
    def science_call(payload):
        nonlocal total, completed
        total += 1
        publish('synthesize')
        reviewed = call(review_prompt, payload, 'paper_science_review_v1', 'high')
        review_descriptors.append(descriptors[-1])
        completed += 1
        publish('synthesize')
        return reviewed.data
    science_validate = lambda data, sources: _card(data, facts, parts, chunks,
        response.model, prompt_version, pool, additional_sources=sources)
    analysis, science = run_science_review(analysis, parts, science_call, science_validate)
    report['science_review'] = science
    for index in science['invalid_response_batches']:
        evict_call(database, provider, *review_descriptors[index])
    for outcome in science['results']:
        for field, reason in outcome['rejection_reasons'].items():
            if len(report['rejections']) < 100:
                report['rejections'].append({'phase': 'science_review', 'field': field, 'reason': reason})
    report['invalid_entries'] += science['rejected_items'] + science['card_invalid_entries']
    report['partial'] = report['invalid_entries'] > 0 or science['partial']
    if science.get('no_supported_card'):
        publish('synthesize')
        raise ProviderError('科学复核后没有可发布的卡片，已有结果已保留', code='science_support')
    report['accepted_card_fields'] = [field for field, value in analysis.card.items() if value]
    report['missing_fields'] = [field for field, value in analysis.card.items() if not value]
    report['citation_count'] = len(analysis.citations)
    report['source_authenticity'] = 'locally_verified'
    report['semantic_verification'] = 'not_automatically_proven'
    report['model'] = response.model
    report['result_fingerprint'] = run_fingerprint
    completed += 1
    publish('complete')
    return StagedAnalysis(analysis, report)
