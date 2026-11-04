"""Locate display mathematics without treating PDF text order as math structure.

The page image remains authoritative: these are crop coordinates, never a LaTeX
transcription. Prose baselines and column gutters constrain fragment grouping.
"""
from __future__ import annotations

import hashlib
import re


NUMBER = re.compile(r"^[（(]\s*([A-Z]?\d+(?:[-.]\d+)*)\s*[）)]$", re.I)
OPERATORS = re.compile(r"[=<>≤≥≈≠±∑∏∫∂∇√×÷−+\-*/^_α-ωΑ-Ω\uf000-\uf0ff]")
RELATION = re.compile(r"[=<>≤≥≈≠∝∑∏∫∂∇√\uf03d\uf0bb\uf0b6\uf0e5\uf0f2]")
WORDS = re.compile(r"[A-Za-z]{3,}")
MATH_WORDS = {'tanh', 'tan', 'sin', 'cos', 'exp', 'log', 'min', 'max', 'arg', 'rho', 'phi',
              'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'omega', 'sigma', 'mu', 'otherwise', 'if'}


def _union(boxes):
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


def _prose(text):
    """Use linguistic content, not absence of math, to identify body baselines."""
    if sum('\u3400' <= char <= '\u9fff' for char in text) >= 2:
        return True
    words = [word for word in WORDS.findall(text.casefold()) if word not in MATH_WORDS]
    return len(words) >= 4 or bool(re.match(r'^(?:where|whereas|the |for |we |in |this |figure|table)', text, re.I))


def _two_columns(lines, width):
    sides = [0, 0]
    for line in lines:
        x0, _, x1, _ = line['bbox']
        if not _prose(line['text']) or not width * .27 <= x1 - x0 <= width * .49:
            continue
        if x1 <= width / 2 + 6:
            sides[0] += 1
        elif x0 >= width / 2 - 6:
            sides[1] += 1
    return min(sides) >= 2


def _inside(box, regions):
    center_x, center_y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(region['bbox'][0] <= center_x <= region['bbox'][2]
               and region['bbox'][1] <= center_y <= region['bbox'][3] for region in regions)


def equation_regions(page, page_number, *, blocks=None, excluded=()):
    width, height = float(page.cropbox.width), float(page.cropbox.height)
    if blocks is None:
        blocks = page.get_text('dict', sort=True).get('blocks', [])
    lines = []
    for block in blocks:
        if block.get('type') != 0:
            continue
        for line in block.get('lines', []):
            text = ''.join(span.get('text', '') for span in line.get('spans', [])).strip()
            box = tuple(line.get('bbox', ()))
            if not text or len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
                continue
            lines.append({'text': text, 'bbox': box})
    two_columns = _two_columns(lines, width)
    for line in lines:
        x0, _, x1, _ = line['bbox']
        line['column'] = (0 if x1 <= width / 2 + 6 else 1 if x0 >= width / 2 - 6 else 2) if two_columns else 0

    # A short math fragment on a prose baseline is still inline math. Collect
    # barriers before discarding prose, including independently emitted glyphs.
    prose = [line for line in lines if _prose(line['text'])]
    fragments, markers = [], []
    for line in lines:
        box, text, column = line['bbox'], line['text'], line['column']
        if _inside(box, excluded):
            continue
        number = NUMBER.fullmatch(text)
        if number:
            markers.append({**line, 'number': number.group(1)})
            continue
        if _prose(text) or box[1] < height * .045 or box[3] > height * .965:
            continue
        center_y = (box[1] + box[3]) / 2
        if any(other['column'] == column and abs(center_y - (other['bbox'][1] + other['bbox'][3]) / 2) <= 5
               for other in prose):
            continue
        fragments.append(line)

    # Group overlapping vertical extents in each column. A fraction's numerator,
    # denominator, bracket and accent often live in completely separate blocks.
    groups = []
    for line in sorted(fragments, key=lambda item: (item['column'], item['bbox'][1], item['bbox'][0])):
        target = None
        for group in reversed(groups):
            if group['column'] != line['column']:
                continue
            box = group['bbox']
            gap = line['bbox'][1] - box[3]
            if gap > 2:
                break
            # A prose baseline is a hard barrier, even when a large bracket
            # overlaps the glyph bounds vertically.
            if any(other['column'] == line['column'] and box[3] < (other['bbox'][1] + other['bbox'][3]) / 2 < line['bbox'][1]
                   for other in prose):
                continue
            target = group
            break
        if target is None:
            groups.append({'column': line['column'], 'bbox': line['bbox'], 'items': [line]})
        else:
            target['items'].append(line)
            target['bbox'] = _union([target['bbox'], line['bbox']])

    result = []
    for group in groups:
        bounds = group['bbox']
        items = sorted(group['items'], key=lambda item: (round(item['bbox'][1] / 6), item['bbox'][0]))
        text = ' '.join(item['text'] for item in items)
        if not RELATION.search(text) or not re.search(r'[A-Za-zα-ωΑ-Ω\uf000-\uf0ff]', text):
            continue
        # Match the number only within this column and the formula's vertical
        # extent; a bibliography/page number cannot name an arbitrary formula.
        numbers = [marker for marker in markers if marker['column'] == group['column']
                   and bounds[1] <= (marker['bbox'][1] + marker['bbox'][3]) / 2 <= bounds[3]
                   and -4 <= marker['bbox'][0] - bounds[2] <= width * .48]
        if numbers:
            marker = min(numbers, key=lambda marker: abs(marker['bbox'][0] - bounds[2]))
            number = marker['number']
            bounds = _union([bounds, marker['bbox']])
        else:
            number = None
        if len(OPERATORS.findall(text)) < (1 if number else 2):
            continue
        label = f'Equation ({number})' if number else f'Equation {len(result) + 1}'
        digest = hashlib.sha1(f'{page_number}:equation:{bounds}:{text}'.encode('utf-8')).hexdigest()[:12]
        result.append({'id': f'visual-{digest}', 'page': page_number, 'kind': 'equation',
                       'label': label, 'caption': text,
                       'bbox': [max(0, bounds[0] - 4), max(0, bounds[1] - 3),
                                min(width, bounds[2] + 4), min(height, bounds[3] + 3)],
                       'page_width': width, 'page_height': height})
    return sorted(result, key=lambda region: (region['bbox'][1], region['bbox'][0]))
