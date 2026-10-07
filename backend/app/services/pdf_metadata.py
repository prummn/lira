"""Conservative bibliography extraction from first-page text and typography.

These are local observations, not authoritative publisher metadata. PDF creation
dates and citations in the abstract/body are deliberately excluded.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Any


ARXIV = re.compile(r"\barxiv\s*:\s*((?:\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7}))(?:v([1-9]\d*))?", re.I)
DOI = re.compile(r"(?:\bdoi\s*:\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s<>]+)", re.I)
ABSTRACT = re.compile(r"^(?:abstract|摘要)(?:\s*[:：.。—–-]\s*.*)?\s*$", re.I)
ABSTRACT_END = re.compile(r"^(?:index terms|key\s*words|CCS concepts|additional key words|ACM reference format)\b", re.I)
ABSTRACT_CAPTION = re.compile(r'^(?:figure|fig\.|table|图|表)\s*\d+\s*[:.：]', re.I)
NUMBER = re.compile(r"^\d+(?:\.\d+)*\.?$")
NUMBERED = re.compile(r"^(\d+(?:\.\d+)*\.?)\s+(.+)$")
LICENSE = re.compile(r"permission|copyright|all rights reserved|provided proper attribution|reproduce the tables|scholarly works|preprint|submitted|accepted|published|version\s*\d", re.I)
ORGANIZATION = re.compile(r"\b(?:university|institute|department|school|laboratory|labs?|google|microsoft|research|brain|corporation|company|inc|corp|ltd|college|academy|hospital|centre|center|technology|technologies|language|conference|proceedings|journal|workshop)\b", re.I)
VENUE = re.compile(r"\b(?:conference|proceedings|journal|workshop|transactions|symposium)\b", re.I)
PUBLICATION_YEAR = re.compile(r"(?:\bpublished(?:\s+online)?\b|\bcopyright\b|©)\D{0,30}\b((?:19|20)\d{2})\b", re.I)
TEMPLATE = re.compile(r"make sure to enter|your rights confirmation|conference acronym|\b[xn]{4,}\b", re.I)


@dataclass(frozen=True)
class LayoutLine:
    key: tuple[int, int, int]
    text: str
    bbox: tuple[float, float, float, float]
    size: float
    bold: bool
    horizontal: bool
    spans: list[dict[str, Any]]


def read_lines(page_index: int, blocks: list[dict]) -> list[LayoutLine]:
    result = []
    for block_index, block in enumerate(blocks):
        if block.get("type") != 0:
            continue
        for line_index, line in enumerate(block["lines"]):
            spans = line["spans"]
            text = "".join(span["text"] for span in spans).strip()
            if not text:
                continue
            # Weight by visible characters so a superscript or bold word cannot
            # change an entire line's style. Keep the largest meaningful size for
            # small-cap titles, where regular capitals and small capitals mix.
            visible = [s for s in spans if s["text"].strip()]
            size = max((float(s["size"]) for s in visible), default=0)
            significant = [s for s in visible if float(s["size"]) >= size * .8]
            letters = sum(len(s["text"].strip()) for s in significant)
            bold = sum(len(s["text"].strip()) for s in significant
                       if s.get("flags", 0) & 16) >= max(1, letters * .8)
            direction = line.get("dir", (1, 0))
            result.append(LayoutLine(
                (page_index, block_index, line_index), text,
                tuple(float(n) for n in line["bbox"]), size, bold,
                abs(direction[1]) < .1 and direction[0] > .9, spans,
            ))
    return result


def body_font(lines: list[LayoutLine]) -> float:
    weights: Counter[float] = Counter()
    for line in lines:
        if line.horizontal and not line.bold:
            weights[round(line.size, 1)] += len(line.text)
    return weights.most_common(1)[0][0] if weights else 10.0


def heading_text(text: str) -> bool:
    return (1 <= len(text.split()) <= 12 and len(text) <= 100
            and not text.endswith((".", ",", ";", ":", "："))
            and not any(c in text for c in "=<>@{}")
            and any(c.isalpha() for c in text))


def _title(lines: list[LayoutLine], height: float, body_size: float) -> list[LayoutLine]:
    abstract_y = min((l.bbox[1] for l in lines if ABSTRACT.fullmatch(l.text)), default=height * .55)
    candidates = [l for l in lines if l.horizontal and l.bbox[1] < min(abstract_y, height * .55)
                  and 4 < len(l.text) < 300 and not LICENSE.search(l.text)
                  and not ABSTRACT.fullmatch(l.text) and not NUMBERED.match(l.text)
                  and not ARXIV.search(l.text) and not DOI.search(l.text)
                  and "@" not in l.text and not VENUE.search(l.text)]
    if not candidates:
        return []
    # An ordinary all-one-font PDF still uses its first eligible line as title.
    # Typography supplies stronger evidence when actual typesetting exists.
    largest = max(l.size for l in candidates)
    styled = [l for l in candidates if l.size >= largest * .95]
    first = min(styled, key=lambda l: (l.bbox[1], l.bbox[0]))
    selected = [first]
    if largest > body_size * 1.15:
        ordered = sorted(styled, key=lambda l: (l.bbox[1], l.bbox[0]))
        for line in ordered:
            if line == first:
                continue
            previous = selected[-1]
            gap = line.bbox[1] - previous.bbox[3]
            if -first.size * .3 <= gap <= max(10, first.size * .85):
                selected.append(line)
            elif line.bbox[1] > previous.bbox[3]:
                break
    return selected


def _join_title(lines: list[LayoutLine]) -> str | None:
    title = ""
    for line in lines:
        if title.endswith("-") and line.text[:1].isalpha():
            title = title[:-1] + line.text
        else:
            title = f"{title} {line.text}".strip()
    return title[:500] or None


def _names(text: str) -> list[str]:
    text = re.sub(r"[∗*†‡⁎♢¹²³⁴⁵⁶⁷⁸⁹\d]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    if ORGANIZATION.search(text) or any(c in text for c in "@{}()/:="):
        return []
    names = re.split(r"\s*(?:,|;|\band\b|&)\s*", text)
    result = []
    for name in names:
        if not name.strip():
            continue  # Empty affiliation-marker separators, e.g. Smith1,2.
        words = name.split()
        if not 2 <= len(words) <= 5:
            return []
        for word in words:
            letters = word.replace("-", "").replace("'", "").replace("’", "").replace(".", "")
            if not letters.isalpha() or not (word[0].isupper() or word in {"de", "van", "von", "di"}):
                return []
        result.append(name)
    return result


def extract_bibliography(metadata: dict, lines: list[LayoutLine], height: float,
                         body_size: float) -> tuple[dict, set[tuple[int, int, int]]]:
    title_lines = _title(lines, height, body_size)
    layout_title = _join_title(title_lines)
    embedded_title = " ".join((metadata.get("title") or "").split())
    if (embedded_title.lower() in {"", "untitled", "document", "microsoft word"}
            or embedded_title.lower().endswith((".pdf", ".tex", ".doc", ".docx"))):
        embedded_title = ""
    title = embedded_title or layout_title
    facts: dict = {"title": title, "authors": [], "year": None, "venue": None,
                   "doi": None, "arxiv_id": None, "arxiv_version": None, "metadata_sources": {}}
    sources = facts["metadata_sources"]
    if title:
        sources["title"] = "pdf_metadata" if embedded_title else "pdf_layout"
    abstract_y = min((l.bbox[1] for l in lines if ABSTRACT.fullmatch(l.text)), default=height * .55)
    title_end = max((l.bbox[3] for l in title_lines), default=0)
    name_lines = [l for l in lines if l.horizontal and title_end < l.bbox[1] < abstract_y
                  and l.size <= max((t.size for t in title_lines), default=body_size * 2)
                  and _names(l.text)
                  and not (any(other.key[1] == l.key[1] and ORGANIZATION.search(other.text)
                               for other in lines)
                           and any(span['size'] < l.size * .92 and any(c.isalpha() for c in span['text'])
                                   for span in l.spans))]
    if any(line.bold for line in name_lines):
        name_lines = [line for line in name_lines if line.bold]
    if name_lines:
        byline_size = max(line.size for line in name_lines)
        name_lines = [line for line in name_lines if line.size >= byline_size * .85]
    # Names at almost equal baselines form a visual row, even if PyMuPDF block
    # ordering happens to return the rightmost author first.
    rows: list[list[LayoutLine]] = []
    for line in sorted(name_lines, key=lambda l: (l.bbox[1], l.bbox[0])):
        if rows and abs(rows[-1][0].bbox[1] - line.bbox[1]) <= max(3, line.size * .35):
            rows[-1].append(line)
        else:
            rows.append([line])
    authors = [name for row in rows for line in sorted(row, key=lambda l: l.bbox[0])
               for name in _names(line.text)]
    facts["authors"] = list(dict.fromkeys(authors))
    if authors:
        sources["authors"] = "pdf_layout"
    elif metadata.get("author"):
        names = _names(metadata["author"])
        if names:
            facts["authors"] = names
            sources["authors"] = "pdf_metadata"

    # Only the pre-abstract front matter and isolated margin/footer bibliographic
    # lines identify this paper. Never mine dates/identifiers from its citations.
    front = [l for l in lines if l.bbox[1] < abstract_y or
             (not l.horizontal and l.bbox[0] < 60 and ARXIV.match(l.text)) or
             (l.bbox[1] > height * .87 and
              (VENUE.search(l.text) or DOI.match(l.text) or PUBLICATION_YEAR.search(l.text)))]
    for line in front:
        if TEMPLATE.search(line.text):
            continue
        if not facts["arxiv_id"] and (match := ARXIV.search(line.text)):
            candidate = match.group(1)
            date_code = candidate.split("/")[-1][:4].replace(".", "")
            if 1 <= int(date_code[2:4]) <= 12:
                facts["arxiv_id"] = candidate
                facts["arxiv_version"] = int(match.group(2)) if match.group(2) else None
                sources["arxiv_id"] = "arxiv_identifier"
        if not facts["doi"] and (match := DOI.search(line.text)):
            facts["doi"] = match.group(1).rstrip(".,;)")
            sources["doi"] = "pdf_text"
        if facts["year"] is None and (match := PUBLICATION_YEAR.search(line.text)):
            facts["year"] = int(match.group(1))
            sources["year"] = "pdf_text"
        if not facts["venue"] and line.horizontal and VENUE.search(line.text) and not LICENSE.search(line.text):
            facts["venue"] = line.text.rstrip(".")
            sources["venue"] = "pdf_text"
            if years := re.findall(r"\b((?:19|20)\d{2})\b", line.text):
                facts["year"] = int(years[-1])
                sources["year"] = "pdf_text"
    if facts["year"] is None and facts["arxiv_id"]:
        year_code = int(facts["arxiv_id"].split("/")[-1][:2])
        facts["year"] = 1900 + year_code if year_code >= 91 else 2000 + year_code
        sources["year"] = "arxiv_identifier"
    return facts, {l.key for l in title_lines}


SECTION_NUMBER = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[A-Z](?:\.\d+)*\.?|[IVXLCDM]+\.)$")


def _toc_row_keys(lines: list[LayoutLine]) -> set[tuple[int, int, int]]:
    """Identify observed leader rows sharing a right-aligned page column.

    A major TOC entry may omit leaders itself. Once two leader rows establish
    the page-number column, suppress every title row in that same TOC column.
    Original source lines remain intact; only heading candidates are filtered.
    """
    rows = []
    for counter in lines:
        if not counter.horizontal or not re.fullmatch(r'[1-9]\d*', counter.text):
            continue
        titles = [line for line in lines if line.key != counter.key and line.horizontal
                  and abs(line.bbox[1] - counter.bbox[1]) < max(2, counter.size * .3)
                  and line.bbox[2] < counter.bbox[0]]
        if titles:
            rows.append((counter, titles))
    leader = re.compile(r'(?:\.\s*){4,}')
    excluded = set()
    for counter, titles in rows:
        if not any(leader.search(line.text) for line in titles):
            continue
        column = [(other, title) for other, title in rows
                  if abs(other.bbox[2] - counter.bbox[2]) < 2]
        if len(column) < 3 or sum(any(leader.search(line.text) for line in title)
                                 for _, title in column) < 2:
            continue
        for other, title in column:
            excluded.add(other.key)
            excluded.update(line.key for line in title)
    return excluded


def detect_headings(lines: list[LayoutLine], known: re.Pattern, body_size: float,
                    excluded: set[tuple[int, int, int]], first_page: bool) -> dict:
    headings = {}
    toc_rows = _toc_row_keys(lines)
    abstract_y = min((l.bbox[1] for l in lines if ABSTRACT.fullmatch(l.text)), default=0)
    by_position = sorted((line for line in lines if line.key not in toc_rows),
                         key=lambda l: (l.bbox[1], l.bbox[0]))
    paired = set()
    for number in by_position:
        if not number.horizontal or not SECTION_NUMBER.fullmatch(number.text):
            continue
        neighbors = [l for l in by_position if l.key != number.key and l.horizontal
                     and abs(l.bbox[1] - number.bbox[1]) < max(2, number.size * .3)
                     and 0 <= l.bbox[0] - number.bbox[2] <= 40
                     and (known.fullmatch(l.text) or (heading_text(l.text) and
                          (l.bold or (l.text.isupper() and l.size >= body_size * .95))))]
        if neighbors:
            title = min(neighbors, key=lambda l: l.bbox[0])
            # Preserve the established chunk split for known headings. Generic
            # split-number headings keep their original number/newline/title.
            start = title if known.fullmatch(title.text) else number
            headings[start.key] = f"{number.text} {title.text}"
            paired.update((number.key, title.key))
    for line in lines:
        if line.key in excluded or line.key in toc_rows or line.key in paired or not line.horizontal:
            continue
        # Explicit abstract labels can be smaller than the main text, inline
        # with their paragraph, or aligned with a figure in the other column.
        if ABSTRACT.fullmatch(line.text) and line.size >= body_size * .75:
            headings[line.key] = 'Abstract'
            continue
        # Table headers and inline labels have neighboring text on the same
        # baseline. A wrapped bold paragraph has several body-sized bold lines.
        # Neither is a standalone document heading.
        peers = [other for other in lines if other.key != line.key and other.horizontal
                 and abs(other.bbox[1] - line.bbox[1]) < max(2, line.size * .2)
                 and not SECTION_NUMBER.fullmatch(other.text)]
        if (len(peers) >= 2 or any(other.key[1] == line.key[1] or other.bold
                                  or min(abs(other.bbox[0] - line.bbox[2]),
                                         abs(line.bbox[0] - other.bbox[2])) < 15
                                  for other in peers)):
            continue
        if line.bold and line.size <= body_size * 1.05 and any(
                other.key != line.key and other.key[1] == line.key[1]
                and other.bold and abs(other.size - line.size) < .5
                and (len(line.text) > 45 or len(other.text) > 45)
                for other in lines):
            continue
        # A parenthesized list item whose bold lead wraps into prose is not a
        # document section. Keep its evidence under the real results heading.
        if re.match(r'^\(\d+\)\s', line.text):
            continue
        # Algorithm line numbers are typography, not section numbers.
        if re.fullmatch(r'(?:\d+\s+)?end(?:\s+(?:if|for|while|function))?', line.text, re.I):
            continue
        if (known.fullmatch(line.text) and line.size >= body_size * .95
                and len(line.text) <= 100 and len(line.text.split()) <= 12):
            headings[line.key] = line.text
        elif (not first_page or line.bbox[1] > abstract_y) and heading_text(line.text):
            numbered = NUMBERED.match(line.text) or (line.size >= body_size * .95
                and re.match(r'^(?:[IVXLCDM]+\.|[A-Z](?:\.\d+)*\.?)\s+\S', line.text))
            # Isolated diagram labels often use bold heading-sized text. A
            # generic unnumbered heading needs nearby prose in its column;
            # captions and other diagram labels do not establish that context.
            following_prose = any(other.horizontal and not other.bold
                and not ABSTRACT_CAPTION.match(other.text) and len(other.text) > 25
                and abs(other.bbox[0] - line.bbox[0]) < body_size * 2
                and 0 <= other.bbox[1] - line.bbox[3] <= body_size * 2.5
                for other in lines)
            if (numbered and (line.bold or line.size > body_size * 1.05
                or (line.text.isupper() and line.size >= body_size * .95))) or (
                    (line.bold and line.size >= body_size * .95
                     or line.text.isupper() and line.size > body_size * 1.05)
                    and following_prose):
                headings[line.key] = line.text
    # Wrapped numbered titles remain one section. Do not alter the original
    # lines: only their shared label is joined, with the first line as anchor.
    lookup = {line.key: line for line in lines}
    for key, label in list(headings.items()):
        if key not in headings or not NUMBERED.match(label):
            continue
        anchor = lookup[key]
        title = next((line for line in lines if line.key in paired
            and line.key[1] == anchor.key[1] and line.key != key
            and abs(line.bbox[1] - anchor.bbox[1]) < 2), anchor)
        previous = title
        for continuation in sorted((line for line in lines if line.key[1] == anchor.key[1]
            and line.bbox[1] > title.bbox[1]), key=lambda line: line.bbox[1]):
            if (not continuation.horizontal or not continuation.bold
                or abs(continuation.size - title.size) > .5
                or abs(continuation.bbox[0] - title.bbox[0]) > 2
                or not 0 <= continuation.bbox[1] - previous.bbox[3] <= title.size
                or not heading_text(continuation.text)
                or NUMBERED.match(continuation.text) or known.fullmatch(continuation.text)):
                break
            headings[key] += ' ' + continuation.text
            headings.pop(continuation.key, None)
            previous = continuation
    return headings


def abstract_bounds(lines: list[LayoutLine]) -> tuple[float, float, float] | None:
    heading = next((l for l in lines if ABSTRACT.fullmatch(l.text)), None)
    if heading is None:
        return None
    center = (heading.bbox[0] + heading.bbox[2]) / 2
    body = [l for l in lines if l.horizontal and l.bbox[1] >= heading.bbox[3]
            and l.bbox[0] < center < l.bbox[2] and len(l.text) > 15]
    if not body:
        return None
    first = min(body, key=lambda l: l.bbox[1])
    same_block = [l for l in body if l.key[1] == first.key[1]]
    return min(l.bbox[0] for l in same_block), max(l.bbox[2] for l in same_block), first.size


def acm_abstract_lines(pages: list, title_keys: set, body_size: float) -> set[tuple[int, int, int]]:
    """Recognize unlabeled ACM abstracts using publisher boundaries and layout.

    Require CCS/keyword/reference front matter on the first two pages. Only
    sustained, smaller-font prose above that boundary qualifies; bylines,
    addresses, footnotes and copyright text stay as original unlabelled text.
    """
    front = [(index, line) for index, (_, _, _, lines) in enumerate(pages[:2]) for line in lines]
    if any(ABSTRACT.fullmatch(line.text) for _, line in front):
        return set()
    markers = [(index, line.bbox[1]) for index, line in front if ABSTRACT_END.match(line.text)]
    if not markers:
        return set()
    boundary = min(markers)
    title_end = max((line.bbox[3] for index, line in front if line.key in title_keys), default=0)
    result = set()
    boilerplate = re.compile(r"^(?:authors?[’']?\s+(?:addresses|contact)|permission|copyright|©|[∗*†‡]|https?://|ACM\b)", re.I)
    for page_index, (width, _, blocks, lines) in enumerate(pages[:2]):
        by_block: dict[int, list[LayoutLine]] = {}
        for line in lines:
            if line.horizontal:
                by_block.setdefault(line.key[1], []).append(line)
        for block_index, group in by_block.items():
            first = group[0]
            if ((page_index, first.bbox[1]) >= boundary
                    or (page_index == 0 and first.bbox[1] <= title_end)
                    or any(line.key in title_keys for line in group)):
                continue
            text = ' '.join(line.text for line in group)
            letters = [c for c in first.text if c.isalpha()]
            typical_size = sorted(line.size for line in group)[len(group) // 2]
            if (len(group) >= 2 and len(first.text) >= 70 and len(text) >= 150
                    and sum(c.isupper() for c in letters) < len(letters) * .5
                    and body_size * .8 <= typical_size <= body_size * 1.02
                    and blocks[block_index]['bbox'][2] - blocks[block_index]['bbox'][0] >= width * .55
                    and not boilerplate.match(first.text) and not ABSTRACT_CAPTION.match(first.text)):
                result.update(line.key for line in group if (page_index, line.bbox[1]) < boundary)
    return result


def section_reading_order(blocks: list[dict], lines: list[LayoutLine], width: float,
                          body_size: float) -> list[int]:
    """Order section propagation by body columns, without changing source blocks.

    PyMuPDF's geometric sort can interleave columns and can sort a long paragraph
    below a later short heading. Only pages with sustained prose in both columns
    use this order. Full-width material separates independent horizontal bands.
    The parser still emits source chunks in their established original order.
    """
    by_block: dict[int, list[LayoutLine]] = {}
    for line in lines:
        by_block.setdefault(line.key[1], []).append(line)
    bounds = {}
    for index, block in enumerate(blocks):
        if "bbox" in block:
            bounds[index] = block["bbox"]
        elif content := by_block.get(index):
            bounds[index] = (min(l.bbox[0] for l in content), min(l.bbox[1] for l in content),
                             max(l.bbox[2] for l in content), max(l.bbox[3] for l in content))
    middle = width / 2

    def column(index: int) -> int:
        x0, _, x1, _ = bounds[index]
        return 0 if x1 <= middle + 8 else 1 if x0 >= middle - 8 else 2

    prose = {0: [], 1: []}
    for index, rect in bounds.items():
        side = column(index)
        if (side < 2 and width * .28 <= rect[2] - rect[0] <= width * .48
                and rect[3] - rect[1] > body_size * 2
                and any(l.horizontal and l.size >= body_size * .9 and len(l.text) >= 25
                        for l in by_block.get(index, []))):
            prose[side].append(rect)
    if not prose[0] or not prose[1]:
        return list(range(len(blocks)))
    overlap = min(max(r[3] for r in prose[0]), max(r[3] for r in prose[1])) - max(
        min(r[1] for r in prose[0]), min(r[1] for r in prose[1]))
    if overlap < body_size * 2:
        return list(range(len(blocks)))

    ordered: list[int] = []
    band: list[int] = []

    def flush_band() -> None:
        ordered.extend(sorted(band, key=lambda i: (column(i), bounds[i][1], i)))
        band.clear()

    for index in sorted(bounds, key=lambda i: (bounds[i][1], i)):
        x0, _, x1, _ = bounds[index]
        if x0 < middle - 12 and x1 > middle + 12 and x1 - x0 > width * .52:
            flush_band()
            ordered.append(index)
        else:
            band.append(index)
    flush_band()
    # Non-text blocks without geometry cannot affect a section, but retaining
    # their indices makes the traversal complete for unusual engine outputs.
    ordered.extend(index for index in range(len(blocks)) if index not in bounds)
    return ordered
