"""Recover derived section labels from the same PDF without replacing sources."""
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from .importing import MAX_PDF_BYTES, _recovered_section
from .pdf import InvalidPDF, parse_pdf


@dataclass(frozen=True)
class SourceSectionPlan:
    changes: dict[str, str | None]
    report: dict
    source_digest: str


def source_digest(chunks):
    values = sorted((chunk.id, chunk.paper_id, chunk.page, chunk.section, chunk.content,
                     chunk.bbox_json, chunk.page_width, chunk.page_height) for chunk in chunks)
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def pdf_matches(pdf_path, expected_sha256):
    if not pdf_path or not expected_sha256:
        return False
    try:
        path = Path(pdf_path)
        if path.stat().st_size > MAX_PDF_BYTES:
            return False
        data = path.read_bytes()
    except OSError:
        return False
    return len(data) <= MAX_PDF_BYTES and hashlib.sha256(data).hexdigest() == expected_sha256


def prepare_source_sections(pdf_path, expected_sha256, chunks):
    """Only exact identity/location matches can authorize a derived-label update."""
    report = {'version': 'stored-source-sections-v1', 'attempted': True, 'available': False,
              'complete': False, 'total_chunks': len(chunks), 'matched_chunks': 0,
              'changed_chunks': 0, 'unmatched_chunks': len(chunks), 'match_types': {}, 'changes': []}
    digest = source_digest(chunks)
    def unavailable(code):
        report['failure_code'] = code
        return SourceSectionPlan({}, report, digest)
    if not pdf_path or not expected_sha256:
        return unavailable('missing_pdf_identity')
    try:
        path = Path(pdf_path)
        if path.stat().st_size > MAX_PDF_BYTES:
            return unavailable('pdf_size_limit')
        data = path.read_bytes()
    except OSError:
        return unavailable('missing_pdf')
    if len(data) > MAX_PDF_BYTES:
        return unavailable('pdf_size_limit')
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        return unavailable('pdf_changed')
    try:
        parsed = parse_pdf(data)
    except InvalidPDF:
        return unavailable('parse_failure')
    report['available'] = True
    exact, dimensions = defaultdict(list), defaultdict(set)
    for block in parsed.blocks:
        exact[(block.page, block.content, tuple(block.bbox))].append(block)
        dimensions[block.page].add((block.page_width, block.page_height))
    changes, counts = {}, Counter()
    normalized = lambda text: re.sub(r'\s+', ' ', text).strip()
    for chunk in chunks:
        try:
            bounds = tuple(json.loads(chunk.bbox_json or '[]'))
        except (ValueError, TypeError):
            bounds = ()
        if (len(bounds) != 4 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in bounds)
                or not bounds[0] < bounds[2] or not bounds[1] < bounds[3]):
            counts['invalid_geometry'] += 1
            continue
        if dimensions.get(chunk.page) != {(chunk.page_width, chunk.page_height)}:
            counts['dimension_mismatch'] += 1
            continue
        candidates = exact.get((chunk.page, chunk.content, bounds), [])
        if len(candidates) > 1:
            counts['ambiguous'] += 1
            continue
        if candidates:
            section, kind = candidates[0].section, 'exact'
        else:
            recovered, section = _recovered_section(chunk, bounds, parsed)
            if not recovered:
                fragments = [block for block in parsed.blocks if block.page == chunk.page
                    and block.bbox[0] >= bounds[0] and block.bbox[1] >= bounds[1]
                    and block.bbox[2] <= bounds[2] and block.bbox[3] <= bounds[3]
                    and normalized(block.content) in normalized(chunk.content)]
                mixed = (fragments and normalized(' '.join(block.content for block in fragments)) == normalized(chunk.content)
                         and len({block.section for block in fragments}) > 1)
                counts['mixed' if mixed else 'unmatched'] += 1
                continue
            kind = 'recovered'
        counts[kind] += 1
        if section != chunk.section:
            changes[chunk.id] = section
            report['changes'].append({'chunk_id': chunk.id, 'before': chunk.section, 'after': section})
    report['matched_chunks'] = counts['exact'] + counts['recovered']
    report['unmatched_chunks'] = len(chunks) - report['matched_chunks']
    report['changed_chunks'] = len(changes)
    report['match_types'] = dict(counts)
    report['complete'] = report['unmatched_chunks'] == 0
    return SourceSectionPlan(changes, report, digest)
