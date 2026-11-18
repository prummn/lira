"""Validate citations against supplied source text, allowing whitespace differences only."""
from __future__ import annotations
import re
import unicodedata
from ..models import PaperChunk


def chunk_body(chunk: PaperChunk) -> str:
    lines = chunk.content.splitlines()
    if chunk.section:
        heading = ' '.join(chunk.section.split())
        for count in range(1, min(len(lines), 4) + 1):
            prefix = ' '.join(' '.join(lines[:count]).split())
            if prefix == heading:
                return '\n'.join(lines[count:]).strip()
            if len(prefix) > len(heading):
                break
    return chunk.content.strip()


def _quote_view(value: str, *, with_spans: bool = False):
    """Return a comparison view while retaining spans in the original text.

    PDF extraction commonly leaves a word split as ``state-of-\\nthe-art`` or
    emits typography ligatures such as ``ﬁ``.  These are visual formatting
    differences, so accepting them is safe when the normalized text still
    matches exactly; the returned span remains the original stored evidence.
    """
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char in '-\\u2010\\u2011\\u2012\\u2013\\u2014' and index + 1 < len(value):
            cursor = index + 1
            while cursor < len(value) and value[cursor].isspace():
                cursor += 1
            if (index > 0 and value[index - 1].isalnum() and cursor < len(value)
                    and value[cursor].isalnum()):
                index = cursor
                continue
        if char == '\\u00ad':
            index += 1
            continue
        if char.isspace():
            cursor = index + 1
            while cursor < len(value) and value[cursor].isspace():
                cursor += 1
            if not chars or chars[-1] != ' ':
                chars.append(' ')
                starts.append(index)
                ends.append(cursor)
            else:
                ends[-1] = cursor
            index = cursor
            continue
        normalized = unicodedata.normalize('NFKC', char).casefold()
        for item in normalized:
            chars.append(item)
            starts.append(index)
            ends.append(index + 1)
        index += 1
    result = ''.join(chars)
    return (result, starts, ends) if with_spans else result


def canonical_quote(source: str, quote: str, *, allow_pdf_formatting: bool = False) -> str | None:
    if not quote or not quote.strip():
        return None
    if quote in source:
        return quote
    if allow_pdf_formatting:
        normalized_source, starts, ends = _quote_view(source, with_spans=True)
        normalized_quote = _quote_view(quote).strip()
        if normalized_quote:
            match = normalized_source.find(normalized_quote)
            if match >= 0:
                start = starts[match]
                end = ends[match + len(normalized_quote) - 1]
                return source[start:end]
    parts = quote.split()
    if not parts:
        return None
    match = re.search(r'\s+'.join(re.escape(part) for part in parts), source)
    return match.group(0) if match else None


def canonical_elided_quote(source: str, quote: str) -> str | None:
    """Recover the literal span around explicitly omitted text in one source.

    Every excerpt must match, in order, with whitespace differences only. The
    returned evidence includes the omitted original text; no fuzzy matching,
    cross-block stitching, or acceptance of partly invented quotes is allowed.
    """
    parts = re.split(r'\s*(?:\[(?:\s*(?:\.{3,}|…+)\s*)\]|\.{3,}|…+)\s*', quote)
    if not 2 <= len(parts) <= 4 or any(len(part.strip()) < 12 for part in parts):
        return None
    cursor = 0
    start = None
    for part in parts:
        literal = canonical_quote(source[cursor:], part.strip())
        if literal is None:
            return None
        offset = source.find(literal, cursor)
        if start is None:
            start = offset
        cursor = offset + len(literal)
    return source[start:cursor]


def canonical_quote_across(sources: list[str], quote: str) -> tuple[str, int] | None:
    """Match a selection that crosses PDF extraction blocks.

    PDF.js can return one visual selection while the importer stores the same
    sentence in two columns, pages, or blocks around a figure.  Matching a
    whitespace-normalized concatenation keeps the source boundary explicit and
    returns the first block containing the evidence anchor.
    """
    if not quote or not quote.strip() or not sources:
        return None
    parts = quote.split()
    if not parts:
        return None
    for start in range(len(sources)):
        joined = ' '.join(sources[start:start + 6])
        match = re.search(r'\s+'.join(re.escape(part) for part in parts), joined)
        if match:
            return match.group(0), start
    return None


def _selection_tokens(value: str) -> list[str]:
    """Tokenize PDF text after removing line-break hyphenation artifacts."""
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "", value.casefold())
    # Unicode words retain Greek variables/names and accented prose. The old
    # ASCII-only pattern silently discarded α/β and could validate a changed
    # variable as the same source.
    value = unicodedata.normalize('NFKC', value)
    return re.findall(r"[^\W_]+(?:[-'][^\W_]+)*|[^\w\s]", value)


def resolve_selection_chunks(chunks, quote: str, *, preferred_page: int | None = None):
    """Resolve a browser selection to the source blocks that produced it.

    PDF.js selections are visual ranges, while extraction chunks are storage
    blocks. A range can therefore start in one block, cross a table/column and
    finish in another. The old validator only searched a six-block window from
    the guessed block, which rejected legitimate long selections. This matcher
    consumes the selected token stream against the longest matching run in each
    candidate block and returns the blocks in the selection's text order.
    """
    if not quote or not chunks:
        return None
    ordered = list(chunks)
    if preferred_page is not None:
        nearby = [chunk for chunk in ordered if chunk.page is not None and abs(chunk.page - preferred_page) <= 1]
        if nearby:
            ordered = nearby + [chunk for chunk in ordered if chunk not in nearby]
    for chunk in ordered:
        matched = canonical_quote(chunk.content, quote)
        if matched is not None:
            return chunk, [chunk], matched
    query = _selection_tokens(quote)
    if len(query) < 3:
        return None
    tokenized = [(chunk, _selection_tokens(chunk.content)) for chunk in ordered]
    used: set[str] = set()
    matched_chunks = []
    cursor = 0
    while cursor < len(query):
        best = None
        for chunk, source in tokenized:
            if chunk.id in used:
                continue
            run = 0
            for start, token in enumerate(source):
                if token != query[cursor]:
                    continue
                length = 0
                while (start + length < len(source) and cursor + length < len(query)
                       and source[start + length] == query[cursor + length]):
                    length += 1
                if length > run:
                    run = length
            if run and (best is None or run > best[0]):
                best = (run, chunk)
        if best is None or best[0] < 2:
            return None
        run, chunk = best
        used.add(chunk.id)
        matched_chunks.append(chunk)
        cursor += run
    if cursor != len(query):
        return None
    return matched_chunks[0], matched_chunks, quote.strip()
