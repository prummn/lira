"""Derived reading paragraphs; stored sources and evidence coordinates stay immutable."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from statistics import median

import pymupdf as fitz

from .pdf_metadata import body_font, read_lines, section_reading_order
from .translations import translation_error
from .visual_regions import CAPTION, visual_regions_for_pdf

MATH_GLYPHS = re.compile(r"[=∈√∑∏×≤≥±∞∂∇∫≈≠∝÷−\uf000-\uf0ff]")


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


def _layout_artifact(raw: str, lines, page_body_size: float, *, caption: bool = False, annotation: bool = False) -> bool:
    """Recognize blocks emitted by PDF layout for tables, footnotes and chrome.

    These blocks are useful as source evidence, but they must not become prose
    paragraphs: doing so breaks continuation across a page where a figure or
    table sits between two lines of the same sentence.
    """
    if re.match(r'^Published as a conference paper at\b', raw, re.I):
        return True
    # Superscript footnote markers are often extracted as a leading lower-case
    # letter or digit with no separating whitespace (``aHotpotQA``/``2We``).
    small_type = bool(lines and median(line.size for line in lines) < page_body_size * .94)
    if re.match(r'^(?:\d+|[a-z])(?=[A-Z(])', raw) and len(raw) < 220 and (small_type or annotation):
        return True
    if caption:
        return False
    if MATH_GLYPHS.search(raw):
        return False
    if lines:
        typical = median(line.size for line in lines)
        # Table headings/rows in two-column papers are consistently smaller than
        # body text. Keep equations and normal prose eligible for math handling.
        if typical < page_body_size * .84 and len(raw) >= 35:
            return True
    # Without a PDF layout (for example in a derived test or a repaired import),
    # compact multi-line blocks still reveal table/figure internals: several
    # short labels with no sentence punctuation are not running prose.
    compact_lines = raw.splitlines()
    if (len(compact_lines) >= 3 and max(map(len, compact_lines)) <= 45
            and not re.search(r'[.!?。！？][\]”"\')]*$', raw)):
        return True
    return False


def _read_layout(path: Path | None):
    if not path or not path.is_file():
        return {}, {}
    try:
        stat = path.stat()
        return _cached_layout(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
    except OSError:
        return {}, {}


@lru_cache(maxsize=8)
def _cached_layout(path: str,modified_ns: int,size: int):
    try:
        with fitz.open(path) as document:
            layouts, ranks = {}, {}
            for page_index, page in enumerate(document):
                raw = page.get_text('dict', sort=True)['blocks']
                lines = read_lines(page_index, raw)
                layouts[page_index + 1] = lines
                order = section_reading_order(raw, lines, page.cropbox.width, body_font(lines), require_overlap=False)
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
    seeds = [chunk for chunk in chunks if MATH_GLYPHS.search(chunk.content)]
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
    # Raised symbols can precede the whole prose block in the PDF's block order.
    # Reorder only adjacent, physically overlapping blocks; the surrounding
    # column/section reading order must remain intact.
    def raised_operator(piece):
        text = piece['source'] if 'source' in piece else piece['chunk'].content
        return len(text.strip()) <= 8 and bool(re.search(r'[√∑∏∫∮∐⋃⋂]', text))
    groups = []
    for piece in pieces:
        bounds = piece['anchor']['bbox']
        overlaps = bool(groups and bounds and any(
            other['anchor']['page'] == piece['anchor']['page']
            and (raised_operator(piece) or raised_operator(other))
            and (box := other['anchor']['bbox'])
            and min(bounds[2], box[2]) > max(bounds[0], box[0])
            and min(bounds[3], box[3]) > max(bounds[1], box[1])
            for other in groups[-1]))
        if overlaps:
            groups[-1].append(piece)
        else:
            groups.append([piece])
    pieces = [piece for group in groups for piece in sorted(group, key=lambda value: value['position'][:2])]
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
        ends_sentence = _ends_sentence(previous.text)
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


def _ends_sentence(text):
    # A PDF usually emits a superscript footnote as a normal digit. It is not
    # the beginning of a new sentence, nor evidence of an unfinished sentence.
    return bool(re.search(r'[.!?。！？][\]”"\')]*(?:\d{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰*†‡]+)?$', text))


def _typography(source, lines, page_lines):
    exact = [line for line in lines if line.text in source]
    if not exact:
        return None
    first = min(exact, key=lambda line: (line.bbox[1], line.bbox[0]))
    last = max(exact, key=lambda line: (line.bbox[1], line.bbox[2]))
    # Estimate the margin from this text column, excluding small footnotes,
    # full-width headings and unrelated fragments in the opposite column.
    source_left = min(line.bbox[0] for line in exact)
    column = [line for line in page_lines if line.horizontal and len(line.text) >= 30
              and abs(line.bbox[0] - source_left) < 24
              and line.size >= first.size * .94]
    margin = min((line.bbox[0] for line in column), default=min(line.bbox[0] for line in exact))
    advances = [b.bbox[1] - a.bbox[1] for a,b in zip(exact,exact[1:])
                if 2 < b.bbox[1] - a.bbox[1] < first.size * 2]
    return {'indented': first.bbox[0] - margin >= max(6,first.size * .55),
            'first': first.bbox, 'last': last.bbox,
            'advance': median(advances) if advances else first.size * 1.22}


def _flow(previous, current):
    """Describe adjacent reading fragments without confusing columns with rows."""
    a, b = previous['anchors'][-1], current['anchors'][0]
    if not a['bbox'] or not b['bbox']:
        return None
    x, y = a['bbox'], b['bbox']
    width = a['page_width'] or 612
    aligned = abs(x[0]-y[0]) <= 22
    overlap = min(x[2],y[2]) - max(x[0],y[0])
    same_column = aligned or overlap >= min(x[2]-x[0],y[2]-y[0]) * .55
    if a['page'] == b['page']:
        if same_column:
            return 'same'
        if x[2] <= width * .52 and y[0] >= width * .48 and y[1] < x[1] - 2:
            return 'column'
    elif b['page'] == a['page'] + 1:
        # The last column of one page wraps to the first column of the next.
        wrap = x[0] >= width * .48 and y[2] <= (b['page_width'] or width) * .52
        if same_column or wrap:
            return 'page'
    return None


def _continuation(previous, current, *, first_prose_on_page=False):
    if previous['kind'] != 'prose' or current['kind'] != 'prose' or previous['section'] != current['section']:
        return False
    flow = _flow(previous,current)
    if flow is None:
        return False
    current_layout = current.get('_layout')
    previous_layout = previous.get('_layout')
    if (flow == 'same' and current_layout and previous_layout
            and current_layout['indented'] and previous['_math']):
        first, last = current_layout['first'], previous_layout['last']
        height = min(first[3] - first[1], last[3] - last[1])
        # A fragment starting after an inline formula is not a new indented
        # paragraph. Compare the actual boundary lines, not whole-block boxes.
        if (previous['anchors'][-1]['page'] == current['anchors'][0]['page']
                and abs(first[1] - last[1]) <= height * .5
                and min(first[3], last[3]) - max(first[1], last[1]) >= height * .5
                and -2 <= first[0] - last[2] <= 22):
            return True
    if current_layout and current_layout['indented']:
        return False
    # A completed sentence is a hard paragraph boundary. Footnote markers such
    # as ``Sims.2`` belong to the sentence and must never cause the next
    # paragraph to be pulled backward into it.
    if _ends_sentence(previous['text']):
        return False
    unfinished = not previous['text'].endswith((':',';','：','；'))
    if not unfinished and not (current_layout and not current_layout['indented']):
        return False
    if not re.match(r'^[a-z]', current['text']) and current_layout is None:
        return False
    # A merged paragraph can contain several overlapping inline fragments. The
    # last item in ``anchors`` is their visual sort order, not necessarily the
    # fragment on the lowest line, so choose geometry by vertical position.
    previous_anchors = [anchor for anchor in previous['anchors'] if anchor.get('bbox')]
    current_anchors = [anchor for anchor in current['anchors'] if anchor.get('bbox')]
    if not previous_anchors or not current_anchors:
        return False
    tail = previous_anchors[-1]
    tail_column = [anchor for anchor in previous_anchors if anchor['page'] == tail['page']
                   and min(anchor['bbox'][2],tail['bbox'][2])-max(anchor['bbox'][0],tail['bbox'][0]) > 0]
    a = max(tail_column, key=lambda anchor: (anchor['bbox'][3],anchor['bbox'][2]))
    b = min(current_anchors, key=lambda anchor: (anchor['page'], anchor['bbox'][1], anchor['bbox'][0]))
    if not a['bbox'] or not b['bbox'] or len(previous['source_text']) + len(current['source_text']) > 12000:
        return False
    if a['page'] == b['page']:
        # PDF extractors split inline math and italic glyphs into overlapping
        # blocks. Their left edges can differ substantially even though the
        # blocks occupy the same visual line (for example ``a_i`` followed by
        # ``i+1`` in Reflexion's Self-reflection paragraph). Treat a lowercase
        # fragment that overlaps the previous line as a continuation before
        # applying the usual column-alignment guard.
        vertical_overlap = min(a['bbox'][3], b['bbox'][3]) - max(a['bbox'][1], b['bbox'][1])
        if flow == 'same' and vertical_overlap > 0 and b['bbox'][1] <= a['bbox'][3] + 18:
            return True
        if flow == 'column':
            return True
        gap = b['bbox'][1] - a['bbox'][3]
        if current_layout and not unfinished:
            return -2 <= gap <= current_layout['advance'] * .55
        return flow == 'same' and -2 <= gap <= 22
    return flow == 'page' and a['bbox'][3] > (a['page_height'] or 800) * .70 and (first_prose_on_page or b['bbox'][1] < (b['page_height'] or 800) * .24)


def _bridge_continuation(previous, current):
    """Join prose separated by a figure/table caption or another non-prose block.

    A caption is a visual interruption, not a paragraph boundary. The old
    parser only considered the immediately preceding item, so a sentence that
    resumed below an inline figure stayed split. The lowercase continuation
    cue and column-aligned geometry keep this bridge conservative.
    """
    if (previous['kind'] != 'prose' or current['kind'] != 'prose'
            or previous['section'] != current['section']
            or _ends_sentence(previous['text']) or previous['text'].endswith((':',';','：','；'))
            or (not re.match(r'^[a-z]', current['text']) and current.get('_layout') is None)
            or (current.get('_layout') and current['_layout']['indented'])):
        return False
    a, b = previous['anchors'][-1], current['anchors'][0]
    flow = _flow(previous,current)
    if not a['bbox'] or not b['bbox'] or flow is None:
        return False
    if a['page'] == b['page']:
        if flow == 'column':
            return True
        gap = b['bbox'][1] - a['bbox'][3]
        return b['bbox'][1] > a['bbox'][1] and 0 <= gap <= max(220, (a['page_height'] or 800) * .58)
    if b['page'] != a['page'] + 1:
        return False
    return (a['bbox'][3] > (a['page_height'] or 800) * .62
            and b['bbox'][1] < (b['page_height'] or 800) * .40)


def _source_order(chunk, lines, layouts, ranks):
    rank = ranks.get(chunk.page, {}).get(lines[0].key[1]) if lines else None
    if rank is None and lines:
        rank = min((ranks.get(chunk.page, {}).get(line.key[1], 100000) for line in lines), default=None)
    bounds = _bbox(chunk)
    if rank is None and bounds and layouts.get(chunk.page):
        # Approximate order without authorizing any change to source geometry.
        closest = min(layouts[chunk.page], key=lambda line: abs(line.bbox[1]-bounds[1]) + abs(line.bbox[0]-bounds[0])*.2)
        rank = ranks.get(chunk.page, {}).get(closest.key[1], 100000)
    return chunk.page or 1, rank if rank is not None else (bounds[1] if bounds else 100000), chunk.id


def ordered_source_chunks(chunks, pdf_path: Path | str | None = None):
    """Order immutable source blocks by observed PDF columns and section bands."""
    layouts, ranks = _read_layout(Path(pdf_path) if pdf_path else None)
    return sorted(chunks, key=lambda chunk: _source_order(chunk,
        _matched_lines(chunk, layouts.get(chunk.page, [])) or _observed_lines(chunk, layouts.get(chunk.page, [])),
        layouts, ranks))


def build_reading_paragraphs(chunks, pdf_path: Path | str | None = None, *, title: str = '') -> list[dict]:
    """Split on observed paragraph layout and join only clear sentence continuations."""
    layouts, ranks = _read_layout(Path(pdf_path) if pdf_path else None)
    visual_captions = {(region['page'], prose_text(region['caption']))
                       for region in visual_regions_for_pdf(pdf_path)} if pdf_path else set()
    matched = {chunk.id: _matched_lines(chunk, layouts.get(chunk.page, [])) for chunk in chunks}
    observed = {chunk.id: matched[chunk.id] or _observed_lines(chunk, layouts.get(chunk.page, [])) for chunk in chunks}
    math_chunks = _math_chunks(chunks)
    def order(chunk):
        return _source_order(chunk, observed[chunk.id], layouts, ranks)
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
        section = chunk.section
        previous_prose = next((p for p in reversed(paragraphs) if p['kind'] == 'prose'),None)
        if (section is None and previous_prose and previous_prose['section'] == 'Abstract'
                and re.match(r'^[a-z]',raw) and not _ends_sentence(previous_prose['text'])
                and _flow(previous_prose,{'anchors':[{'page':chunk.page,'bbox':bounds,'page_width':chunk.page_width,'page_height':chunk.page_height}]}) in {'column','page'}):
            section = 'Abstract'
        page_body_size = body_font(layouts.get(chunk.page, []))
        is_math = chunk.id in math_chunks
        # A body sentence may begin with a figure reference. Require verified
        # visual context, a caption delimiter, or smaller caption typography.
        caption_like = bool(CAPTION.match(prose_text(raw))) and (
            (chunk.page, prose_text(raw)) in visual_captions
            or bool(re.match(r'^(?:Figure|Fig\.?|Table|图|表)\s*[A-Z]?\d+(?:\.\d+)*\s*[:：]', raw, re.I))
            or bool(lines and median(line.size for line in lines) < page_body_size * .94))
        caption_before = paragraphs[-1]['anchors'][-1] if paragraphs and paragraphs[-1]['kind'] == 'caption' else None
        annotation = bool(caption_before and bounds and caption_before['bbox'] and caption_before['page'] == chunk.page
                          and abs(caption_before['bbox'][0]-bounds[0]) < 22 and 0 <= bounds[1]-caption_before['bbox'][3] < 35)
        layout_artifact = _layout_artifact(raw, lines, page_body_size, caption=caption_like,annotation=annotation)
        footnote = bool(lines and median(line.size for line in lines) < page_body_size * .94
                        and bounds and bounds[1] > (chunk.page_height or 800) * .82)
        short_continuation = bool(re.match(r'^[a-z]', raw) and any(
            value['kind'] == 'prose' and value['section'] == chunk.section
            and not re.search(r'[.!?:;。！？：；][\]”"\')]*$', value['text'])
            for value in reversed(paragraphs)))
        # Only discard actual e-mail addresses from author metadata. Metrics
        # such as ``pass@1`` are ordinary scientific prose and must remain in
        # the paragraph (the old broad ``'@' in raw`` check dropped Reflexion's
        # entire abstract).
        has_email = bool(re.search(r'\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b', raw))
        if (layout_artifact or footnote or re.match(r'^[∗*†‡]', raw) or (len(raw) < 35 and not is_math and not short_continuation) or has_email or re.match(r'^(?:arXiv:|Provided proper attribution|Copyright|Permission to)', raw, re.I)
                or (not section and chunk.page == 1 and len(raw) < 120)
                or (bounds and bounds[1] > (chunk.page_height or 800) * .92)):
            continue
        for start, end, bbox in _ranges(chunk, matched[chunk.id]):
            source = chunk.content[start:end]
            if not source.strip():
                continue
            kind = 'caption' if caption_like else 'prose'
            item = {'section': section, 'kind': kind, 'source_text': source, 'text': prose_text(source), '_math': is_math and len(source) < 150,
                    '_layout': _typography(source,lines,layouts.get(chunk.page,[])),
                    'refs': [{'chunk_id': chunk.id, 'start': start, 'end': end}],
                    'anchors': [{'chunk_id': chunk.id, 'page': chunk.page or 1, 'bbox': bbox,
                                 'page_width': chunk.page_width, 'page_height': chunk.page_height}]}
            item['_pieces'] = [{'source': source, 'ref': item['refs'][0], 'anchor': item['anchors'][0],
                                'position': _piece_position(source, item['anchors'][0], lines)}]
            previous = paragraphs[-1] if paragraphs else None
            # ACM abstracts can continue in the opposite column where the
            # stored parser label is absent. Repair only the derived label.
            if (previous and previous['section'] == 'Abstract' and item['section'] is None
                    and kind == 'prose' and not _ends_sentence(previous['text'])
                    and _flow(previous,item) in {'column','page'}):
                item['section'] = 'Abstract'
            first_prose = kind == 'prose' and chunk.page not in prose_pages
            if first_prose:
                # Figures may precede the continued sentence on the following page.
                previous = next((value for value in reversed(paragraphs) if value['kind']=='prose'), None)
            bridge = False
            if kind == 'prose' and previous and previous['kind'] != 'prose':
                candidate_index = len(paragraphs) - 1
                while candidate_index >= 0 and paragraphs[candidate_index]['kind'] != 'prose':
                    candidate_index -= 1
                candidate = paragraphs[candidate_index] if candidate_index >= 0 else None
                if candidate and _bridge_continuation(candidate, item):
                    previous, bridge = candidate, True
            if previous and (_math_continuation(previous, item) or bridge
                             or _continuation(previous, item, first_prose_on_page=first_prose)):
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
        layout = item.pop('_layout')
        item['starts_indented'] = layout['indented'] if layout else None
        pieces = _ordered_pieces(item.pop('_pieces'))
        item['source_text'] = '\n'.join(piece['source'] for piece in pieces)
        item['text'] = prose_text(item['source_text'])
        item['refs'] = [piece['ref'] for piece in pieces]
        item['anchors'] = [piece['anchor'] for piece in pieces]
        identity = json.dumps([item['refs'], item['source_text']], ensure_ascii=False, sort_keys=True)
        item['id'] = 'paragraph-' + hashlib.sha256(identity.encode()).hexdigest()[:24]
    return paragraphs


def paragraphs_for(paper):
    from .reading_boundaries import project
    return project(paper,build_reading_paragraphs(list(paper.chunks), paper.pdf_path, title=paper.title))


def reading_payload(paper, provider=None, *, paragraphs=None):
    paragraphs = paragraphs_for(paper) if paragraphs is None else paragraphs
    translations = {}
    translation_errors = {}
    for item in paragraphs:
        anchor = item['refs'][0]['chunk_id']
        cached = [translation for translation in paper.translations
                  if translation.chunk_id == anchor and translation.source_text == item['source_text']]
        valid = [row for row in cached if not translation_error(row.source_text, row.text)]
        if cached and not valid:
            translation_errors[item['id']] = translation_error(cached[0].source_text, cached[0].text)
        cached = valid
        if provider is not None and provider.translation_available:
            matching = [record for record in cached if record.provider == provider.name
                      and record.config_version == provider.translation_configuration_version
                      and record.prompt_version == provider.translation_prompt_version]
            # Pretranslation deliberately uses the configured background model,
            # which may differ from the current interactive connection. Preserve
            # access to saved translations, with their actual model label.
            cached = matching or cached
        if cached:
            latest = max(cached, key=lambda record: (record.created_at, record.id))
            translations[item['id']] = {'text': latest.text, 'model': latest.model_version}
    return {'paragraphs': [{key: value for key, value in item.items() if key not in {'refs','starts_indented'}} for item in paragraphs],
            'translations': translations, 'translation_errors': translation_errors}
