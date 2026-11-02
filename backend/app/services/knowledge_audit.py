"""Read-only, deterministic projections over paper knowledge evidence.

The audit deliberately does not call a provider.  It reports what is already
stored and what the source text mentions, preserving review lifecycle state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..models import Paper
from .knowledge import normalize_name


@dataclass(frozen=True)
class KnowledgeAudit:
    paper_id: str
    coverage: dict[str, dict[str, dict]]
    suggestions: list[dict]

    def model_dump(self) -> dict:
        return {'paper_id': self.paper_id, 'coverage': self.coverage, 'suggestions': self.suggestions}


CATEGORIES = ('method', 'component', 'dataset', 'benchmark', 'metric', 'baseline', 'ablation', 'task', 'related_method', 'concept', 'paper', 'venue')


def _stored_evidence(candidate) -> list[dict]:
    try:
        raw = json.loads(candidate.evidence_json or '[]')
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get('quote') and item.get('chunk_id')]


def _source_hits(paper: Paper, aliases: tuple[str, ...]) -> list[dict]:
    hits: list[dict] = []
    patterns = [re.compile(r'(?<![\w])' + re.escape(alias) + r'(?![\w])', re.IGNORECASE) for alias in aliases]
    for chunk in paper.chunks:
        content = chunk.content or ''
        if re.match(r'^(?:[\d.]+\s*)?(references|bibliography|参考文献)\b', (chunk.section or '').strip(), re.I):
            continue
        if re.match(r'^\s*(references|bibliography)\s*\n', content, re.I):
            continue
        matches = [match for pattern in patterns if (match := pattern.search(content))]
        if not matches:
            continue
        match = min(matches, key=lambda item: item.start())
        start, end = max(0, match.start()-250), min(len(content), match.end()+750)
        hits.append({'chunk_id': chunk.id, 'page': chunk.page, 'section': chunk.section, 'quote': content[start:end]})
    return hits


def _category_for_candidate(candidate) -> str:
    from .knowledge_identity import effective_kind
    kind = effective_kind(candidate)
    role = (candidate.role or '').lower()
    if kind in {'dataset', 'benchmark', 'task', 'metric'}:
        return kind
    if role == 'baseline':
        return 'baseline'
    if role == 'ablation':
        return 'ablation'
    if role == 'component':
        return 'component'
    if role in {'compared', 'cited'} and kind == 'method':
        return 'related_method'
    return kind


def audit_paper_knowledge(paper: Paper) -> KnowledgeAudit:
    from sqlalchemy import select
    from sqlalchemy.orm import object_session
    from ..models import KnowledgeEntity
    from .knowledge_identity import ambiguous_aliases, match_candidate

    candidates = list(paper.knowledge_candidates or [])
    coverage = {category: {} for category in CATEGORIES}
    suggestions = []
    for candidate in candidates:
        category = _category_for_candidate(candidate)
        name = candidate.entity.name if candidate.entity and candidate.entity.status == 'active' else candidate.name
        state = ('ignored' if candidate.status == 'rejected' else
            'confirmed' if candidate.status in {'confirmed', 'known', 'alias'} else 'candidate')
        coverage.setdefault(category, {})[name] = {
            'name': name, 'state': state, 'candidate_id': candidate.id,
            'evidence_count': len(_stored_evidence(candidate)), 'why': f'候选状态为 {candidate.status}',
        }

    # Check only actual mentions of existing library identities. This is a
    # source-grounded review aid, never a completeness score for the field.
    session = object_session(paper)
    entities = session.scalars(select(KnowledgeEntity).where(KnowledgeEntity.status == 'active')).all() if session else []
    blocked = ambiguous_aliases([*candidates, *entities])
    for entity in entities:
        aliases = tuple(json.loads(entity.aliases_json or '[]'))
        if match_candidate(candidates, entity.entity_type, entity.name, aliases, entity.id, blocked):
            continue
        names = tuple(name for name in (entity.name, *aliases)
            if (entity.entity_type, normalize_name(name)) not in blocked)
        hits = _source_hits(paper, names)
        if not hits:
            continue
        why = '正文提及已有知识对象，尚未建立本文来源；请核对是否指同一对象'
        coverage.setdefault(entity.entity_type, {})[entity.name] = {
            'name': entity.name, 'state': 'missing', 'candidate_id': None,
            'evidence_count': len(hits), 'why': why,
        }
        suggestions.append({'name': entity.name, 'entity_type': entity.entity_type,
            'why': why, 'evidence': hits[:2]})
    return KnowledgeAudit(paper_id=paper.id, coverage=coverage, suggestions=suggestions)
