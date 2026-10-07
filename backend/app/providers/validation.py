"""Validate citations against supplied source text, allowing whitespace differences only."""
from __future__ import annotations
import re
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


def canonical_quote(source: str, quote: str) -> str | None:
    if not quote or not quote.strip():
        return None
    if quote in source:
        return quote
    parts = quote.split()
    if not parts:
        return None
    match = re.search(r'\s+'.join(re.escape(part) for part in parts), source)
    return match.group(0) if match else None
