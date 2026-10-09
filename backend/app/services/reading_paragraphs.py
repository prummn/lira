"""Derived reading paragraphs; stored sources and evidence coordinates stay immutable."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from statistics import median

import pymupdf as fitz

from .pdf_metadata import body_font, read_lines, section_reading_order


def prose_text(source: str) -> str:
    # Join PDF line wrapping, preserving compound prefixes and paragraph breaks.
    source = re.sub(r'(?i)\b(self|multi|cross|English|encoder|decoder|sequence|point)-\n', r'\1-', source)
    source = re.sub(r'(?<=[a-z])[-\u00ad]\n(?=[a-z])', '', source)
    return re.sub(r'\s+', ' ', source).strip()


def _bbox(chunk):
    try:
        bounds = json.loads(chunk.bbox_json or 'null')
        if bounds and len(bounds) == 4 and bounds[0] < bounds[2] and bounds[1] < bounds[3]:
            return bounds
    except (ValueError, TypeError):
        pass
    return None


def _heading(text: str, section: str | None):
    clean = lambda value: re.sub(r'^\d+(?:\.\d+)*\.?\s*', '', prose_text(value)).casefold()
    return bool(section and clean(text) == clean(section)) or bool(re.fullmatch(r'\d+(?:\.\d+)*\.?', text.strip()))


def _read_layout(path: Path | None):
    if not path or not path.is_file():
        return {}, {}
    try:
        with fitz.open(path) as document:
            layouts, ranks = {}, {}
            for page_index, page in enumerate(document):
                raw = page.get_text('dict', sort=True)['blocks']
                lines = read_lines(page_index, raw)
                layouts[page_index + 1] = lines
                order = section_reading_order(raw, lines, page.cropbox.width, body_font(lines))
                ranks[page_index + 1] = {key: rank for rank, key in enumerate(order)}
            return layouts, ranks
    except (OSError, RuntimeError, ValueError):
        return {}, {}


def _matched_lines(chunk, lines):
    bounds = _bbox(chunk)
    if not bounds:
        return []
    matched = [line for line in lines if bounds[0] - 1 <= line.bbox[0] and line.bbox[2] <= bounds[2] + 1
               and bounds[1] - 1 <= line.bbox[1] and line.bbox[3] <= bounds[3] + 1]
    # Overlapping superscripts may belong to another block inside the same bounds.
    # Only an exact source match authorizes splitting or refining source geometry.
    if '\n'.join(line.text for line in matched) == chunk.content:
        return matched
    by_block = {}
    for line in matched:
        by_block.setdefault(line.key[1], []).append(line)
    return next((group for group in by_block.values() if '\n'.join(line.text for line in group) == chunk.content), [])


def _observed_lines(chunk, lines):
    bounds = _bbox(chunk)
    if not bounds:
        return []
    # Partial matches can establish order and typography, never new source bounds.
    return [line for line in lines if line.text in chunk.content
            and bounds[1] - 1 <= line.bbox[1] and line.bbox[3] <= bounds[3] + 1]


def _math_chunks(chunks):
    seeds = [chunk for chunk in chunks if re.search(r'[=∈√∑∏×≤≥±∞]', chunk.content)]
    result = {chunk.id for chunk in seeds}
    for chunk in chunks:
        bounds = _bbox(chunk)
        if len(chunk.content) >= 35 or not bounds:
            continue
        for seed in seeds:
            other = _bbox(seed)
            if (other and seed.page == chunk.page and seed.section == chunk.section
                    and min(bounds[3], other[3]) - max(bounds[1], other[1]) > 0):
                result.add(chunk.id)
                break
    return result


def _math_continuation(previous, current):
    if not current['_math'] or previous['kind'] != 'prose' or previous['section'] != current['section']:
        return False
    a, b = previous['anchors'][-1], current['anchors'][0]
    if a['page'] != b['page'] or not a['bbox'] or not b['bbox'] or len(previous['source_text']) + len(current['source_text']) > 12000:
        return False
    horizontal_gap = max(a['bbox'][0] - b['bbox'][2], b['bbox'][0] - a['bbox'][2], 0)
    if horizontal_gap > 22:
        return False
    overlap = min(a['bbox'][3], b['bbox'][3]) - max(a['bbox'][1], b['bbox'][1])
    gap = b['bbox'][1] - a['bbox'][3]
    return overlap > 0 or (0 <= gap <= 35 and previous['text'].endswith(':')) or (previous['_math'] and 0 <= gap <= 9)


def _piece_position(source, anchor, lines):
    exact = [line for line in lines if line.text in source]
    if exact:
        top = min(line.bbox[1] for line in exact)
        row = [line for line in exact if line.bbox[1] - top <= max(4, line.size * .8)]
        return top, min(line.bbox[0] for line in row), max(line.size for line in row)
    bounds = anchor['bbox']
    return (bounds[1], bounds[0], 10) if bounds else (100000, 0, 10)


def _ordered_pieces(pieces):
    # The PDF's block list can put WK after WV because of tiny superscript
    # differences in y. Read neighboring fragments on one row from left to
    # right; preserve full source fragments, without reconstructing math.
    rows = []
    for piece in pieces:
        top, _, size = piece['position']
        if (rows and piece['anchor']['page'] == rows[-1][0]['anchor']['page']
                and abs(top - rows[-1][0]['position'][0]) <= max(size, rows[-1][0]['position'][2]) * .8):
            rows[-1].append(piece)
        else:
            rows.append([piece])
    return [piece for row in rows for piece in sorted(row, key=lambda value: value['position'][1])]


def _ranges(chunk, lines):
    if not lines:
        return [(0, len(chunk.content), _bbox(chunk))]
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line.text) + 1
    advances = [b.bbox[1] - a.bbox[1] for a, b in zip(lines, lines[1:]) if b.bbox[1] > a.bbox[1] + 2]
    advance = median(advances) if advances else 12
    left = min(line.bbox[0] for line in lines)
    cuts = [0]
    for index in range(1, len(lines)):
        previous, current = lines[index - 1], lines[index]
        ends_sentence = bool(re.search(r'[.!?。！？][\]”"\')]*$', previous.text))
        indentation = current.bbox[0] - left >= max(6, current.size * .55)
        gap = current.bbox[1] - previous.bbox[1] > advance * 1.45
        if ends_sentence and (indentation or gap) and current.bbox[1] > previous.bbox[1] + 2:
            cuts.append(index)
    cuts.append(len(lines))
    result = []
    for first, last in zip(cuts, cuts[1:]):
        group = lines[first:last]
        bounds = [min(line.bbox[0] for line in group), min(line.bbox[1] for line in group),
                  max(line.bbox[2] for line in group), max(line.bbox[3] for line in group)]
        result.append((offsets[first], offsets[last] - 1 if last < len(lines) else len(chunk.content), bounds))
    return result


def _continuation(previous, current, *, first_prose_on_page=False):
    if previous['kind'] != 'prose' or current['kind'] != 'prose' or previous['section'] != current['section']:
        return False
    if re.search(r'[.!?:;。！？：；][\]”"\')]*$', previous['text']) or not re.match(r'^[a-z]', current['text']):
        return False
    a, b = previous['anchors'][-1], current['anchors'][0]
    if not a['bbox'] or not b['bbox'] or len(previous['source_text']) + len(current['source_text']) > 12000:
        return False
    if abs(a['bbox'][0] - b['bbox'][0]) > 15:
        return False
    if a['page'] == b['page']:
        return -2 <= b['bbox'][1] - a['bbox'][3] <= 22
    return b['page'] == a['page'] + 1 and a['bbox'][3] > (a['page_height'] or 800) * .75 and (first_prose_on_page or b['bbox'][1] < (b['page_height'] or 800) * .24)


def build_reading_paragraphs(chunks, pdf_path: Path | str | None = None, *, title: str = '') -> list[dict]:
    """Split on observed paragraph layout and join only clear sentence continuations."""
    layouts, ranks = _read_layout(Path(pdf_path) if pdf_path else None)
    matched = {chunk.id: _matched_lines(chunk, layouts.get(chunk.page, [])) for chunk in chunks}
    observed = {chunk.id: matched[chunk.id] or _observed_lines(chunk, layouts.get(chunk.page, [])) for chunk in chunks}
    math_chunks = _math_chunks(chunks)
    def order(chunk):
        lines = observed[chunk.id]
        rank = ranks.get(chunk.page, {}).get(lines[0].key[1]) if lines else None
        if rank is None and lines:
            rank = min((ranks.get(chunk.page, {}).get(line.key[1], 100000) for line in lines), default=None)
        bounds = _bbox(chunk)
        if rank is None and bounds and layouts.get(chunk.page):
            # Place an unrecognized block beside the nearest observed text rather
            # than sending it after every matched block on the page.
            closest = min(layouts[chunk.page], key=lambda line: abs(line.bbox[1]-bounds[1]) + abs(line.bbox[0]-bounds[0])*.2)
            rank = ranks.get(chunk.page, {}).get(closest.key[1], 100000)
        return chunk.page or 1, rank if rank is not None else (bounds[1] if bounds else 100000), chunk.id
    paragraphs = []
    prose_pages = set()
    ordered_chunks = _ordered_pieces([
        {'chunk': chunk, 'anchor': {'page': chunk.page or 1, 'bbox': _bbox(chunk)},
         'position': _piece_position(chunk.content, {'bbox': _bbox(chunk)}, observed[chunk.id])}
        for chunk in sorted(chunks, key=order)
    ])
    for piece in ordered_chunks:
        chunk = piece['chunk']
        raw = chunk.content.strip()
        if not raw or _heading(raw, chunk.section) or prose_text(raw) == title:
            continue
        bounds = _bbox(chunk)
        lines = observed[chunk.id]
        page_body_size = body_font(layouts.get(chunk.page, []))
        footnote = bool(lines and median(line.size for line in lines) < page_body_size * .94 and bounds and bounds[1] > (chunk.page_height or 800) * .82)
        is_math = chunk.id in math_chunks
        if (footnote or re.match(r'^[∗*†‡]', raw) or (len(raw) < 35 and not is_math) or '@' in raw or re.match(r'^(?:arXiv:|Provided proper attribution|Copyright|Permission to)', raw, re.I)
                or (not chunk.section and chunk.page == 1 and len(raw) < 120)
                or (bounds and bounds[1] > (chunk.page_height or 800) * .92)):
            continue
        for start, end, bbox in _ranges(chunk, matched[chunk.id]):
            source = chunk.content[start:end]
            if not source.strip():
                continue
            kind = 'caption' if re.match(r'^(Figure|Fig\.|Table|图|表)\s*\d', source, re.I) else 'prose'
            item = {'section': chunk.section, 'kind': kind, 'source_text': source, 'text': prose_text(source), '_math': is_math and len(source) < 150,
                    'refs': [{'chunk_id': chunk.id, 'start': start, 'end': end}],
                    'anchors': [{'chunk_id': chunk.id, 'page': chunk.page or 1, 'bbox': bbox,
                                 'page_width': chunk.page_width, 'page_height': chunk.page_height}]}
            item['_pieces'] = [{'source': source, 'ref': item['refs'][0], 'anchor': item['anchors'][0],
                                'position': _piece_position(source, item['anchors'][0], lines)}]
            previous = paragraphs[-1] if paragraphs else None
            first_prose = kind == 'prose' and chunk.page not in prose_pages
            if first_prose:
                # Figures may precede the continued sentence on the following page.
                previous = next((value for value in reversed(paragraphs) if value['kind']=='prose'), None)
            if previous and (_math_continuation(previous, item) or _continuation(previous, item, first_prose_on_page=first_prose)):
                previous['source_text'] += '\n' + source
                previous['text'] = prose_text(previous['source_text'])
                previous['refs'].extend(item['refs'])
                previous['anchors'].extend(item['anchors'])
                previous['_math'] = item['_math']
                previous['_pieces'].extend(item['_pieces'])
            else:
                paragraphs.append(item)
            if kind == 'prose':
                prose_pages.add(chunk.page)
    for item in paragraphs:
        item.pop('_math')
        pieces = _ordered_pieces(item.pop('_pieces'))
        item['source_text'] = '\n'.join(piece['source'] for piece in pieces)
        item['text'] = prose_text(item['source_text'])
        item['refs'] = [piece['ref'] for piece in pieces]
        item['anchors'] = [piece['anchor'] for piece in pieces]
        identity = json.dumps([item['refs'], item['source_text']], ensure_ascii=False, sort_keys=True)
        item['id'] = 'paragraph-' + hashlib.sha256(identity.encode()).hexdigest()[:24]
    return paragraphs


def paragraphs_for(paper):
    return build_reading_paragraphs(list(paper.chunks), paper.pdf_path, title=paper.title)


def reading_payload(paper, provider=None):
    paragraphs = paragraphs_for(paper)
    translations = {}
    for item in paragraphs:
        anchor = item['refs'][0]['chunk_id']
        cached = [translation for translation in paper.translations
                  if translation.chunk_id == anchor and translation.source_text == item['source_text']]
        if provider is not None and provider.translation_available:
            cached = [record for record in cached if record.provider == provider.name
                      and record.config_version == provider.translation_configuration_version
                      and record.prompt_version == provider.translation_prompt_version]
        if cached:
            latest = max(cached, key=lambda record: (record.created_at, record.id))
            translations[item['id']] = {'text': latest.text, 'model': latest.model_version}
    return {'paragraphs': [{key: value for key, value in item.items() if key != 'refs'} for item in paragraphs],
            'translations': translations}
