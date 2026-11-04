"""Resolve PDF selections without weakening the literal citation validator."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import unicodedata

import pymupdf as fitz

from ..models import Paper, PaperChunk
from ..providers.validation import resolve_selection_chunks


@dataclass
class SelectionSource:
    anchor: PaperChunk
    chunks: list[PaperChunk]
    text: str
    layout_recovered: bool = False
    math_recovered: bool = False


def visual_selection_chunks(paper: Paper, page: int, bbox) -> list[PaperChunk]:
    """Pin actual crop contents before page headers and unrelated column text."""
    if not bbox or len(bbox) != 4:
        return []
    matches = []
    for chunk in paper.chunks:
        if chunk.page != page or not chunk.bbox_json:
            continue
        try:
            box = json.loads(chunk.bbox_json)
            if not isinstance(box, list) or len(box) != 4 or not all(math.isfinite(value) for value in box):
                continue
            area = (box[2] - box[0]) * (box[3] - box[1])
            intersection = max(0, min(box[2], bbox[2]) - max(box[0], bbox[0])) * max(0, min(box[3], bbox[3]) - max(box[1], bbox[1]))
            if area > 0 and intersection / area >= .15:
                matches.append((intersection / area, box[1], box[0], chunk.id, chunk))
        except (TypeError, ValueError):
            continue
    matches.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    return [item[-1] for item in matches]


def _view(value: str) -> str:
    value = re.sub(r'(?<=\w)-\s+(?=\w)', '', value)
    return ''.join(unicodedata.normalize('NFKC', value).casefold().split())


def _font_aliases(pdf, page) -> dict[str, dict[str, str]]:
    """TeX extension fonts sometimes omit symbols from their ToUnicode map.

    Use the PDF's own glyph names, never a general X-to-sum substitution.
    MuPDF emits the character code as ASCII when these entries are missing.
    """
    symbols = {'summation': '∑', 'product': '∏', 'coproduct': '∐', 'integral': '∫',
               'contintegral': '∮', 'union': '⋃', 'intersection': '⋂'}
    result = {}
    for xref, _, _, base_font, *_ in page.get_fonts():
        if not re.search(r'(?:MathExtension|CMEX|LMEX)', base_font, re.I):
            continue
        kind, encoding = pdf.xref_get_key(xref, 'Encoding')
        if kind == 'xref':
            encoding = pdf.xref_object(int(encoding.split()[0]))
        differences = re.search(r'/Differences\s*\[([^]]*)\]', encoding)
        if not differences:
            continue
        code = 0
        aliases = {}
        for token in re.findall(r'\d+|/[^\s/]+', differences[1]):
            if token.isdigit():
                code = int(token)
                continue
            name = re.sub(r'(?:display|text)$', '', token[1:])
            if name in symbols and 0 <= code < 128:
                aliases[chr(code)] = symbols[name]
            code += 1
        if aliases:
            result[base_font.split('+')[-1]] = aliases
    return result


def pdf_comparison_views(paper: Paper, pages: set[int]) -> dict[str, str]:
    """Repair comparison copies only; stored evidence remains immutable."""
    if not paper.pdf_path or not Path(paper.pdf_path).is_file():
        return {}
    result = {}
    try:
        with fitz.open(paper.pdf_path) as pdf:
            for number in sorted(pages):
                if not 1 <= number <= len(pdf):
                    continue
                page = pdf[number - 1]
                aliases = _font_aliases(pdf, page)
                if not aliases:
                    continue
                for block in page.get_text('dict')['blocks']:
                    if block['type'] != 0:
                        continue
                    original, repaired = [], []
                    for line in block['lines']:
                        original.append(''.join(span['text'] for span in line['spans']))
                        parts = []
                        for span in line['spans']:
                            mapping = next((value for name, value in aliases.items() if name.startswith(span['font'])), {})
                            parts.append(''.join(mapping.get(char, char) for char in span['text']))
                        repaired.append(''.join(parts))
                    raw, corrected = '\n'.join(original), '\n'.join(repaired)
                    if raw == corrected:
                        continue
                    for chunk in paper.chunks:
                        if chunk.page != number or _view(chunk.content) != _view(raw):
                            continue
                        bounds = json.loads(chunk.bbox_json or 'null')
                        if bounds and len(bounds) == 4 and all(abs(a - b) < 1 for a, b in zip(bounds, block['bbox'])):
                            result[chunk.id] = corrected
    except (OSError, RuntimeError, ValueError):
        return {}
    return result


def resolve_pdf_selection(paper: Paper, text: str, *, page: int | None = None) -> SelectionSource | None:
    strict = resolve_selection_chunks(paper.chunks, text, preferred_page=page)
    if strict is not None:
        return SelectionSource(*strict)
    # Formatting recovery is local to the selected page and its continuations.
    # Do not assemble a plausible passage from unrelated parts of the paper.
    if page is None:
        return None
    nearby = [chunk for chunk in paper.chunks if chunk.page is not None and abs(chunk.page - page) <= 1]
    nearby.sort(key=lambda chunk: (abs(chunk.page - page), chunk.page, chunk.id))
    corrected = pdf_comparison_views(paper, {chunk.page for chunk in nearby})
    sources = [(chunk, _view(corrected.get(chunk.id, chunk.content))) for chunk in nearby]
    query = _view(text)
    if len(query) < 3:
        return None
    consumed: dict[str, set[int]] = {}
    matched = []
    cursor = 0
    while cursor < len(query):
        best = None
        for chunk, source in sources:
            used = consumed.get(chunk.id, set())
            start = source.find(query[cursor])
            while start >= 0:
                length = 0
                while (start + length < len(source) and cursor + length < len(query)
                       and start + length not in used and source[start + length] == query[cursor + length]):
                    length += 1
                # Prose may start/end partway through a selection, but never
                # splice words from its interior into another prose block.
                end = start + length
                short_math = len(source) <= 40 and not re.search(r'[a-z]{4,}', re.sub(r'pass@\d+', '', source))
                if short_math:
                    boundary = (not start or not (source[start - 1].isalnum() and source[start].isalnum()))
                    boundary = boundary and (end == len(source) or not (source[end - 1:end].isalnum() and source[end:end + 1].isalnum()))
                else:
                    boundary = (cursor == 0 or start == 0) and (cursor + length == len(query) or end == len(source))
                if length and boundary and (length >= 3 or short_math) and (best is None or length > best[0]):
                    best = (length, chunk, start)
                start = source.find(query[cursor], start + 1)
        if best is None:
            return None
        length, chunk, start = best
        consumed.setdefault(chunk.id, set()).update(range(start, start + length))
        if chunk not in matched:
            matched.append(chunk)
        cursor += length
    if not matched:
        return None
    return SelectionSource(matched[0], matched, text.strip(), True, any(chunk.id in corrected for chunk in matched))


def selection_image(paper: Paper, chunks: list[PaperChunk], page: int) -> str | None:
    """Render just the recovered formula passage, without another model call."""
    if not paper.pdf_path or not Path(paper.pdf_path).is_file():
        return None
    bounds = [json.loads(chunk.bbox_json) for chunk in chunks if chunk.page == page and chunk.bbox_json]
    if not bounds:
        return None
    try:
        with fitz.open(paper.pdf_path) as pdf:
            if not 1 <= page <= len(pdf):
                return None
            source = pdf[page - 1]
            rect = fitz.Rect(min(b[0] for b in bounds) - 5, min(b[1] for b in bounds) - 5,
                             max(b[2] for b in bounds) + 5, max(b[3] for b in bounds) + 5) & source.rect
            if rect.is_empty:
                return None
            pixmap = source.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), clip=rect, alpha=False)
            return 'data:image/png;base64,' + base64.b64encode(pixmap.tobytes('png')).decode('ascii')
    except (OSError, RuntimeError, ValueError):
        return None
