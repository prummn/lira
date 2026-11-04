"""Caption-led visual regions for direct figure and table questions."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import re
from pathlib import Path

import pymupdf as fitz

from .pdf_metadata import is_contents_page, read_lines
from .equation_regions import equation_regions as _equation_regions


CAPTION = re.compile(r"^\s*((?:Figure|Fig\.?|Table|图|表)\s*[A-Z]?\d+(?:[-.]\d+)*)\s*[:：.\-]?\s*(.*)$", re.I)


def _box(value, width: float, height: float):
    try:
        x0, y0, x1, y1 = (float(part) for part in value)
    except (TypeError, ValueError):
        return None
    x0, x1 = max(0.0, min(width, x0)), max(0.0, min(width, x1))
    y0, y1 = max(0.0, min(height, y0)), max(0.0, min(height, y1))
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def _drawing_box(value, width: float, height: float):
    try:
        x0, y0, x1, y1 = (float(part) for part in value)
    except (TypeError, ValueError):
        return None
    if x0 == x1:
        x0, x1 = x0 - 0.5, x1 + 0.5
    if y0 == y1:
        y0, y1 = y0 - 0.5, y1 + 0.5
    return _box((x0, y0, x1, y1), width, height)


def _union(boxes):
    values = [box for box in boxes if box]
    if not values:
        return None
    return (min(box[0] for box in values), min(box[1] for box in values),
            max(box[2] for box in values), max(box[3] for box in values))


def _gap(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return dx, dy


def _tabular_lines(lines):
    # PDF extractors may group every cell of a large table into one block.
    # Recognize repeated, horizontally separated cells instead of limiting
    # the total characters or number of PDF lines in that block.
    rows = []
    for line in sorted(lines, key=lambda item: item['bbox'][1]):
        text = ''.join(span.get('text', '') for span in line.get('spans', [])).strip()
        if not text:
            continue
        box = line['bbox']
        center = (box[1] + box[3]) / 2
        if rows and abs(center - rows[-1][0]) <= max(2.0, (box[3] - box[1]) * 0.4):
            rows[-1][1].append((box, text))
        else:
            rows.append((center, [(box, text)]))
    aligned = []
    for _, cells in rows:
        cells.sort(key=lambda cell: cell[0][0])
        if len(cells) >= 2 and all(len(text) <= 100 for _, text in cells) and all(
                right[0][0] >= left[0][2] - 1 for left, right in zip(cells, cells[1:])):
            aligned.append(len(cells))
    return any(count >= 3 for count in aligned) or len(aligned) >= 2


def _blocks(page, width, height):
    result = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        text = " ".join("".join(span.get("text", "") for span in line.get("spans", [])) for line in lines).strip()
        bbox = _box(block.get("bbox"), width, height)
        if text and bbox:
            result.append({"text": re.sub(r"\s+", " ", text), "bbox": bbox,
                           "line_count": len(lines), "tabular": _tabular_lines(lines),
                           "font_size": max((span.get('size', 0) for line in lines for span in line.get('spans', [])), default=0)})
    return _join_caption_lines(result)


def _join_caption_lines(blocks):
    """Recover caption continuations emitted as independent PDF text blocks.

    Match typography and tight line spacing within the caption's column. A
    bilingual label of the same number may widen the caption, while body text,
    tabular cells and the next caption remain separate reading targets.
    """
    ordered = sorted(blocks, key=lambda block: (block['bbox'][1], block['bbox'][0]))
    consumed, result = set(), []
    for index, original in enumerate(ordered):
        if index in consumed:
            continue
        block = dict(original)
        label = CAPTION.match(block['text'])
        if label and block['font_size']:
            identity = _region_identity({'kind': 'table' if label[1].casefold().startswith(('table', '表')) else 'figure', 'label': label[1]})
            for next_index in range(index + 1, len(ordered)):
                following = ordered[next_index]
                a, b = block['bbox'], following['bbox']
                if b[1] - a[3] > max(5, block['font_size'] * .7):
                    break
                if (next_index in consumed or b[1] < a[3] - 1 or following['tabular']
                        or abs(following['font_size'] - block['font_size']) > .6
                        or min(a[2], b[2]) <= max(a[0], b[0])):
                    continue
                next_label = CAPTION.match(following['text'])
                if next_label:
                    next_identity = _region_identity({'kind': 'table' if next_label[1].casefold().startswith(('table', '表')) else 'figure', 'label': next_label[1]})
                    if identity != next_identity:
                        continue
                elif b[0] < a[0] - 12 or b[2] > a[2] + 12:
                    continue
                if block['line_count'] + following['line_count'] > 10:
                    break
                block['bbox'] = _union([a, b])
                block['text'] += ' ' + following['text']
                block['line_count'] += following['line_count']
                consumed.add(next_index)
        result.append(block)
    return result


def _graphic_boxes(page, width, height):
    boxes = []
    page_area = width * height
    try:
        for image in page.get_images(full=True):
            # Soft masks with almost zero opacity are publisher watermarks,
            # not visible artwork. Their rectangles can overlap both columns.
            if len(image) > 1 and image[1]:
                mask = fitz.Pixmap(page.parent, image[1])
                if max(mask.samples, default=255) <= 16:
                    continue
            for rect in page.get_image_rects(image[0]):
                box = _box(rect, width, height)
                if box and (box[2] - box[0]) * (box[3] - box[1]) < page_area * 0.78:
                    boxes.append(box)
    except (RuntimeError, ValueError):
        pass
    try:
        for drawing in page.get_drawings():
            box = _drawing_box(drawing.get("rect"), width, height)
            if not box:
                continue
            box_width, box_height = box[2] - box[0], box[3] - box[1]
            area = box_width * box_height
            if (box_width > width * .65 and box_height < 3
                    and (box[3] < height * .12 or box[1] > height * .89)):
                continue
            if area >= 35 or max(box_width, box_height) >= 36:
                if area < page_area * 0.78:
                    boxes.append(box)
    except (RuntimeError, ValueError):
        pass
    return boxes


def _caption_near(box, caption, kind, page_height):
    dx, dy = _gap(box, caption)
    horizontal_limit = min(100.0, max(38.0, (caption[2] - caption[0]) * 0.35))
    if dx > horizontal_limit:
        return False
    if kind == "figure":
        # Captions usually follow a figure. A nearby object below it is allowed
        # for the less common top-caption layout, but only at close range.
        if box[3] <= caption[1] + 8:
            return dy <= min(300.0, page_height * 0.42)
        return dy <= 82.0
    # Tables commonly place their caption above the rows. Use the opposite
    # direction first, with a small fallback for bottom captions.
    if box[1] >= caption[3] - 8:
        return dy <= min(280.0, page_height * 0.42)
    return dy <= 70.0


def _components(boxes, margin=34.0):
    pending = set(range(len(boxes)))
    result = []
    while pending:
        component = {pending.pop()}
        changed = True
        while changed:
            changed = False
            for index in list(pending):
                if any(max(_gap(boxes[index], boxes[member])) <= margin for member in component):
                    pending.remove(index)
                    component.add(index)
                    changed = True
        result.append([boxes[index] for index in component])
    return result


def _clear_caption_path(bounds, caption, blocks):
    if bounds[3] <= caption[1] + 8:
        top, bottom = bounds[3], caption[1]
    elif bounds[1] >= caption[3] - 8:
        top, bottom = caption[3], bounds[1]
    else:
        return True
    left, right = max(bounds[0], caption[0]), min(bounds[2], caption[2])
    for block in blocks:
        box = block["bbox"]
        if box == caption or box[1] < top - 1 or box[3] > bottom + 1:
            continue
        if min(right, box[2]) <= max(left, box[0]):
            continue
        # Axis labels may sit outside a drawing. Full prose and other captions
        # separate it from the candidate; they cannot be crossed to find a figure.
        if CAPTION.match(block["text"]) or (len(block["text"]) >= 70 and not block["tabular"]):
            return False
    return True


def _best_graphic(boxes, caption, kind, page_height, blocks=()):
    candidates = [box for box in boxes if _caption_near(box, caption, kind, page_height)]
    if not candidates:
        return None
    if kind == 'figure':
        candidates = [box for box in candidates if _clear_caption_path(box, caption, blocks)]
        # Captions divide artwork: a close image below this caption is a
        # separate top-caption candidate, never part of the artwork above it.
        clusters = (_components([box for box in candidates if box[3] <= caption[1] + 8])
                    + _components([box for box in candidates if box[3] > caption[1] + 8]))
    else:
        clusters = _components(candidates)
    if kind == "figure":
        clusters = [cluster for cluster in clusters
                    if (bounds := _union(cluster))[2] - bounds[0] >= 12
                    and bounds[3] - bounds[1] >= 12
                    and _clear_caption_path(bounds, caption, blocks)]
        if not clusters:
            return None

    def score(cluster):
        bounds = _union(cluster)
        dx, dy = _gap(bounds, caption)
        direction_penalty = 0 if ((kind == "figure" and bounds[3] <= caption[1] + 8)
                                  or (kind == "table" and bounds[1] >= caption[3] - 8)) else 75
        area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        return direction_penalty + dy + dx * 0.22 - min(area, 50000) / 1200

    return min(clusters, key=score)


def _table_text_boxes(blocks, caption, width, height):
    before, after = [], []
    for block in blocks:
        bbox, text = block["bbox"], block["text"]
        if bbox == caption:
            continue
        dx, _ = _gap(bbox, caption)
        overlap = min(bbox[2], caption[2]) - max(bbox[0], caption[0])
        if dx > min(120.0, width * 0.2) or overlap <= 0:
            continue
        sentence = len(text) >= 55 and bool(re.search(r"[.!?。！？][\]）\"']*$", text))
        compact_row = len(text) <= 120 and not sentence and (block["line_count"] <= 3 or bool(re.search(r"\d", text)))
        heading = bool(re.match(r'^\d+(?:\.\d+)*\s+[A-Z]', text)) and not block['tabular']
        eligible = not CAPTION.match(text) and not heading and (block['tabular'] or compact_row)
        if bbox[1] >= caption[3] - 8:
            if eligible:
                after.append((bbox, block['tabular']))
        elif bbox[3] <= caption[1] + 8:
            if eligible:
                before.append((bbox, block['tabular']))

    def rows_from(candidates, direction):
        ordered = sorted(candidates, key=lambda item: direction * ((item[0][1] + item[0][3]) / 2))
        bands = []
        for bbox, marked_tabular in ordered:
            center = (bbox[1] + bbox[3]) / 2
            if bands and abs(center - bands[-1][0]) <= max(3.0, (bbox[3] - bbox[1]) * .35):
                bands[-1][1].append((bbox, marked_tabular))
            else:
                bands.append((center, [(bbox, marked_tabular)]))
        tabular_bands = []
        for center, cells in bands:
            cells.sort(key=lambda item: item[0][0])
            texts = [next((block['text'] for block in blocks if block['bbox'] == bbox), '') for bbox, _ in cells]
            distinct_columns = []
            for (bbox, _), text in zip(cells, texts):
                if not distinct_columns or bbox[0] - distinct_columns[-1][0][2] >= 8:
                    distinct_columns.append((bbox, text))
            numeric_cells = sum(bool(re.search(r'\d', text)) for _, text in distinct_columns)
            row_like = (len(distinct_columns) >= 3
                        or any(marked for _, marked in cells)
                        or len(distinct_columns) >= 2 and numeric_cells >= 1
                        and all(len(text) <= 80 for _, text in distinct_columns))
            tabular_bands.append((center, [bbox for bbox, _ in cells], row_like))
        if direction > 0:
            tabular_bands.sort(key=lambda band: band[0])
        else:
            tabular_bands.sort(key=lambda band: band[0], reverse=True)
        rows, edge = [], caption[3] if direction > 0 else caption[1]
        for center, boxes, row_like in tabular_bands:
            top, bottom = min(box[1] for box in boxes), max(box[3] for box in boxes)
            gap = top - edge if direction > 0 else edge - bottom
            if not row_like or gap > 48:
                if rows:
                    break
                continue
            rows.extend(boxes)
            edge = bottom if direction > 0 else top
        return rows

    for candidates, direction in ((after, 1), (before, -1)):
        rows = rows_from(candidates, direction)
        if rows:
            return rows
    return []


def _table_graphics(boxes, caption, rows):
    # Sparse horizontal rules can be far apart. Associate them with the full
    # cell extent; a fixed drawing-component distance only finds the header.
    extent = _union([caption, *rows])
    return [box for box in boxes if box[1] >= extent[1] - 8 and box[3] <= extent[3] + 16
            and _gap(box, _union(rows))[0] <= 12]


def _table_rule_extent(graphics, caption, blocks, height):
    """Associate three-rule tables even when cell math fragments defeat row OCR.

    Word-exported tables often draw the bottom rule once per cell. Join only
    collinear touching pieces before matching the header and bottom widths.
    """
    rules = []
    for box in sorted((box for box in graphics if box[3] - box[1] <= 3
                       and box[2] - box[0] >= 25), key=lambda box: (box[1], box[0])):
        match = next((index for index, rule in enumerate(rules)
                      if abs((rule[1] + rule[3]) / 2 - (box[1] + box[3]) / 2) < 2
                      and _gap(rule, box)[0] <= 3), None)
        if match is None:
            rules.append(box)
        else:
            rules[match] = _union([rules[match], box])
    starts = [rule for rule in rules if 0 <= rule[1] - caption[3] <= 35
              and rule[0] <= (caption[0] + caption[2]) / 2 <= rule[2]
              and rule[2] - rule[0] >= 80]
    if not starts:
        return None
    first = min(starts, key=lambda box: box[1])
    selected = [first]
    for rule in sorted(rules, key=lambda box: box[1]):
        if rule[1] <= first[3] + 2 or abs(rule[0] - first[0]) > 12 or abs(rule[2] - first[2]) > 12:
            continue
        previous = selected[-1]
        if rule[1] - previous[3] > min(230, height * .32):
            break
        barriers = [block for block in blocks
                    if previous[3] <= (block['bbox'][1] + block['bbox'][3]) / 2 <= rule[1]
                    and min(rule[2], block['bbox'][2]) > max(rule[0], block['bbox'][0])
                    and (CAPTION.match(block['text']) or not block['tabular']
                         and len(block['text']) >= 70 and re.search(r'[.!?。！？]\s*$', block['text']))]
        if barriers:
            break
        selected.append(rule)
    return _union(selected) if len(selected) >= 3 else None


def _page_regions(page, page_number):
    width, height = float(page.cropbox.width), float(page.cropbox.height)
    raw_blocks = page.get_text("dict", sort=True).get("blocks", [])
    if is_contents_page(read_lines(page_number - 1, raw_blocks)):
        return []
    blocks = _blocks(page, width, height)
    graphics = _graphic_boxes(page, width, height)
    regions = []
    for block in blocks:
        match = CAPTION.match(block["text"])
        if not match:
            continue
        label = re.sub(r"\s+", " ", match.group(1)).strip()
        title = match.group(2).strip()
        if _body_reference_caption(label, title):
            continue
        # A bare ``图 4``/``Fig. 4`` is usually a body reference or an
        # extractor fragment. A real visual caption has descriptive text;
        # bilingual captions are handled when the descriptive counterpart is
        # encountered below.
        if not title and label.casefold().startswith(("图", "fig")):
            continue
        kind = "table" if label.casefold().startswith(("table", "表")) else "figure"
        caption = block["bbox"]
        ruled = _table_rule_extent(graphics, caption, blocks, height) if kind == 'table' else None
        rows = [ruled] if ruled else _table_text_boxes(blocks, caption, width, height) if kind == "table" else []
        graphic_boxes = _table_graphics(graphics, caption, rows) if rows else _best_graphic(graphics, caption, kind, height, blocks)
        graphic = _union(graphic_boxes or [])
        # A caption by itself is not a useful selection target. Require some
        # geometric evidence so a misread footnote cannot become a chart.
        if not graphic and not rows:
            continue
        padding = 5.0
        bounds = _union(([graphic] if graphic else []) + rows + [caption])
        bounds = _box((bounds[0] - padding, bounds[1] - padding,
                       bounds[2] + padding, bounds[3] + padding), width, height)
        if not bounds:
            continue
        digest = hashlib.sha1(f"{page_number}:{kind}:{label}:{block['text']}".encode("utf-8")).hexdigest()[:12]
        regions.append({"id": f"visual-{digest}", "page": page_number, "kind": kind,
                        "label": label, "caption": block["text"], "bbox": list(bounds),
                        "caption_bbox": list(caption),
                        "page_width": width, "page_height": height})
    regions.extend(_equation_regions(page, page_number, blocks=raw_blocks, excluded=regions))
    return _merge_bilingual_regions(regions)


def _body_reference_caption(label, title):
    return label.casefold().startswith("图") and bool(
        re.match(r"(?:所示|所见|所给|如下|可见|显示|展示)", title)
    )


def _region_identity(region):
    match = CAPTION.match(region["label"])
    if not match:
        return None
    label = re.sub(r"^(?:figure|fig\.?|table|图|表)\s*", "", region["label"], flags=re.I)
    return region["kind"], re.sub(r"\s+", "", label).casefold()


def _merge_bilingual_regions(regions):
    """Join duplicate Chinese/English captions that point at the same artwork."""
    result = []
    for region in regions:
        identity = _region_identity(region)
        target = None
        if identity:
            for existing in reversed(result):
                if _region_identity(existing) != identity:
                    continue
                a, b = existing["bbox"], region["bbox"]
                intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
                smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
                vertical_gap = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
                horizontal_overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
                if smaller and (intersection / smaller >= .7
                                or (horizontal_overlap > 0 and vertical_gap <= 26)):
                    target = existing
                    break
        if not target:
            result.append(dict(region))
            continue
        # Keep the tighter artwork bounds. The second caption often inherits a
        # neighboring drawing from a two-column PDF text block; taking a union
        # would make the clickable region swallow the next paragraph/figure.
        size = lambda box: (box[2] - box[0]) * (box[3] - box[1])
        target["bbox"] = list(max((target["bbox"], region["bbox"]), key=size)
                              if target["kind"] == "table" else min((target["bbox"], region["bbox"]), key=size))
        caption_boxes = [box for box in (target.get('caption_bbox'), region.get('caption_bbox')) if box]
        if caption_boxes:
            target['caption_bbox'] = list(_union(caption_boxes))
            target['bbox'] = list(_union([target['bbox'], *caption_boxes]))
        if region["caption"] not in target["caption"]:
            target["caption"] += "\n" + region["caption"]
        if region["label"].startswith(("图", "表")):
            target["label"] = region["label"]
    return result


@lru_cache(maxsize=16)
def _cached_regions(path: str, modified_ns: int, size: int):
    try:
        with fitz.open(path) as document:
            return tuple(region for index, page in enumerate(document, start=1)
                         for region in _page_regions(page, index))
    except (OSError, RuntimeError, ValueError):
        return ()


def visual_regions_for_pdf(path: str | Path):
    """Return cached, page-local figure/table regions in canonical PDF points."""
    try:
        source = Path(path)
        if not source.is_file():
            return []
        stat = source.stat()
        return [dict(region) for region in _cached_regions(str(source.resolve()), stat.st_mtime_ns, stat.st_size)]
    except OSError:
        return []
