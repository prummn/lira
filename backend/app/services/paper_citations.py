"""Conservative, read-only citation projection from locally stored references.

Bibliographic observation is independent of method lineage. No model call,
manual knowledge decision, or database write is involved here.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from ..models import Paper, PaperChunk

_REFERENCE_SECTION = re.compile(r'^(?:\d+[.\s]*)?(?:references|bibliography|参考文献)(?:\b|$)', re.I)
_ENTRY = re.compile(r'(?m)^[ \t]*(?:\[(\d{1,4})\]|(\d{1,3})\.[ \t]+(?=[A-Za-z]))[ \t]*')
_ARXIV = re.compile(r'(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v\d+)?', re.I)
_DOI = re.compile(r'\b10\.\d{4,9}/[^\s<>"\]]+', re.I)


def _normalized_with_offsets(value: str) -> tuple[str, list[int]]:
    # Retain original offsets through accent/case folding and PDF hyphenation.
    omitted = {i for m in re.finditer(r'(?<=\w)[-\u00ad]\s*\n\s*(?=\w)', value)
               for i in range(m.start(), m.end())}
    chars, offsets = [], []
    for i, char in enumerate(value):
        if i in omitted:
            continue
        for normalized in unicodedata.normalize('NFKD', char).casefold():
            if not unicodedata.combining(normalized):
                chars.append(normalized); offsets.append(i)
    result, positions = [], []
    for token in re.finditer(r'[^\W_]+', ''.join(chars)):
        if result:
            result.append(' '); positions.append(offsets[token.start()])
        result.extend(token.group()); positions.extend(offsets[token.start():token.end()])
    return ''.join(result), positions


def _title(value: str) -> str:
    return _normalized_with_offsets(value)[0]


def _title_boundaries(text: str, start: int, end: int) -> bool:
    before, after = text[:start].rstrip(), text[end:].lstrip()
    # A token substring of a longer, unimported title is insufficient evidence.
    begins = not before or before[-1] in '.?!)]\"\'“”‘’' or bool(re.search(r'(?:19|20)\d{2}[a-z]?$', before))
    ends = not after or after[0] in '.?!。)]\"\'“”‘’'
    return begins and ends


def _doi(value: str) -> str:
    match = _DOI.search(value)
    return match.group().casefold().rstrip('.,;:)') if match else ''


@dataclass
class Reference:
    text: str
    label: str | None
    evidence: list[dict]


def references_from_chunks(chunks: list[PaperChunk]) -> list[Reference]:
    """Keep chunk boundaries for evidence while joining wrapped references."""
    groups: list[list[PaperChunk]] = []
    previous_reference = False
    for chunk in sorted(chunks, key=lambda c: (c.page or 0, c.id)):
        in_references = bool(_REFERENCE_SECTION.match((chunk.section or '').strip()))
        if in_references:
            if not previous_reference:
                groups.append([])
            groups[-1].append(chunk)
        previous_reference = in_references

    result = []
    for group in groups:
        spans = []
        text = ''
        for chunk in group:
            start = len(text)
            text += chunk.content + '\n'
            spans.append((start, start + len(chunk.content), chunk))
        markers = list(_ENTRY.finditer(text))
        # Author/year bibliographies can lack numbering. Complete distinctive
        # titles and identifiers still constitute explicit bibliographic evidence.
        entries = [(m.start(), markers[i + 1].start() if i + 1 < len(markers) else len(text),
                    m.group(1) or m.group(2)) for i, m in enumerate(markers)] if markers else [(0, len(text), None)]
        for start, end, label in entries:
            evidence = []
            for a, b, chunk in spans:
                quote = chunk.content[max(0, start - a):min(b - a, end - a)].strip() if a < end and b > start else ''
                if quote and not quote.isdigit() and quote.casefold() not in {'references', 'bibliography'}:
                    evidence.append({'chunk_id': chunk.id, 'page': chunk.page, 'quote': quote})
            if evidence:
                excerpt = '\n'.join(e['quote'] for e in evidence)
                result.append(Reference(excerpt, label if len(excerpt) <= 2500 else None, evidence))
    return result


def _excerpt(reference: Reference, start: int, end: int) -> tuple[str, list[dict]]:
    if reference.label:
        return reference.text, reference.evidence
    # Unnumbered lists lack reliable entry boundaries. Show only source chunks
    # containing the matched title/identifier, never the entire bibliography.
    position = 0
    evidence = []
    for item in reference.evidence:
        quote = item['quote']
        if position < end and position + len(quote) > start:
            a, b = max(0, start - position - 250), min(len(quote), end - position + 250)
            evidence.append({**item, 'quote': quote[a:b]})
        position += len(quote) + 1
    return '\n'.join(e['quote'] for e in evidence), evidence


def citation_edges(papers: list[Paper], chunks: list[PaperChunk]) -> list[dict]:
    """Only unique identifiers or full distinctive titles link local papers."""
    real_papers = [paper for paper in papers if not paper.is_demo]
    titles: dict[str, list[str]] = defaultdict(list)
    arxiv: dict[str, list[str]] = defaultdict(list)
    dois: dict[str, list[str]] = defaultdict(list)
    for paper in real_papers:
        title = _title(paper.title)
        if len(title.split()) >= 5 and len(title) >= 24:
            titles[title].append(paper.id)
        if paper.arxiv_id:
            arxiv[re.sub(r'v\d+$', '', paper.arxiv_id)].append(paper.id)
        if paper.doi and _doi(paper.doi):
            dois[_doi(paper.doi)].append(paper.id)
    by_paper: dict[str, list[PaperChunk]] = defaultdict(list)
    for chunk in chunks:
        by_paper[chunk.paper_id].append(chunk)
    edges: dict[tuple[str, str], dict] = {}
    for source in real_papers:
        for reference in references_from_chunks(by_paper[source.id]):
            identifiers = [(m.start(), m.end(), arxiv.get(m.group(1), [])) for m in _ARXIV.finditer(reference.text)]
            identifiers += [(m.start(), m.end(), dois.get(_doi(m.group()), [])) for m in _DOI.finditer(reference.text)]
            hits = [(a, b, ids[0]) for a, b, ids in identifiers if len(ids) == 1]
            normalized, offsets = _normalized_with_offsets(reference.text)
            title_hits = []
            for title, ids in titles.items():
                for match in re.finditer(r'(?<!\w)' + re.escape(title) + r'(?!\w)', normalized):
                    title_hits.append((match.start(), match.end(), ids))
            # A complete longer title wins over a shorter title embedded in it.
            # A known identifier in a numbered entry wins over conflicting titles.
            if not (reference.label and hits):
                for a, b, ids in title_hits:
                    start, end = offsets[a], offsets[b-1]+1
                    if (len(ids) == 1 and _title_boundaries(reference.text, start, end)
                            and not any(c <= a and d >= b and d-c > b-a for c,d,_ in title_hits)):
                        hits.append((start, end, ids[0]))
            for start, end, target in hits:
                if target == source.id:
                    continue
                key = (source.id, target)
                if key in edges:
                    continue
                digest = hashlib.sha256(f'{source.id}:{target}:cites'.encode()).hexdigest()[:24]
                description, evidence = _excerpt(reference, start, end)
                edges[key] = {'id': 'citation-' + digest, 'source': source.id, 'target': target,
                              'relation': 'cites', 'relation_source': 'explicit',
                              'description': description, 'reference_label': reference.label,
                              'evidence': evidence}
    return list(edges.values())
