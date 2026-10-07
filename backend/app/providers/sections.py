"""Recover numbered ancestor headings from labels already present in the paper."""
from __future__ import annotations

import re
from ..models import PaperChunk

NUMBERED = re.compile(r'^(\d+(?:\.\d+)*)(?:\.?\s+)')


def section_contexts(chunks: list[PaperChunk]) -> dict[str, str]:
    headings: dict[str, str] = {}
    for chunk in chunks:
        match = NUMBERED.match(chunk.section or '')
        if match:
            headings.setdefault(match.group(1), chunk.section or '')
    contexts: dict[str, str] = {}
    for chunk in chunks:
        label = chunk.section or ''
        match = NUMBERED.match(label)
        labels = [label]
        if match:
            parts = match.group(1).split('.')
            labels.extend(headings[prefix] for length in range(len(parts) - 1, 0, -1)
                          if (prefix := '.'.join(parts[:length])) in headings)
        contexts[chunk.id] = '\n'.join(labels).casefold()
    return contexts
