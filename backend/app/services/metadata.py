"""Bibliographic enrichment from arXiv citation metadata/Atom and Crossref records."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
import re
from urllib.parse import quote
import xml.etree.ElementTree as ET

from fastapi import HTTPException
import httpx

from .downloads import Resolver, fetch_public, normalize_arxiv_id

DOI = re.compile(r'10\.\d{4,9}/[^\s<>]+', re.I)
METADATA_LIMIT = 2 * 1024 * 1024


@dataclass
class MetadataResult:
    fields: dict[str, object] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', value.strip(), flags=re.I)
    return value.lower() if len(value) <= 200 and DOI.fullmatch(value) else None


def _year(value: str | None) -> int | None:
    match = re.search(r'\b((?:19|20|21)\d{2})\b', value or '')
    return int(match.group(1)) if match else None


def _clean(value: str, maximum: int = 500) -> str:
    return re.sub(r'\s+', ' ', value).strip()[:maximum]


def _trusted_origin(value: str, hosts: set[str]) -> bool:
    url = httpx.URL(value)
    return url.scheme == 'https' and url.host.rstrip('.').lower() in hosts and url.port in {None, 443}


class CitationHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        name = (values.get('name') or '').lower()
        content = values.get('content')
        if tag.lower() == 'meta' and name.startswith('citation_') and content:
            self.tags.setdefault(name, []).append(_clean(content, 10000))


def _arxiv_html(data: bytes, identifier: str) -> dict[str, object]:
    parser = CitationHTML()
    text = data.decode('utf-8', errors='replace')
    parser.feed(text)
    tags = parser.tags
    first = lambda name: tags.get(name, [None])[0]
    claimed_id = first('citation_arxiv_id')
    if normalize_arxiv_id(claimed_id) != identifier:
        return {}
    if not first('citation_title') or not tags.get('citation_author'):
        return {}
    authors = []
    for name in tags['citation_author']:
        parts = name.split(',', 1)
        authors.append(_clean(parts[1] + ' ' + parts[0], 200) if len(parts) == 2 else _clean(name, 200))
    authors = [name for name in authors if name]
    if not authors:
        return {}
    fields: dict[str, object] = {'title': _clean(first('citation_title')), 'authors': authors, 'arxiv_id': identifier}
    # citation_date is first submission; citation_online_date is latest revision.
    submission = re.search(r'\[v1\](?:<[^>]+>|\s)*([^<]{1,100})', text)
    year = _year(submission.group(1) if submission else None) or _year(first('citation_date'))
    if year:
        fields['year'] = year
    venue = first('citation_journal_title') or first('citation_conference_title')
    if venue:
        fields['venue'] = _clean(venue, 200)
    doi = normalize_doi(first('citation_doi'))
    if doi:
        fields['doi'] = doi
    return fields


def _arxiv_atom(data: bytes, identifier: str) -> dict[str, object]:
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        return {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    ns = {'a': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
    for entry in root.findall('a:entry', ns):
        if normalize_arxiv_id(entry.findtext('a:id', namespaces=ns)) != identifier:
            continue
        title = entry.findtext('a:title', namespaces=ns)
        authors = [_clean(author.findtext('a:name', default='', namespaces=ns), 200) for author in entry.findall('a:author', ns)]
        authors = [name for name in authors if name]
        if not title or not authors:
            return {}
        fields: dict[str, object] = {'title': _clean(title), 'authors': authors, 'arxiv_id': identifier}
        year = _year(entry.findtext('a:published', namespaces=ns))
        if year:
            fields['year'] = year
        venue = entry.findtext('arxiv:journal_ref', namespaces=ns)
        if venue:
            fields['venue'] = _clean(venue, 200)
        doi = normalize_doi(entry.findtext('arxiv:doi', namespaces=ns))
        if doi:
            fields['doi'] = doi
        return fields
    return {}


def _crossref(data: bytes, doi: str) -> dict[str, object]:
    try:
        item = json.loads(data).get('message', {})
        if not isinstance(item, dict) or normalize_doi(item.get('DOI')) != doi:
            return {}
        fields: dict[str, object] = {'doi': doi}
        titles = item.get('title')
        if isinstance(titles, list) and titles and isinstance(titles[0], str):
            fields['title'] = _clean(titles[0])
        authors = [_clean(' '.join(str(author.get(key) or '') for key in ('given', 'family')), 200) for author in item.get('author', []) if isinstance(author, dict)]
        if any(authors):
            fields['authors'] = [name for name in authors if name]
        venues = item.get('container-title')
        if isinstance(venues, list) and venues and isinstance(venues[0], str):
            fields['venue'] = _clean(venues[0], 200)
        years = []
        for field_name in ('published-print', 'published-online', 'published', 'issued'):
            record = item.get(field_name, {})
            parts = record.get('date-parts') if isinstance(record, dict) else None
            if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0] and isinstance(parts[0][0], int) and 1900 <= parts[0][0] <= 2200:
                years.append(parts[0][0])
        if years:
            fields['year'] = min(years)
        return fields
    except (ValueError, TypeError, AttributeError):
        return {}


def enrich_metadata(*, arxiv_id: str | None = None, doi: str | None = None, transport: httpx.BaseTransport | None = None, resolver: Resolver | None = None) -> MetadataResult:
    result = MetadataResult()
    identifier = normalize_arxiv_id(arxiv_id)
    normalized_doi = normalize_doi(doi)
    if identifier:
        fields = {}
        try:
            response = fetch_public('https://arxiv.org/abs/' + identifier, max_bytes=METADATA_LIMIT, timeout=8.0, deadline=12.0, transport=transport, resolver=resolver)
            if _trusted_origin(response.url, {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}):
                fields = _arxiv_html(response.data, identifier)
        except HTTPException:
            pass
        if not fields or not fields.get('year'):
            try:
                response = fetch_public('https://export.arxiv.org/api/query?id_list=' + quote(identifier, safe=''), max_bytes=METADATA_LIMIT, timeout=8.0, deadline=12.0, transport=transport, resolver=resolver)
                atom = _arxiv_atom(response.data, identifier) if _trusted_origin(response.url, {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}) else {}
                fields = {**fields, **atom}
            except HTTPException:
                pass
        if fields:
            result.fields.update(fields)
            result.sources.update({name: 'arxiv' for name in fields})
            normalized_doi = normalized_doi or normalize_doi(fields.get('doi'))
        else:
            result.warnings.append('arXiv 元数据服务暂不可用，已保留 PDF 中的识别结果')
    if normalized_doi:
        fields = {}
        try:
            response = fetch_public('https://api.crossref.org/works/' + quote(normalized_doi, safe=''), max_bytes=METADATA_LIMIT, timeout=8.0, deadline=12.0, transport=transport, resolver=resolver)
            if _trusted_origin(response.url, {'api.crossref.org'}):
                fields = _crossref(response.data, normalized_doi)
        except HTTPException:
            pass
        if fields:
            # Keep first-submission year/title/authors for arXiv; Crossref can fill venue/DOI.
            for name, value in fields.items():
                if name not in result.fields:
                    result.fields[name] = value
                    result.sources[name] = 'crossref'
        else:
            result.warnings.append('Crossref DOI 元数据暂不可用，已保留现有识别结果')
    return result
