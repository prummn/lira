"""Model-assisted query planning over bounded, typed, local evidence.

The model chooses search terms, not executable tools. Every outgoing source has
an immutable local ID. Only that submitted text can validate a returned quote.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import hashlib
import json
from math import log1p, sqrt
from pathlib import Path
import re

from fastapi import HTTPException
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import selectinload

from ..db import Database
from ..library_schemas import LibraryAnswer, LibraryAnswerItem, LibraryCitation, LibraryQuestion
from ..models import Collection, CollectionPaper, Note, Paper, PaperAuthor
from ..providers.base import ProviderError
from ..providers.mock import STOPWORDS, tokens
from ..providers.validation import canonical_quote
from .serialization import values
from .model_calls import evict_call

PROMPTS = Path(__file__).resolve().parents[3] / 'prompts'
CATALOG_LIMIT = 200
SOURCE_BUDGET = 48000
SOURCE_LIMIT = 72


def json_call(*args, **kwargs):
    # Transport/cache implementation is shared with the staged analysis worker.
    from .model_calls import json_call as call
    return call(*args, **kwargs)


@dataclass(frozen=True)
class Source:
    id: str
    paper_id: str
    title: str
    content: str
    kind: str
    page: int | None = None
    section: str | None = None
    chunk_id: str | None = None
    bbox: list[float] | None = None
    page_width: float | None = None
    page_height: float | None = None

    @property
    def quote_id(self) -> str:
        # Bind the selector to this exact submitted excerpt, not hidden full text.
        encoded = json.dumps([self.id, self.content], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return 'quote-' + hashlib.sha256(encoded).hexdigest()

    def payload(self) -> dict:
        return {'source_id': self.id, 'paper_id': self.paper_id, 'title': self.title,
                'type': self.kind, 'page': self.page, 'section': self.section,
                'content': self.content, 'quote_id': self.quote_id}


def library_scope(session, payload: LibraryQuestion) -> list[Paper]:
    statement = select(Paper).options(
        selectinload(Paper.author_links).selectinload(PaperAuthor.author),
        selectinload(Paper.collection_links), selectinload(Paper.analysis),
    )
    if payload.collection_id:
        if session.get(Collection, payload.collection_id) is None:
            raise HTTPException(404, '集合不存在')
        statement = statement.where(select(CollectionPaper.paper_id).where(
            CollectionPaper.paper_id == Paper.id,
            CollectionPaper.collection_id == payload.collection_id).exists())
    if payload.paper_ids:
        statement = statement.where(Paper.id.in_(payload.paper_ids))
    else:
        statement = statement.where(Paper.is_demo.is_(False))
    papers = list(session.scalars(statement.order_by(Paper.id)).unique())
    if payload.paper_ids and {p.id for p in papers} != set(payload.paper_ids):
        raise HTTPException(422, '指定论文不存在或不属于当前集合')
    return papers


def catalog_record(paper: Paper, note_count: int) -> dict:
    return {'paper_id': paper.id, 'title': paper.title,
            'authors': [link.author.name for link in paper.author_links],
            'year': paper.year, 'venue': paper.venue, 'arxiv_id': paper.arxiv_id,
            'doi': paper.doi, 'is_demo': paper.is_demo,
            'reading_status': paper.reading_status, 'is_favorite': paper.is_favorite,
            'tags': values(paper.tags_json), 'collection_ids': [link.collection_id for link in paper.collection_links],
            'intelligence_status': getattr(paper, 'intelligence_status', None) or (
                'completed' if paper.analysis and paper.analysis.mode == 'remote' else 'unanalyzed'),
            'analysis_mode': paper.analysis.mode if paper.analysis else None,
            'summary': (paper.analysis.one_liner if paper.analysis else paper.abstract or '') or '',
            'summary_source': 'ai' if paper.analysis else 'paper',
            'metadata_sources': json.loads(paper.metadata_sources_json or '{}'),
            'notes_count': note_count}


def catalog_snapshot(database: Database, payload: LibraryQuestion) -> tuple[list[dict], dict]:
    with database.sessions() as session:
        papers = library_scope(session, payload)
        counts = dict(session.execute(select(Note.paper_id, func.count(Note.id)).group_by(Note.paper_id)).all())
        records = [catalog_record(p, counts.get(p.id, 0)) for p in papers]
    query = tokens(payload.question)
    records.sort(key=lambda r: (-len(tokens(r['title'] + ' ' + r['summary']) & query), r['paper_id']))
    total = len(records)
    records = records[:CATALOG_LIMIT]
    for record in records:
        record['summary'] = record['summary'][:600]
    return records, {'scope_papers': total, 'catalog_papers': len(records),
                     'catalog_truncated': total > len(records), 'excludes_demo': not bool(payload.paper_ids),
                     'collection_id': payload.collection_id}


def _fts(session, queries: list[str], scope: list[str]) -> list[dict]:
    if not scope:
        return []
    matches: dict[str, dict] = {}
    for query_index, query in enumerate(queries):
        wanted = _terms([query])
        terms = [term for term in re.findall(r'[^\W_]+', query.casefold(), re.UNICODE)
            if term in wanted or (len(term) >= 2 and re.search(r'[\u3400-\u9fff]', term))][:12]
        if not terms:
            continue
        expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
        statement = text('SELECT c.id,c.paper_id,bm25(paper_chunks_fts) AS rank '
                         'FROM paper_chunks_fts JOIN paper_chunks c ON c.id=paper_chunks_fts.chunk_id '
                         'WHERE paper_chunks_fts MATCH :query AND c.paper_id IN :scope '
                         'ORDER BY rank,c.id LIMIT 120').bindparams(bindparam('scope', expanding=True))
        for position, row in enumerate(session.execute(statement, {'query': expression, 'scope': scope}).mappings(), 1):
            match = matches.setdefault(row['id'], {**dict(row), 'query_ranks': {}, 'rrf': 0.0})
            match['rank'] = min(match['rank'], row['rank'])
            match['query_ranks'][query_index] = position
            match['rrf'] += 1 / (10 + position)
    return sorted(matches.values(), key=lambda match: (-match['rrf'], match['rank'], match['id']))


def _terms(queries: list[str]) -> set[str]:
    terms = tokens(' '.join(queries))
    for query in queries:
        terms.update(term.casefold() for term in re.findall(r'\b(?:[A-Z][A-Z0-9]{1,3}|[A-Za-z]\d+)\b', query)
            if term.casefold() not in STOPWORDS)
        for phrase in re.findall(r'[\u3400-\u9fff]+', query):
            terms.update(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return {term for term in terms if len(term) >= 2 and term not in {'哪些', '论文', '笔记', '有关', '我的', '是否', '这个'}}


def _excerpt(content: str, queries: list[str], budget: int = 6000) -> str:
    if len(content) <= budget:
        return content
    lowered = content.casefold()
    # Keep a real match and its surrounding argument, even in a long source block.
    phrases = sorted(set(queries) | _terms(queries), key=len, reverse=True)
    positions = [lowered.find(phrase.casefold()) for phrase in phrases if len(phrase) >= 2]
    position = next((p for p in positions if p >= 0), 0)
    start = min(max(0, position - budget // 3), max(0, len(content) - budget))
    return content[start:start + budget]


def _numbered_section(section: str) -> str | None:
    match = re.match(r'^\s*(\d+(?:\.\d+)*)\b', section)
    return match.group(1) if match else None


def _topic_sections(chunks: list, queries: list[str], question: str, title: str) -> list[str]:
    request = ' '.join(queries + [question]).casefold()
    families = [
        (r'future|prospect|outlook|direction|未来|展望', r'future|prospect|outlook|未来|展望'),
        (r'evaluat|metric|benchmark|assess|评估|评价|指标|评测', r'evaluat|metric|benchmark|assess|评估|评价|指标|评测'),
        (r'efficien|computational|latency|scalab|cost|效率|开销|成本', r'efficien|scalab|compress|computational|latency|效率|压缩'),
        (r'limitation|challenge|局限|限制|挑战', r'limitation|challenge|discussion|局限|限制|挑战'),
        (r'method|mechanism|architecture|方法|机制|架构', r'method|mechanism|architecture|approach|方法|机制|架构'),
    ]
    names = list(dict.fromkeys(chunk.section for chunk in chunks if chunk.section))
    wanted = _terms(queries + [question]) - tokens(title)
    direct = [name for name in names if tokens(name) & wanted]
    groups = [[name for name in names if re.search(heading, name.casefold())]
        for trigger, heading in families if re.search(trigger, request)]
    result = []
    for group in groups + [direct]:
        parents = {_numbered_section(name) for name in group} - {None}
        focused = sorted(group, key=lambda name: (-len(tokens(name) & wanted), -name.count('.'), names.index(name)))
        for name in focused + names:
            number = _numbered_section(name)
            if name in group or (number and any(number.startswith(parent + '.') for parent in parents)):
                if name not in result:
                    result.append(name)
    return result


def _formula(content: str) -> bool:
    return len(content) <= 300 and not re.search(r'https?://', content) and bool(
        re.search(r'\b[A-Za-z][A-Za-z0-9_]{0,3}\s*=', content)) and not bool(
        re.fullmatch(r'\s*[a-z]\s*=\s*\d+\s*', content))


def _continuation(chunk, chunks: list) -> list:
    """Keep a short argument/equation together, using the original PDF column."""
    if not (_formula(chunk.content) or re.match(r'^\s*\d+(?:\.\d+)+\s+[A-Za-z\u3400-\u9fff]', chunk.content) or re.search(
            r'(?:[-:=]|\b(?:the|of|as|to|and|or|a|an|is|for|with|by))\s*$', chunk.content)):
        return []
    box = values(chunk.bbox_json)
    same_page = [c for c in chunks if c.page == chunk.page and c.section == chunk.section]
    if len(box) == 4:
        formula = _formula(chunk.content)
        if formula and box[2] - box[0] < 80:
            columns = [values(c.bbox_json) for c in same_page]
            parents = [other for other in columns if len(other) == 4 and other[2] - other[0] > 150
                and other[0] <= box[0] and other[2] >= box[2] and 0 <= box[1] - other[3] < 180]
            if parents:
                parent = min(parents, key=lambda other: box[1] - other[3])
                box = [parent[0], box[1], parent[2], box[3]]
        def follows(candidate):
            other = values(candidate.bbox_json)
            lower = box[1] - 35 if formula else box[1]
            if len(other) != 4 or other[1] < lower or candidate.id == chunk.id:
                return False
            if formula and other[1] > box[3] + 45:
                return False
            overlap = min(box[2], other[2]) - max(box[0], other[0])
            return overlap > 0 and overlap >= min(box[2] - box[0], other[2] - other[0]) * 0.5
        following = sorted([c for c in same_page if follows(c)], key=lambda c: (values(c.bbox_json)[1], c.id))
    else:
        index = next(i for i, c in enumerate(chunks) if c.id == chunk.id)
        following = [c for c in chunks[index + 1:] if c.page == chunk.page and c.section == chunk.section]
    # A paragraph ending at the bottom of a page continues in the same section.
    if not following and chunk.page is not None:
        following = [c for c in chunks if c.page == chunk.page + 1 and c.section == chunk.section]
    result, size = [], 0
    for candidate in following[:10]:
        if size + len(candidate.content) > 2000:
            break
        result.append(candidate)
        size += len(candidate.content)
    return result


def _ranked_chunks(chunks: list, queries: list[str], question: str, title: str, hits: list[dict], card_ids: set) -> list:
    """Combine FTS ordering, local rarity, query diversity and observed structure."""
    if not chunks:
        return []
    documents = {chunk.id: _terms([chunk.content]) for chunk in chunks}
    frequencies = Counter(term for document in documents.values() for term in document)
    title_terms = tokens(title)
    weights = {term: log1p((len(chunks) + 1) / (count + 1)) * (0.2 if term in title_terms else 1)
        for term, count in frequencies.items()}
    by_id = {hit['id']: hit for hit in hits}
    def lexical(chunk, wanted):
        return sum(weights[term] for term in documents[chunk.id] & wanted) / sqrt(1 + len(documents[chunk.id]) / 100)
    wanted = _terms(queries + [question])
    scores = {chunk.id: lexical(chunk, wanted) + 8 * by_id.get(chunk.id, {}).get('rrf', 0)
        + (0.2 if chunk.id in card_ids else 0) for chunk in chunks}
    def ordered(candidates):
        return sorted(candidates, key=lambda c: (-scores[c.id], c.page or 0, c.id))
    anchors, seen = [], set()
    def add(chunk):
        if chunk.id not in seen and len(anchors) < 14:
            anchors.append(chunk)
            seen.add(chunk.id)
    # Reserve an anchor for each distinct model-planned query, rather than merging OR hits.
    for index, query in enumerate(queries):
        terms = _terms([query])
        candidates = [c for c in chunks if documents[c.id] & terms]
        if candidates:
            best = min(candidates, key=lambda c: (-lexical(c, terms)
                - 1 / (1 + by_id.get(c.id, {}).get('query_ranks', {}).get(index, 120)), c.page or 0, c.id))
            add(best)
    sections = _topic_sections(chunks, queries, question, title)
    # Short paragraph labels identify separate definitions even in one long section.
    labels = [c for c in chunks if len(c.content) >= 80 and not re.search(r'references|bibliography|参考文献', c.section or '', re.I)
        and len(c.content.splitlines()[0].split()) <= 4
        and _terms([c.content.splitlines()[0]]) & (wanted - title_terms)]
    for chunk in ordered(labels):
        add(chunk)
    for chunk in ordered([c for c in chunks if c.section in sections and _formula(c.content)])[:4]:
        add(chunk)
    # A named parent chapter also owns its numbered subsections, including topics
    # whose prose does not repeat the question's words (e.g. a future-work taxonomy).
    for section in sections:
        substantive = ordered([c for c in chunks if c.section == section and len(c.content.strip()) >= 80])
        if substantive:
            add(substantive[0])
    for chunk in ordered(chunks):
        add(chunk)
    expanded = list(anchors)
    def expand(candidates):
        for candidate in candidates:
            if candidate.id not in seen:
                expanded.append(candidate)
                seen.add(candidate.id)
    # Equation/paragraph continuations come before generic one-block neighbors.
    for chunk in sorted(anchors, key=lambda c: (not _formula(c.content), c.section not in sections, -scores[c.id])):
        expand(_continuation(chunk, chunks))
    indices = {c.id: i for i, c in enumerate(chunks)}
    for chunk in anchors:
        i = indices[chunk.id]
        expand(chunks[max(0, i - 1):i + 2])
    return expanded


def collect_sources(database: Database, records: list[dict], plan: dict, question: str) -> tuple[list[Source], dict]:
    allowed = {r['paper_id'] for r in records}
    selected = list(dict.fromkeys(pid for pid in plan.get('paper_ids', []) if isinstance(pid, str) and pid in allowed))[:12]
    queries = list(dict.fromkeys(q.strip()[:120] for q in plan.get('queries', []) if isinstance(q, str) and q.strip()))[:5]
    if not queries:
        queries = [question[:120]]
    sources: dict[str, Source] = {}
    intent = plan.get('intent')
    with database.sessions() as session:
        hits = _fts(session, queries, list(allowed)) if intent not in {'metadata', 'notes'} else []
        hit_papers = list(dict.fromkeys(hit['paper_id'] for hit in hits))
        # A personal-memory question must search notes in the whole allowed scope,
        # not only papers that happen to match English PDF text.
        terms = _terms(queries + [question])
        note_matches = []
        if allowed and intent != 'metadata':
            notes = session.scalars(select(Note).where(Note.paper_id.in_(allowed))).all()
            scored_notes = sorted(notes, key=lambda n: (-sum(term in n.content.casefold() for term in terms), n.id))
            note_matches = list(dict.fromkeys(n.paper_id for n in scored_notes
                if any(term in n.content.casefold() for term in terms)))
            if intent == 'notes' and not note_matches:
                note_matches = list(dict.fromkeys(n.paper_id for n in scored_notes))
        candidates = list(dict.fromkeys(selected + note_matches + hit_papers))[:12]
        if not candidates:
            candidates = [r['paper_id'] for r in records[:6]]
        for record in records:
            # Metadata stays available even when no paper has an AI card.
            rendered = json.dumps({k: v for k, v in record.items() if k not in {'summary', 'summary_source'}},
                                  ensure_ascii=False, sort_keys=True)
            sources['metadata:' + record['paper_id']] = Source('metadata:' + record['paper_id'], record['paper_id'], record['title'], rendered, 'external_metadata')
        options = (selectinload(Paper.notes),) if intent == 'notes' else (
            selectinload(Paper.chunks), selectinload(Paper.notes), selectinload(Paper.analysis), selectinload(Paper.evidence))
        papers = [] if intent == 'metadata' else list(session.scalars(
            select(Paper).where(Paper.id.in_(candidates)).options(*options)).unique())
        terms = _terms(queries + [question])
        # Round-robin evidence prevents the first paper from using all context.
        per_paper: dict[str, list[Source]] = {}
        for paper in papers:
            chunks = [] if intent == 'notes' else sorted(paper.chunks, key=lambda c: (c.page or 0, c.id))
            card_ids = set()
            if intent != 'notes' and paper.analysis:
                try:
                    card = json.loads(paper.analysis.card_json or '{}')
                except ValueError:
                    card = {}
                card_items = []
                for field, raw in card.items() if isinstance(card, dict) else []:
                    if field == 'title':
                        continue
                    for item in raw if isinstance(raw, list) else [raw]:
                        if isinstance(item, dict) and isinstance(item.get('content'), str):
                            card_items.append((field, item))
                for field, item in card_items:
                    if len(tokens(item['content']) & terms):
                        ids = {eid for eid in item.get('evidence_ids', []) if isinstance(eid, str)}
                        card_ids.update(e.chunk_id for e in paper.evidence if e.id in ids)
                summary = '\n'.join(f'{field}: {item["content"]}' for field, item in card_items)[:8000]
            else:
                summary = ''
            expanded = _ranked_chunks(chunks, queries, question, paper.title, hits, card_ids)
            paper_sources = [Source('chunk:' + c.id, paper.id, paper.title, _excerpt(c.content, queries), 'paper',
                                    c.page, c.section, c.id, values(c.bbox_json) or None,
                                    c.page_width, c.page_height) for c in expanded]
            # Notes and AI cards are visible but cannot pass as original facts.
            ranked_notes = sorted(paper.notes, key=lambda n: (-sum(term in n.content.casefold() for term in terms), n.id))
            note_sources = [Source('note:' + n.id, paper.id, paper.title, n.content, 'user', n.page,
                                   bbox=values(n.bbox_json) or None) for n in ranked_notes
                            if any(term in n.content.casefold() for term in terms) or plan.get('intent') == 'notes'][:8]
            if intent == 'notes':
                paper_sources = note_sources
            else:
                paper_sources = paper_sources[:3] + note_sources + paper_sources[3:]
            if summary:
                paper_sources.append(Source('card:' + paper.id, paper.id, paper.title, summary, 'ai'))
            per_paper[paper.id] = paper_sources
        # Selected metadata first; all remaining records remain in catalog payload.
        prioritized = [sources['metadata:' + pid] for pid in candidates if 'metadata:' + pid in sources]
        max_rows = max((len(s) for s in per_paper.values()), default=0)
        for i in range(max_rows):
            for pid in candidates:
                if pid in per_paper and i < len(per_paper[pid]):
                    prioritized.append(per_paper[pid][i])
        if intent == 'metadata':
            prioritized = prioritized[:len(candidates)] + list(sources.values()) + prioritized[len(candidates):]
        budget = SOURCE_BUDGET
        sent: list[Source] = []
        included = set()
        for source in prioritized:
            if source.id in included or len(sent) >= SOURCE_LIMIT or budget <= 0:
                continue
            # Exact prefix is recorded as submitted source, no hidden full text.
            content = source.content[:min(6000, budget)]
            if not content.strip():
                continue
            sent.append(Source(**{**source.__dict__, 'content': content}))
            included.add(source.id)
            budget -= len(content)
    return sent, {'queries': queries, 'candidate_paper_ids': candidates,
                  'selected_paper_ids': selected, 'source_characters': SOURCE_BUDGET - budget,
                  'sources': len(sent), 'retrieval_is_partial': True}


def validate_answer(data: dict, sources: list[Source]) -> tuple[list[LibraryAnswerItem], int]:
    lookup = {source.id: source for source in sources}
    items = []
    rejected = 0
    if data.get('insufficient_evidence') is not False:
        return [], 0
    raw_items = data.get('items') if isinstance(data.get('items'), list) else []
    # Keep validation bounded while making every omitted item visible as unverified.
    rejected = max(0, len(raw_items) - 16)
    for raw in raw_items[:16]:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        content, kind, references = raw.get('content'), raw.get('kind'), raw.get('citations')
        if (not isinstance(content, str) or not content.strip() or len(content) > 8000
                or not isinstance(kind, str) or kind not in {'fact', 'comparison', 'inference', 'user_note', 'metadata'}
                or not isinstance(references, list) or not 1 <= len(references) <= 12):
            rejected += 1
            continue
        citations = []
        valid = True
        for reference in references:
            if not isinstance(reference, dict):
                valid = False
                break
            source_id = reference.get('source_id')
            source = lookup.get(source_id) if isinstance(source_id, str) else None
            if not source:
                valid = False
                break
            canonical = None
            if 'quote_id' in reference:
                quote_id = reference['quote_id']
                if (not isinstance(quote_id, str) or quote_id != source.quote_id
                        or not source.content.strip() or len(source.content) > 6000):
                    valid = False
                    break
                # Local ID resolution never asks the model to transcribe PDF text.
                canonical = source.content
            if 'source_text' in reference or 'quote_id' not in reference:
                quote = reference.get('source_text')
                if not isinstance(quote, str) or not 8 <= len(quote) <= 3000:
                    valid = False
                    break
                # A valid selector must not bypass an invalid optional legacy quote.
                canonical = canonical_quote(source.content, quote)
            if canonical is None or (kind in {'fact', 'comparison', 'inference'} and source.kind != 'paper'):
                valid = False
                break
            if (kind == 'user_note' and source.kind != 'user') or (kind == 'metadata' and source.kind != 'external_metadata'):
                valid = False
                break
            digest = hashlib.sha256((source.id + canonical).encode()).hexdigest()[:20]
            citations.append(LibraryCitation(id='library-' + digest, paper_id=source.paper_id,
                title=source.title, source_id=source.id, source_text=canonical,
                source_type=source.kind, page=source.page, section=source.section,
                chunk_id=source.chunk_id, bbox=source.bbox, page_width=source.page_width,
                page_height=source.page_height))
        if kind == 'comparison' and len({c.paper_id for c in citations}) < 2:
            valid = False
        if valid and citations:
            items.append(LibraryAnswerItem(content=content.strip(), kind=kind, citations=citations))
        else:
            rejected += 1
    return items, rejected


def _usage(calls: list) -> dict:
    input_tokens = output_tokens = 0
    reported = True
    actual_calls = 0
    for call in calls:
        if call.cached:
            continue
        actual_calls += 1
        usage = call.usage or {}
        inbound = usage.get('input_tokens', usage.get('prompt_tokens'))
        outbound = usage.get('output_tokens', usage.get('completion_tokens'))
        if not isinstance(inbound, int) or not isinstance(outbound, int):
            reported = False
        else:
            input_tokens += inbound
            output_tokens += outbound
    return {'input_tokens': input_tokens if reported else None,
            'output_tokens': output_tokens if reported else None,
            'total_tokens': input_tokens + output_tokens if reported else None,
            'usage_reported': reported, 'model_calls': actual_calls,
            'cache_hits': sum(call.cached for call in calls)}


def answer_library(database: Database, provider, payload: LibraryQuestion) -> LibraryAnswer:
    if not getattr(provider, 'configured', False) or getattr(provider, 'mode', '') != 'remote':
        raise ProviderError('论文管理员需要配置有效的模型服务；本地阅读和搜索仍然可用', 503)
    records, coverage = catalog_snapshot(database, payload)
    if not records:
        return LibraryAnswer(answer='当前范围没有已存储的真实论文。', items=[], citations=[],
            provider=provider.name, mode=provider.mode, insufficient_evidence=True,
            limitations=['请先导入论文或选择包含论文的范围。'], retrieved_paper_ids=[],
            queries=[], coverage=coverage, usage=_usage([]), cached=True)
    history = [turn.model_dump() for turn in payload.history[-6:]]
    for turn in history:
        turn['content'] = turn['content'][-4000:]
    planner_system = (PROMPTS / 'librarian_plan.txt').read_text('utf-8')
    planner_payload = {'question': payload.question, 'history': history, 'catalog': records, 'coverage': dict(coverage)}
    planner_options = {'operation': 'library_plan_v1', 'max_output_tokens': 3000, 'reasoning_effort': 'medium'}
    planner = json_call(database, provider, planner_system, planner_payload, **planner_options)
    if (not isinstance(planner.data.get('queries'), list) or not isinstance(planner.data.get('paper_ids'), list)
            or not isinstance(planner.data.get('intent'), str)
            or planner.data['intent'] not in {'metadata', 'research', 'notes', 'comparison'}):
        evict_call(database, provider, planner_system, planner_payload, **planner_options)
        raise ProviderError('模型检索计划格式无效，请重试；论文和笔记已保留')
    sources, retrieval = collect_sources(database, records, planner.data, payload.question)
    coverage.update(retrieval)
    answer_system = (PROMPTS / 'librarian_answer.txt').read_text('utf-8')
    answer_payload = {'question': payload.question, 'history': history, 'catalog': records,
                      'sources': [s.payload() for s in sources], 'coverage': dict(coverage)}
    answer_options = {'operation': 'library_answer_v1', 'max_output_tokens': 10000, 'reasoning_effort': 'high'}
    answer = json_call(database, provider, answer_system, answer_payload, **answer_options)
    if not isinstance(answer.data.get('insufficient_evidence'), bool) or not isinstance(answer.data.get('items'), list):
        evict_call(database, provider, answer_system, answer_payload, **answer_options)
        raise ProviderError('模型回答格式无效，请重试；论文和笔记已保留')
    items, rejected = validate_answer(answer.data, sources)
    if not items and not answer.data['insufficient_evidence']:
        evict_call(database, provider, answer_system, answer_payload, **answer_options)
        raise ProviderError('模型回答没有通过来源核验，请重试或缩小问题范围')
    limitations = [s[:1000] for s in answer.data.get('limitations', [])[:8]
                   if isinstance(s, str)] if isinstance(answer.data.get('limitations', []), list) else []
    if rejected:
        evict_call(database, provider, answer_system, answer_payload, **answer_options)
        limitations.append(f'{rejected} 条无法核验来源的模型条目已排除。')
    comparison_source_type = 'external_metadata' if planner.data['intent'] == 'metadata' else 'paper'
    cited_papers = {c.paper_id for item in items for c in item.citations if c.source_type == comparison_source_type}
    if planner.data.get('intent') == 'comparison' or re.search(r'比较|区别|差异|compare|comparison|\bvs\b|versus', payload.question, re.I):
        expected = set(payload.paper_ids or retrieval['selected_paper_ids'])
        missing = expected - cited_papers
        coverage['comparison_paper_coverage_complete'] = not bool(missing)
        # Citation membership cannot establish semantic coverage of every dimension.
        coverage['comparison_complete'] = False if missing or rejected else None
        coverage['comparison_coverage_verification'] = 'paper_ids_only'
        if missing:
            limitations.append(f'本轮未取得 {len(missing)} 篇候选论文的可引用答案，不能视为完整比较。')
        if rejected:
            limitations.append('部分比较条目未通过来源核验，本轮仅保留可核验部分，不能视为完整比较。')
    if coverage['catalog_truncated']:
        limitations.append('目录超过本轮上下文上限；请选择集合或论文缩小范围。')
    citations = list({c.id: c for item in items for c in item.citations}.values())
    coverage['rejected_items'] = rejected
    coverage['source_authenticity_checked'] = True
    return LibraryAnswer(answer='\n\n'.join(item.content for item in items) or '当前库中没有足够且可核验的证据回答这个问题。',
        items=items, citations=citations, provider=provider.name, mode=provider.mode,
        model=answer.model, insufficient_evidence=not bool(items), limitations=limitations,
        retrieved_paper_ids=retrieval['candidate_paper_ids'], queries=retrieval['queries'],
        coverage=coverage, usage=_usage([planner, answer]), cached=planner.cached and answer.cached)
