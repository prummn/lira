"""Conservative structure index from observed text, with original source offsets."""
from __future__ import annotations
import re
from ..models import PaperChunk


def extract_structure(chunks: list[PaperChunk]) -> dict:
    index: dict[str, list] = {'sections': [], 'figures': [], 'tables': [], 'references': []}
    sections = set()
    for chunk in sorted(chunks, key=lambda item: (item.page or 0, item.id)):
        if chunk.section and chunk.section not in sections:
            sections.add(chunk.section)
            index['sections'].append({'section': chunk.section, 'chunk_id': chunk.id, 'page': chunk.page})
        for match in re.finditer(r'(?m)^[ \t]*(?P<kind>Figure|Fig\.?|Table|图|表)\s*\d+[.:：\s][^\n]*', chunk.content, re.IGNORECASE):
            kind = match.group('kind').lower()
            index['tables' if kind in {'table', '表'} else 'figures'].append({'chunk_id': chunk.id, 'page': chunk.page, 'source_text': match.group(0).strip(), 'start': match.start(), 'end': match.end()})
        if any(term in (chunk.section or '').casefold() for term in ('references', 'bibliography', '参考文献')):
            for match in re.finditer(r'(?m)^\s*(?:\[\d+\]|\d+\.)[^\n]+', chunk.content):
                index['references'].append({'chunk_id': chunk.id, 'page': chunk.page, 'source_text': match.group(0).strip(), 'start': match.start(), 'end': match.end()})
    return index
