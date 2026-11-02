"""Caption-led visual regions for direct figure and table questions."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import re
from pathlib import Path

import pymupdf as fitz


CAPTION = re.compile(r"^\s*((?:Figure|Fig\.?|Table|图|表)\s*[A-Z]?\d+(?:\.\d+)*)\s*[:：.\-]?\s*(.*)$", re.I)


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
                           "line_count": len(lines), "tabular": _tabular_lines(lines)})
    return result


def _graphic_boxes(page, width, height):
    boxes = []
    page_area = width * height
    try:
        for image in page.get_images(full=True):
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
        sentence = len(text) >= 70 and bool(re.search(r"[.!?。！？][\]）\"']*$", text))
        compact_row = len(text) <= 160 and not sentence and (block["line_count"] <= 3 or bool(re.search(r"\d", text)))
        heading = bool(re.match(r'^\d+(?:\.\d+)*\s+[A-Z]', text)) and not block['tabular']
        eligible = not CAPTION.match(text) and not heading and (block['tabular'] or compact_row)
        if bbox[1] >= caption[3] - 8:
            after.append((bbox, eligible))
        elif bbox[3] <= caption[1] + 8:
            before.append((bbox, eligible))
    # Walk contiguous text in either direction. Other captions and prose are
    # barriers, including when they are not themselves selectable table rows.
    for direction, candidates in ((1, sorted(after, key=lambda item: item[0][1])),
                                  (-1, sorted(before, key=lambda item: -item[0][3]))):
        rows = []
        edge = caption[3] if direction > 0 else caption[1]
        for bbox, eligible in candidates:
            gap = bbox[1] - edge if direction > 0 else edge - bbox[3]
            if not eligible or gap > 52:
                break
            rows.append(bbox)
            edge = bbox[3] if direction > 0 else bbox[1]
        if rows:
            return rows
    return []


def _table_graphics(boxes, caption, rows):
    # Sparse horizontal rules can be far apart. Associate them with the full
    # cell extent; a fixed drawing-component distance only finds the header.
    extent = _union([caption, *rows])
    return [box for box in boxes if box[1] >= extent[1] - 8 and box[3] <= extent[3] + 16
            and _gap(box, _union(rows))[0] <= 12]


def _page_regions(page, page_number):
    width, height = float(page.cropbox.width), float(page.cropbox.height)
    blocks = _blocks(page, width, height)
    graphics = _graphic_boxes(page, width, height)
    regions = []
    for block in blocks:
        match = CAPTION.match(block["text"])
        if not match:
            continue
        label = re.sub(r"\s+", " ", match.group(1)).strip()
        kind = "table" if label.casefold().startswith(("table", "表")) else "figure"
        caption = block["bbox"]
        rows = _table_text_boxes(blocks, caption, width, height) if kind == "table" else []
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
                        "page_width": width, "page_height": height})
    return regions


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
