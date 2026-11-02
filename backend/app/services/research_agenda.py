"""Finite topic investigations, planned once per source snapshot.

Plans and investigations share ResearchTask persistence and the one worker.
They produce findings, never graph mutations or further plans.
"""
import hashlib
import json
import re
import uuid

from sqlalchemy import select

from ..models import PaperChunk, ResearchFinding, ResearchFindingRevision, ResearchTask
from ..providers.validation import canonical_quote
from .research_findings import KINDS, list_findings
from .research_materials import PROMPTS, dumps, snapshot, snapshot_fingerprint

DEEP_KINDS = ('agenda', 'investigation')


def source_fingerprint(db, paper_ids):
    """Include text outside the initial, bounded synthesis sample."""
    rows = db.execute(select(PaperChunk.paper_id, PaperChunk.id, PaperChunk.page,
        PaperChunk.section, PaperChunk.content).where(PaperChunk.paper_id.in_(paper_ids))
        .order_by(PaperChunk.paper_id, PaperChunk.id)).all()
    return hashlib.sha256(dumps([list(row) for row in rows]).encode()).hexdigest()


def sources_match(db, material):
    """Validate actual read passages when adopting pre-digest checkpoints."""
    for source in material['sources']:
        row = db.get(PaperChunk, source['chunk_id'])
        if row is None or (row.paper_id, row.page, row.section, row.content) != (
                source['paper_id'], source['page'], source['section'], source['text']):
            return False
    return True


def target_active(db, collection_id, brief):
    target = brief.get('existing_id')
    if not target:
        return True
    row = db.get(ResearchFinding, target)
    return bool(row and row.collection_id == collection_id and row.kind == brief['kind']
                and row.status not in {'dismissed', 'done'})


def bind_target(data, material):
    """A targeted deepening must revise its original finding, even if renamed."""
    target = material['investigation'].get('existing_id')
    items = data.get('findings')
    if material.get('origin') and not target and isinstance(items, list):
        if len(items) > 1 or any(isinstance(item, dict) and item.get('existing_id') for item in items):
            raise ValueError('新阅读问题不能覆盖其他问题的答案；已有完整答案请使用answered_by引用')
    if target and isinstance(items, list) and items:
        if len(items) != 1 or not isinstance(items[0], dict) or items[0].get('existing_id') not in (None, target):
            raise ValueError('定向深化只能更新任务指定的原线索')
        items[0]['existing_id'] = target


def validate_plan(data, material, existing):
    tasks = data.get('tasks') if isinstance(data, dict) else None
    if not isinstance(tasks, list) or len(tasks) > 6:
        raise ValueError('研究议程须为至多6项的列表')
    papers = {p['id'] for p in material['papers']}
    previous = {i['id']: i for i in existing}
    seen, seen_titles, updated, result = set(), set(), set(), []
    normalize = lambda text: re.sub(r'\W+', '', text.casefold())
    for item in tasks:
        if not isinstance(item, dict) or KINDS.get(item.get('kind')) not in material['work_types']:
            raise ValueError('议程产出类型不在专题选择范围')
        for key, limit in [('title', 200), ('question', 2000), ('rationale', 1000)]:
            if not isinstance(item.get(key), str) or not 4 <= len(item[key].strip()) <= limit:
                raise ValueError('研究任务缺少明确问题或动机')
        ids = item.get('paper_ids')
        if not isinstance(ids, list) or not ids or len(ids) > 4 or any(not isinstance(p, str) or p not in papers for p in ids):
            raise ValueError('研究任务只能阅读本专题中至多4篇论文')
        if item['kind'] == 'connection' and len(set(ids)) < 2:
            raise ValueError('跨论文研究至少需要两篇论文')
        hints = item.get('section_hints', [])
        if not isinstance(hints, list) or len(hints) > 10 or any(not isinstance(h, str) or len(h) > 160 for h in hints):
            raise ValueError('研究章节提示格式无效')
        existing_id = item.get('existing_id')
        if existing_id is not None:
            prior = previous.get(existing_id)
            if not prior or prior['kind'] != item['kind'] or prior['status'] in {'dismissed', 'done'} or existing_id in updated:
                raise ValueError('只能深化本专题同类型且未忽略的已有线索')
            updated.add(existing_id)
        key = normalize(item['question'])
        title = normalize(item['title'])
        if not key or key in seen or title in seen_titles:
            raise ValueError('研究议程包含重复问题')
        seen.add(key)
        seen_titles.add(title)
        result.append({**{k: item[k].strip() for k in ('title', 'question', 'rationale', 'kind')},
                       'paper_ids': sorted(set(ids)), 'section_hints': hints, 'existing_id': existing_id})
    return result


