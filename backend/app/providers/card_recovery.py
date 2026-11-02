"""Select rejected card slots and apply independently validated replacements."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import re

from .base import ProviderError
from .cards import CARD_ALIASES, LIST_FIELDS, SINGLE_FIELDS, field_schema

MAX_REJECTED_VALUE_CHARS = 12000
MAX_REJECTED_TEXT_CHARS = 24000


def section_repair_context(context: dict, targets: list[dict]) -> dict | None:
    """Repair heading metadata with complete cited sources, not the whole paper.

    Unknown IDs, truncated targets and semantic/content faults still need the
    broader context. Keep every source of each selected cross-section fact.
    """
    refs = set()
    if not targets:
        return None
    for target in targets:
        if (target.get('reason_codes') != ['section_mismatch']
                or not target.get('rejected_value_complete')):
            return None
        try:
            value = json.loads(target['rejected_value'])
        except (KeyError, ValueError, TypeError):
            return None
        ids = value.get('citation_ids') if isinstance(value, dict) else None
        if not isinstance(ids, list) or not ids or not all(isinstance(key, str) for key in ids):
            return None
        refs.update(ids)
    available = {source['id'] for source in context['evidence']}
    if not refs <= available:
        return None
    facts = [fact for fact in context['facts'] if refs.intersection(fact['citation_ids'])]
    if not facts:
        return None
    refs.update(key for fact in facts for key in fact['citation_ids'])
    return {'facts': facts, 'evidence': [source for source in context['evidence'] if source['id'] in refs]}


def repair_targets(data: dict, rejections: list[dict]) -> list[dict]:
    raw = data.get('card') if isinstance(data.get('card'), dict) else data
    targets = {}
    for rejection in rejections:
        match = re.fullmatch(r'([a-z_]+)(?:\[(\d+)\])?', rejection['field'])
        if not match or match[1] not in (*SINGLE_FIELDS, *LIST_FIELDS):
            continue
        field, index = match[1], match[2]
        value = raw.get(field, raw.get(CARD_ALIASES.get(field, field)))
        if index is not None:
            if not isinstance(value, list) or int(index) >= len(value):
                continue
            value = value[int(index)]
        path = field if index is None else f'{field}[{index}]'
        rejected_value = json.dumps(value, ensure_ascii=False)
        target = targets.setdefault(path, {'field': path, 'reason_codes': [],
            'value_schema': field_schema(field, indexed=index is not None),
            'rejected_value': rejected_value[:MAX_REJECTED_VALUE_CHARS],
            'rejected_value_complete': len(rejected_value) <= MAX_REJECTED_VALUE_CHARS})
        if rejection['reason'] not in target['reason_codes']:
            target['reason_codes'].append(rejection['reason'])
    # Local paths/reasons are bounded; the earlier model output is untrusted.
    selected = list(targets.values())[:16]
    remaining = MAX_REJECTED_TEXT_CHARS
    for target in selected:
        value = target['rejected_value']
        target['rejected_value'] = value[:remaining]
        target['rejected_value_complete'] &= len(value) <= remaining
        remaining -= len(target['rejected_value'])
    return selected


def apply_repairs(data: dict, targets: list[dict], repairs: object, validate) -> tuple[dict, set[str]]:
    patched = deepcopy(data)
    raw = patched.get('card') if isinstance(patched.get('card'), dict) else patched
    allowed = {target['field'] for target in targets}
    if not isinstance(repairs, list) or len(repairs) > 32:
        return patched, set()
    counts = Counter(item.get('field') for item in repairs
        if isinstance(item, dict) and isinstance(item.get('field'), str))
    resolved = set()
    for item in repairs:
        if not isinstance(item, dict) or not isinstance(item.get('field'), str):
            continue
        path = item['field']
        if path not in allowed or counts[path] != 1:
            continue
        match = re.fullmatch(r'([a-z_]+)(?:\[(\d+)\])?', path)
        field, index = match[1], match[2]
        value = item.get('value')
        # An individual TLDR line has the same citation/content contract as a
        # claim. Cardinality is checked on the complete patched card later;
        # do not replace already accepted lines to fix one bad line.
        candidate_field = 'claims' if field == 'tldr' and index is not None else field
        candidate = {candidate_field: [value] if index is not None else value}
        try:
            analysis, invalid = validate(candidate)
        except ProviderError:
            continue
        # null/[] drops the requested claim; it must never count as a repair.
        if invalid or not analysis.card.get(candidate_field):
            continue
        if index is None:
            raw[field] = value
        else:
            values = raw.get(field)
            if not isinstance(values, list) or int(index) >= len(values):
                continue
            values[int(index)] = value
        resolved.add(path)
    return patched, resolved


def resolved_field(path: str, resolved: set[str]) -> bool:
    return path in resolved or path.split('[', 1)[0] in resolved


def preserves_entries(original, corrected) -> bool:
    """Whole-card validation must retain every previously accepted entry."""
    if original is None:
        return True
    for field, value in original.card.items():
        accepted = value if isinstance(value, list) else [value] if value else []
        current = corrected.card.get(field)
        candidates = iter(current if isinstance(current, list) else [current] if current else [])
        # Order and duplicate multiplicity are preserved, as well as content,
        # source quotations and the local source objects used for geometry.
        if any(not any(entry == candidate for candidate in candidates) for entry in accepted):
            return False
    return True
