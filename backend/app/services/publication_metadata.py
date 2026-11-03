"""Conservative, key-free publication enrichment for the background librarian.

Only fills empty, non-manual fields; never commits or calls a model. The report
and bounded TTL cache live as a JSON *string* in metadata_sources_json so the
existing dict[str, str] API and database need no migration. Publication year is
evidence in the report, never a replacement for an existing first-public year.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import quote

import httpx
import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Paper
from .downloads import normalize_arxiv_id
from .metadata import normalize_doi
from .pdf_metadata import CONFERENCE_PUBLICATION, TEMPLATE

_CACHE = '_publication_enrichment'
_VERSION = 1
_MAX_BYTES = 1024 * 1024
_MAX_REQUESTS = 3
_DEADLINE = 12.0
_FIELDS = ('year', 'venue', 'doi', 'arxiv_id')


def _object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or '{}')
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _clean(value, maximum=500) -> str:
    return re.sub(r'\s+', ' ', value).strip()[:maximum] if isinstance(value, str) else ''


def _title(value) -> str:
    return ' '.join(re.sub(r'[\W_]+', ' ', unicodedata.normalize('NFKC', _clean(value)).casefold()).split())


def _title_matches(left, right) -> bool:
    normalized = _title(left)
    return len(normalized) >= 30 and len(normalized.split()) >= 5 and normalized == _title(right)


def _venue(value, year=None) -> str | None:
    value = _clean(value, 200)
    if not value or TEMPLATE.search(value) or re.search(r'\b(?:arxiv|biorxiv|medrxiv|repository|preprints?)\b', value, re.I):
        return None
    if re.fullmatch(r'(?:advances in )?neural information processing systems', value, re.I):
        return 'NeurIPS' + (f' {year}' if _year(year) else '')
    return value


def _year(value) -> int | None:
    return value if type(value) is int and 1900 <= value <= 2200 else None


def _formal_doi(value) -> str | None:
    doi = normalize_doi(value) if isinstance(value, str) else None
    # The arXiv DOI identifies the preprint, not a conference publication.
    return doi if doi and not doi.startswith('10.48550/arxiv.') else None


def _front(paper: Paper) -> str:
    if not paper.pdf_path:
        return ''
    try:
        path = Path(paper.pdf_path)
        if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
            return ''
        with pymupdf.open(path) as document:
            return document[0].get_text()[:12000] if len(document) else ''
    except (OSError, RuntimeError, ValueError):
        return ''


def _fingerprint(paper: Paper, front: str, external: bool) -> str:
    sources = _object(paper.metadata_sources_json)
    return _digest({'version': _VERSION, 'external': external, 'id': paper.id,
        'title': paper.title, 'sha256': paper.sha256, 'front': front,
        'arxiv_version': paper.arxiv_version,
        'fields': {key: getattr(paper, key) for key in _FIELDS},
        'sources': {key: sources.get(key) for key in _FIELDS}})


@dataclass
class _Candidate:
    fields: dict
    source: str
    url: str
    fingerprint: str
    match: str


def _choose(records: list[dict], paper: Paper) -> dict | None:
    exact, titles = [], []
    doi, arxiv = normalize_doi(paper.doi), normalize_arxiv_id(paper.arxiv_id)
    for record in records:
        identifiers = record.get('arxiv_ids', set())
        known_doi = record.get('doi')
        # An explicit conflict cannot be rescued by a similar title.
        if doi and known_doi and doi != known_doi:
            continue
        if len(identifiers) > 1 or (arxiv and identifiers and arxiv not in identifiers):
            continue
        if (doi and doi == known_doi) or (arxiv and arxiv in identifiers):
            exact.append({**record, 'match': 'identifier'})
        elif _title_matches(paper.title, record.get('title')):
            titles.append({**record, 'match': 'title'})
    choices = exact or titles
    # Ambiguous duplicate bibliographic records are not safe title matches.
    unique = {record.get('doi') or record.get('id'): record for record in choices}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _openalex(payload, paper: Paper, url: str) -> _Candidate | None:
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        return None
    records = []
    for item in payload['results'][:5]:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get('id'), str) or not re.fullmatch(r'https://openalex\.org/W\d+', item['id']):
            continue
        primary = item.get('primary_location')
        locations = [primary] if isinstance(primary, dict) else []
        if isinstance(item.get('locations'), list):
            locations += [loc for loc in item['locations'] if isinstance(loc, dict)]
        arxiv_ids = {identifier for loc in locations for key in ('landing_page_url', 'pdf_url')
                     if isinstance(loc.get(key), str) and (identifier := normalize_arxiv_id(loc[key]))}
        venues = []
        for location in locations:
            source = location.get('source')
            if isinstance(source, dict) and source.get('type') in {'journal', 'conference', 'book series'}:
                if venue := _venue(source.get('display_name'), item.get('publication_year')):
                    venues.append(venue)
        records.append({'id': item.get('id'), 'title': item.get('title'),
            'doi': _formal_doi(item.get('doi')), 'year': _year(item.get('publication_year')),
            'arxiv_ids': arxiv_ids, 'venue': venues[0] if venues else None})
    selected = _choose(records, paper)
    if not selected:
        return None
    fields = {key: selected[key] for key in ('doi', 'year', 'venue') if selected.get(key)}
    if len(selected['arxiv_ids']) == 1:
        fields['arxiv_id'] = next(iter(selected['arxiv_ids']))
    return _Candidate(fields, 'openalex', url, _digest(payload), selected['match'])


def _crossref(payload, paper: Paper, url: str, expected_doi: str | None = None) -> _Candidate | None:
    if not isinstance(payload, dict) or not isinstance(payload.get('message'), dict):
        return None
    message = payload['message']
    items = [message] if expected_doi else message.get('items', [])
    if not isinstance(items, list):
        return None
    records = []
    for item in items[:5]:
        if not isinstance(item, dict) or not (doi := _formal_doi(item.get('DOI'))):
            continue
        if expected_doi and doi != expected_doi:
            continue
        titles, containers = item.get('title'), item.get('container-title')
        years = []
        for field in ('published-print', 'published-online', 'published', 'issued'):
            date = item.get(field)
            parts = date.get('date-parts') if isinstance(date, dict) else None
            if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                if year := _year(parts[0][0]):
                    years.append(year)
        records.append({'id': doi, 'doi': doi, 'title': titles[0] if isinstance(titles, list) and titles else None,
            'venue': _venue(containers[0], min(years) if years else None) if isinstance(containers, list) and containers else None,
            'year': min(years) if years else None})
    selected = _choose(records, paper)
    if not selected:
        return None
    return _Candidate({key: selected[key] for key in ('doi', 'venue', 'year') if selected.get(key)},
                      'crossref', url, _digest(payload), selected['match'])


def enrich_publication(session: Session, paper: Paper, *, client: httpx.Client | None = None,
                       allow_external: bool = True, force: bool = False, checkpoint_lock=None) -> dict:
    """Fill trustworthy missing publication metadata; caller owns the transaction.

    At most three fixed-host requests and a twelve-second network budget. The
    supplied HTTP client is useful for MockTransport tests and is never closed.
    Cache invalidates on metadata/manual-source/PDF-front-matter changes.
    """
    started, now = time.monotonic(), time.time()
    front = _front(paper)
    sources = _object(paper.metadata_sources_json)
    fingerprint = _fingerprint(paper, front, allow_external)
    cache = _object(sources.get(_CACHE))
    if (not force and cache.get('fingerprint') == fingerprint
            and isinstance(cache.get('expires_at'), (int, float))
            and now < cache['expires_at'] <= now + 8 * 86400):
        return {**cache, 'cached': True, 'changed': {}}
    report = {'status': 'not_found', 'changed': {}, 'provenance': [], 'warnings': [],
              'cached': False, 'fingerprint': fingerprint, 'checked_at': now, 'request_count': 0}

    def apply(candidate: _Candidate):
        evidence = {'source': candidate.source, 'url': candidate.url, 'fingerprint': candidate.fingerprint,
                    'match': candidate.match, 'fields': dict(candidate.fields)}
        if candidate.fields.get('year'):
            evidence['publication_year'] = candidate.fields['year']
        report['provenance'].append(evidence)
        for field, value in candidate.fields.items():
            if field not in _FIELDS or getattr(paper, field) is not None or sources.get(field) == 'manual':
                continue
            origin = candidate.source
            if field == 'year' and (arxiv := normalize_arxiv_id(paper.arxiv_id or candidate.fields.get('arxiv_id'))):
                code = int(arxiv.split('/')[-1][:2])
                value, origin = (1900 if code >= 91 else 2000) + code, 'arxiv_identifier'
            if field == 'doi':
                with session.no_autoflush:
                    duplicate = session.scalar(select(Paper.id).where(Paper.doi == value, Paper.id != paper.id))
                if duplicate:
                    report['warnings'].append('公开 DOI 已属于库中另一篇论文，已跳过该编号')
                    continue
            setattr(paper, field, value)
            sources[field] = origin
            report['changed'][field] = value

    for line in front.splitlines():
        if re.fullmatch(r'\s*(?:abstract|摘要)\s*', line, re.I):
            break
        if not TEMPLATE.search(line) and (match := CONFERENCE_PUBLICATION.fullmatch(line)):
            apply(_Candidate({'venue': match.group(1).strip()[:200], 'year': int(match.group(2))},
                'pdf_front_matter', paper.source_url or '', _digest(line), 'pdf_header'))
            break

    owned = client is None
    network = client or httpx.Client(transport=httpx.HTTPTransport(retries=0, trust_env=False),
                                    trust_env=False, follow_redirects=False)

    def fetch(url: str, params: dict | None = None):
        remaining = _DEADLINE - (time.monotonic() - started)
        if report['request_count'] >= _MAX_REQUESTS or remaining <= 0:
            return None, url

        report['request_count'] += 1
        try:
            timeout = httpx.Timeout(min(4.0, remaining), connect=min(2.0, remaining))
            with network.stream('GET', url, params=params, timeout=timeout, follow_redirects=False,
                headers={'Accept': 'application/json', 'User-Agent': 'PaperReaderPublicationMetadata/1'}) as response:
                actual_url = str(response.url)
                if response.status_code != 200:
                    report['warnings'].append(f'{response.url.host} 元数据查询未成功（HTTP {response.status_code}）')
                    return None, actual_url
                data = bytearray()
                for block in response.iter_bytes():
                    data.extend(block)
                    if len(data) > _MAX_BYTES or time.monotonic() - started > _DEADLINE:
                        report['warnings'].append('公开元数据响应超过大小或时间上限，已跳过')
                        return None, actual_url
                return json.loads(data), actual_url
        except (httpx.HTTPError, ValueError, OSError):
            report['warnings'].append('公开元数据服务暂不可用，已保留原有字段')
            return None, url

    def request(url: str, params: dict | None = None):
        nonlocal sources
        if checkpoint_lock is None:
            return fetch(url, params)
        # Do not hold SQLite's writer or the worker's checkpoint mutex during
        # a public metadata request. Rebase manual-source protection afterwards.
        paper.metadata_sources_json = json.dumps(sources, ensure_ascii=False)
        session.commit()
        checkpoint_lock.release()
        try:
            return fetch(url, params)
        finally:
            checkpoint_lock.acquire()
            session.expire_all()
            sources = _object(paper.metadata_sources_json)

    def missing():
        return any(getattr(paper, key) is None and sources.get(key) != 'manual' for key in ('year', 'venue', 'doi'))

    try:
        if allow_external:
            doi = _formal_doi(paper.doi)
            if doi:
                payload, url = request('https://api.crossref.org/works/' + quote(doi, safe=''))
                if candidate := _crossref(payload, paper, url, doi):
                    apply(candidate)
            if not doi or missing():
                payload, url = request('https://api.openalex.org/works', {'search': paper.title[:320], 'per-page': 5})
                if candidate := _openalex(payload, paper, url):
                    apply(candidate)
            if missing():
                payload, url = request('https://api.crossref.org/works', {'query.title': paper.title[:320], 'rows': 5})
                if candidate := _crossref(payload, paper, url):
                    apply(candidate)
    finally:
        if owned:
            network.close()
    report['warnings'] = list(dict.fromkeys(report['warnings']))
    report['status'] = 'enriched' if report['changed'] else 'verified' if report['provenance'] else 'unavailable' if report['warnings'] else 'not_found'
    # Include the newly filled fields/sources in the cache key, so the very
    # next pass is idempotent while any later user correction invalidates it.
    paper.metadata_sources_json = json.dumps(sources, ensure_ascii=False)
    report['fingerprint'] = _fingerprint(paper, front, allow_external)
    ttl = 900 if report['warnings'] else 7 * 86400 if report['provenance'] else 6 * 3600
    report['expires_at'] = now + ttl
    sources[_CACHE] = json.dumps(report, ensure_ascii=False)
    paper.metadata_sources_json = json.dumps(sources, ensure_ascii=False)
    return report