def enqueue_plan(db, collection_id, focus, work_types):
    if not set(work_types) - {'essay', 'reading'}:
        return None
    material, base = snapshot(db, collection_id, focus, kind='findings', work_types=work_types)
    if not material['sources']:
        return None
    initial = db.scalar(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
        ResearchTask.kind == 'findings', ResearchTask.fingerprint == base))
    if initial is None:
        initial = next((t for t in db.scalars(select(ResearchTask).where(
            ResearchTask.collection_id == collection_id, ResearchTask.kind == 'findings'))
            if snapshot_fingerprint(json.loads(t.material_json)) == base), None)
    if initial is None or initial.status != 'completed':
        return None
    recipe = [(PROMPTS / f'research_{stage}.txt').read_text(encoding='utf-8') for stage in ('plan', 'investigate')]
    full = source_fingerprint(db, [p['id'] for p in material['papers']])
    fingerprint = hashlib.sha256(dumps(['agenda-v2', base, full, recipe]).encode()).hexdigest()
    previous = db.scalar(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
                                                  ResearchTask.fingerprint == fingerprint))
    if previous:
        return previous
    # Reading-intent separation and selection improvements must not replay an
    # already finished plan on unchanged papers. Preserve its calls and history.
    for candidate in db.scalars(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
            ResearchTask.kind == 'agenda', ResearchTask.status == 'completed')):
        stored = json.loads(candidate.material_json)
        if stored.get('_source_fingerprint') == full and snapshot_fingerprint(stored) == base:
            return candidate
    # Adopt this session's earlier tasks without repeating official calls.
    # Every passage they actually read must still match the local source.
    legacy_key = hashlib.sha256(dumps(['agenda-v1', base, recipe]).encode()).hexdigest()
    legacy = db.scalar(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
                                                ResearchTask.fingerprint == legacy_key))
    if legacy:
        old = json.loads(legacy.material_json)
        children = [(child, json.loads(child.material_json)) for child in db.scalars(select(ResearchTask).where(
            ResearchTask.collection_id == collection_id, ResearchTask.kind == 'investigation'))]
        children = [(child, stored) for child, stored in children if stored.get('_plan_id') == legacy.id]
        if ('_source_fingerprint' not in old and sources_match(db, old)
                and all(sources_match(db, stored) for _, stored in children)):
            legacy.fingerprint = fingerprint
            legacy.material_json = dumps({**old, '_source_fingerprint': full})
            for child, stored in children:
                child.material_json = dumps({**stored, '_source_fingerprint': full})
            db.flush()
            return legacy
    task = ResearchTask(id='research-' + uuid.uuid4().hex, collection_id=collection_id, kind='agenda',
                        stage='plan', fingerprint=fingerprint,
                        material_json=dumps({**material, '_base_fingerprint': base, '_source_fingerprint': full}))
    db.add(task)
    db.flush()
    return task


def plan_context(db, material, collection_id):
    sections = {}
    samples = []
    for source in material['sources']:
        key = (source['paper_id'], source['section'])
        if key not in sections:
            sections[key] = True
            if len(samples) < 100:
                samples.append({**source, 'text': source['text'][:1000]})
    existing = [{**{k: item[k] for k in ('id', 'kind', 'title', 'body', 'next_step', 'status')},
                 'papers': sorted({source['paper_id'] for source in item['sources']})}
                for item in list_findings(db, collection_id)]
    return {'topic': material['collection'], 'focus': material['focus'], 'work_types': material['work_types'],
            'papers': material['papers'], 'coverage': material['coverage'],
            'section_samples': samples, 'existing_findings': existing}


