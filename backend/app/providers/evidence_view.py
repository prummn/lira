"""Bounded synthesis views; immutable originals remain the citation authority."""
import json
import re
from collections import defaultdict


def _excerpt(text, limit, hints):
    if len(text) <= limit:
        return text
    terms = set(re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{3,}|\d+(?:\.\d+)?', hints.casefold()))
    # Keep a continuous original span; never splice words or manufacture quotes.
    starts = {0, max(0, len(text)-limit)}
    starts.update(match.end() for match in re.finditer(r'[.!?]\s+|\n', text))
    starts = sorted(start for start in starts if start <= len(text)-limit)
    def score(start):
        words = set(re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{3,}|\d+(?:\.\d+)?', text[start:start+limit].casefold()))
        return len(words & terms)
    start = max(starts, key=score)
    return text[start:start+limit]


def compact_evidence_context(context, limit):
    """Keep all propositions and source IDs, shorten only delivered quotations.

    Card IDs still resolve to FULL verified originals, including PDF geometry.
    The subsequent scientific review receives those originals and neighboring
    source context, not this display view. Never mutate the underlying pool.
    """
    if len(json.dumps(context, ensure_ascii=False)) <= limit:
        return context
    hints = defaultdict(list)
    sections = defaultdict(list)
    for source in context['evidence']:
        sections[source.get('section')].append(source['id'])
    section_index = [{'section': section, 'citation_ids': ids} for section, ids in sections.items()]
    for fact in context['facts']:
        for key in fact['citation_ids']:
            hints[key].append(fact['content'])
    def view(length):
        return {**context, 'evidence_view': 'indexed_excerpts', 'evidence_sections': section_index,
            # A fact can cite multiple sections. Preserve each source's exact
            # section in a shared index without repeating long headings.
            'evidence': [{'id': source['id'],
                'source_text': _excerpt(source['source_text'], length, ' '.join(hints[source['id']]))}
                for source in context['evidence']]}
    minimum = view(64)
    if len(json.dumps(minimum, ensure_ascii=False)) > limit:
        # Facts/metadata themselves need reduction; never drop a fact or ID.
        return context
    low, high, best = 64, max((len(source['source_text']) for source in context['evidence']), default=64), minimum
    while low <= high:
        middle = (low+high)//2
        candidate = view(middle)
        if len(json.dumps(candidate, ensure_ascii=False)) <= limit:
            best, low = candidate, middle+1
        else:
            high = middle-1
    return best