def investigation_material(db, collection_id, base, brief, material):
    """Select from full local text, including appendices omitted by initial synthesis."""
    papers = [p for p in material['papers'] if p['id'] in brief['paper_ids']]
    sources, coverage, section_index = [], [], []
    prior = list_findings(db, collection_id)
    reused = []
    terms = set(re.findall(r'[a-z][a-z0-9_-]{3,}', brief['question'].casefold()))
    hints = [h.casefold() for h in brief['section_hints'] if h.strip()]
    budget = min(24000, 64000 // max(1, len(papers)))
    natural = lambda text: tuple(int(x) if x.isdigit() else x for x in re.split(r'(\d+)', text))
    for paper in papers:
        chunks = list(db.scalars(select(PaperChunk).where(PaperChunk.paper_id == paper['id'])).all())
        chunks.sort(key=lambda c: (c.page or 0, natural(c.id)))
        by_id = {c.id: c for c in chunks}
        anchor = material.get('origin', {})
        preferred = {anchor.get('chunk_id')} if anchor.get('paper_id') == paper['id'] else set()
        for item in prior:
            if item['status'] in ('dismissed', 'done'):
                continue
            for source in item['sources']:
                chunk = by_id.get(source.get('chunk_id'))
                quote = source.get('quote', '')
                if (chunk and len(reused) < 12 and len(quote) >= 18 and
                        canonical_quote(chunk.content, quote, allow_pdf_formatting=True)):
                    preferred.add(chunk.id)
                    reused.append(dict(finding_id=item['id'], title=item['title'],
                        interpretation=item['body'][:1500], chunk_id=chunk.id, quote=quote))
        for index, chunk in enumerate(chunks):
            selected_text = anchor.get('selected_text') or ''
            selection_matches = len(selected_text) >= 12 and canonical_quote(chunk.content, selected_text, allow_pdf_formatting=True)
            if chunk.id == anchor.get('chunk_id') or selection_matches or (anchor.get('page') == chunk.page and
                    anchor.get('paper_id') == paper['id']):
                preferred.update(c.id for c in chunks[max(0, index-1):index+2])
        def score(chunk):
            heading = (chunk.section or '').casefold()
            match = 30 if any(h in heading or heading and heading in h for h in hints) else 0
            words = set(re.findall(r'[a-z][a-z0-9_-]{3,}', chunk.content.casefold()))
            return (100 if chunk.id in preferred else 0) + match + len(terms & words) - (50 if re.match(r'^references?\b', heading) else 0)
        chosen, used = set(), 0
        for chunk in sorted(chunks, key=score, reverse=True):
            if score(chunk) <= 0 and len(chosen) >= 4:
                continue
            if used + len(chunk.content) > budget:
                continue
            chosen.add(chunk.id)
            used += len(chunk.content)
        for chunk in chunks:
            if chunk.id in chosen:
                sources.append({'id': f'S{len(sources)+1}', 'paper_id': paper['id'], 'title': paper['title'],
                    'chunk_id': chunk.id, 'page': chunk.page, 'section': chunk.section, 'text': chunk.content})
        coverage.append({'paper_id': paper['id'], 'title': paper['title'],
                         'total_chars': sum(len(c.content) for c in chunks), 'included_chars': used,
                         'chunks': len(chosen)})
        groups = {}
        for chunk in chunks:
            group = groups.setdefault(chunk.section or '未标注章节', {'section': chunk.section or '未标注章节',
                'pages': [], 'chunks': 0, 'included_chunks': 0})
            group['chunks'] += 1
            group['included_chunks'] += chunk.id in chosen
            if chunk.page not in group['pages']:
                group['pages'].append(chunk.page)
        section_index.append({'paper_id': paper['id'], 'title': paper['title'], 'sections': list(groups.values())})
    selected_ids = {s['chunk_id']: s['id'] for s in sources}
    reused = [{**r, 'source_id': selected_ids[r['chunk_id']]} for r in reused if r['chunk_id'] in selected_ids]
    return {**material, 'papers': papers, 'sources': sources, 'coverage': coverage,
            'section_index': section_index, 'reused_evidence': reused,
            'work_types': [KINDS[brief['kind']]], 'investigation': brief,
            '_base_fingerprint': base}


def expand_material(db, material, requests):
    """One bounded follow-up read, using exact headings from the local index."""
    if not isinstance(requests, list) or not 1 <= len(requests) <= 4:
        raise ValueError('扩读须指定至多四篇目标论文')
    allowed = {p['paper_id']: {s['section'] for s in p['sections']} for p in material['section_index']}
    sources = list(material['sources'])
    present = {s['chunk_id'] for s in sources}
    added = 0
    for request in requests:
        if not isinstance(request, dict):
            raise ValueError('扩读请求格式无效')
        paper_id, sections = request.get('paper_id'), request.get('sections')
        if (paper_id not in allowed or not isinstance(sections, list) or not 1 <= len(sections) <= 3
                or any(not isinstance(s, str) or s not in allowed[paper_id] for s in sections)):
            raise ValueError('扩读章节不属于目标论文目录')
        title = next(p['title'] for p in material['papers'] if p['id'] == paper_id)
        for chunk in db.scalars(select(PaperChunk).where(PaperChunk.paper_id == paper_id).order_by(PaperChunk.page, PaperChunk.id)):
            if chunk.id in present or (chunk.section or '未标注章节') not in sections or added+len(chunk.content) > 64000:
                continue
            present.add(chunk.id)
            added += len(chunk.content)
            sources.append(dict(id=f'S{len(sources)+1}', paper_id=paper_id, title=title,
                chunk_id=chunk.id, page=chunk.page, section=chunk.section, text=chunk.content))
    if not added:
        raise ValueError('指定章节没有可新增的原文，请根据已提供材料回答')
    coverage = [{**c, 'included_chars': sum(len(s['text']) for s in sources if s['paper_id'] == c['paper_id']),
                 'chunks': sum(s['paper_id'] == c['paper_id'] for s in sources)} for c in material['coverage']]
    section_index = [{**paper, 'sections': [{**section, 'included_chunks': sum(
        s['paper_id'] == paper['paper_id'] and (s['section'] or '未标注章节') == section['section'] for s in sources)}
        for section in paper['sections']]} for paper in material['section_index']]
    return {**material, 'sources': sources, 'coverage': coverage, 'section_index': section_index}


def create_investigations(db, parent, briefs):
    material = json.loads(parent.material_json)
    for brief in briefs:
        if not target_active(db, parent.collection_id, brief):
            continue
        key = hashlib.sha256(dumps(['investigation-v1', parent.fingerprint, brief]).encode()).hexdigest()
        if db.scalar(select(ResearchTask.id).where(ResearchTask.collection_id == parent.collection_id,
                                                  ResearchTask.fingerprint == key)):
            continue
        selected = investigation_material(db, parent.collection_id, material['_base_fingerprint'], brief, material)
        selected['_plan_id'] = parent.id
        if not selected['sources']:
            raise ValueError('研究任务缺少可读取的原文')
        db.add(ResearchTask(id='research-' + uuid.uuid4().hex, collection_id=parent.collection_id,
            kind='investigation', stage='discover', fingerprint=key, material_json=dumps(selected)))
    db.flush()


def agenda_state(db, collection_id, read_task):
    rows = db.scalars(select(ResearchTask).where(ResearchTask.collection_id == collection_id,
        ResearchTask.kind.in_(DEEP_KINDS)).order_by(ResearchTask.created_at.desc(), ResearchTask.id)).all()
    planner = next((t for t in rows if t.kind == 'agenda'), None)
    children = [t for t in rows if t.kind == 'investigation' and
                (json.loads(t.material_json).get('_plan_id') == (planner.id if planner else None)
                 or json.loads(t.material_json).get('origin'))]
    outcomes = {}
    if children:
        for revision in db.scalars(select(ResearchFindingRevision).where(
                ResearchFindingRevision.task_id.in_([t.id for t in children]))).all():
            outcomes.setdefault(revision.task_id, []).append(revision.finding_id)
        for child in children:
            reused = json.loads(child.checkpoint_json).get('reused_answer')
            if reused and child.status == 'completed' and db.get(ResearchFinding, reused):
                outcomes.setdefault(child.id, []).append(reused)
    tasks = []
    for row in sorted(children, key=lambda t: (t.created_at, t.id)):
        brief = json.loads(row.material_json)['investigation']
        tasks.append({**read_task(row), **brief, 'origin': json.loads(row.material_json).get('origin'),
                      'outcome_ids': sorted(set(outcomes.get(row.id, [])))})
    return {'planner': read_task(planner) if planner else None, 'tasks': tasks}
