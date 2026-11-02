"""Snapshot original passages and human questions without modifying knowledge."""
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import select

from ..models import Collection, CollectionPaper, Note, Paper, PaperChunk, KnowledgeCandidate

PIPELINE_VERSION = 'collection-notes-v2'
PROMPTS = Path(__file__).resolve().parents[3] / 'prompts'


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def snapshot_fingerprint(material):
    """Reading intents get their own queue; drawing a highlight cannot rewrite a topic."""
    basis = {k: material[k] for k in ('version', 'recipe', 'collection', 'description', 'focus',
                                    'papers', 'sources', 'coverage') if k in material}
    basis['papers'] = [{**paper, 'notes': [n for n in paper.get('notes', [])
        if n['kind'] not in ('question', 'highlight')]} for paper in basis['papers']]
    if 'purpose' in material:
        basis.update(purpose=material['purpose'], work_types=sorted(set(material['work_types'])-{'reading'}))
    return hashlib.sha256(dumps(basis).encode()).hexdigest()


def snapshot(db, collection_id, focus, *, kind='essay', work_types=None):
    collection = db.get(Collection, collection_id)
    papers = db.scalars(select(Paper).join(CollectionPaper).where(
        CollectionPaper.collection_id == collection_id).order_by(Paper.id)).all()
    recipe = {stage: (PROMPTS / f'research_{stage}.txt').read_text(encoding='utf-8')
              for stage in (('discover', 'assess') if kind == 'findings' else ('synthesis', 'draft', 'review'))}
    material = {'version': PIPELINE_VERSION, 'recipe': hashlib.sha256(dumps(recipe).encode()).hexdigest(),
                'collection': collection.name,
                'description': collection.description, 'focus': focus, 'papers': [], 'sources': [], 'coverage': []}
    if kind == 'findings':
        material.update(purpose='findings-v1', work_types=sorted(set(work_types or []) - {'essay', 'reading'}))
    budget = max(3000, min(80000, 220000 // max(1, len(papers))))
    for paper in papers:
        chunks = db.scalars(select(PaperChunk).where(PaperChunk.paper_id == paper.id)).all()
        natural = lambda s: tuple(int(x) if x.isdigit() else x for x in re.split(r'(\d+)', s))
        chunks = sorted(chunks, key=lambda c: (c.page or 0, natural(c.id)))
        available = sum(len(c.content) for c in chunks)
        # Keep every section represented if the full text exceeds the per-paper share.
        selected, used = [], 0
        if available <= budget:
            selected = chunks
        else:
            groups = {}
            for chunk in chunks:
                groups.setdefault(chunk.section or f'page-{chunk.page}', []).append(chunk)
            per_group = max(500, budget // max(1, len(groups)))
            for group in groups.values():
                section_used = 0
                for chunk in group:
                    if used + len(chunk.content) > budget or section_used >= per_group:
                        continue
                    selected.append(chunk)
                    used += len(chunk.content)
                    section_used += len(chunk.content)
            selected.sort(key=lambda c: (c.page or 0, natural(c.id)))
        notes = db.scalars(select(Note).where(Note.paper_id == paper.id).order_by(Note.id)).all()
        concepts = db.scalars(select(KnowledgeCandidate).where(KnowledgeCandidate.paper_id == paper.id,
            KnowledgeCandidate.status == 'confirmed').order_by(KnowledgeCandidate.id)).all()
        material['papers'].append({'id': paper.id, 'title': paper.title, 'year': paper.year,
            'abstract': paper.abstract, 'notes': [{'kind': n.kind, 'text': n.content, 'source': n.source_text} for n in notes],
            'confirmed_index': [{'name': c.name, 'kind': c.entity_type, 'description': c.description} for c in concepts]})
        for chunk in selected:
            material['sources'].append({'id': f'S{len(material["sources"])+1}', 'paper_id': paper.id,
                'title': paper.title, 'chunk_id': chunk.id, 'page': chunk.page, 'section': chunk.section,
                'text': chunk.content})
        material['coverage'].append({'paper_id': paper.id, 'title': paper.title, 'total_chars': available,
                                    'included_chars': sum(len(c.content) for c in selected), 'chunks': len(selected)})
    fingerprint = snapshot_fingerprint(material)
    return material, fingerprint


def verify_synthesis(data, material):
    sources = {s['id']: s for s in material['sources']}
    evidence = data.get('evidence')
    if not isinstance(evidence, list) or not evidence or len(evidence) > 80:
        raise ValueError('研读结果缺少可追溯的原文证据')
    normalize = lambda value: re.sub(r'\s+', '', value).casefold()
    verified = []
    for item in evidence:
        source = sources.get(item.get('source_id')) if isinstance(item, dict) else None
        quote = item.get('quote') if isinstance(item, dict) else None
        if source is None or not isinstance(quote, str) or len(quote.strip()) < 18 or normalize(quote) not in normalize(source['text']):
            raise ValueError('研读引文与原文不匹配；未发布文章')
        verified.append({**source, 'quote': quote, 'claim': str(item.get('claim', ''))[:3000]})
    covered = {s['paper_id'] for s in verified}
    required = {s['paper_id'] for s in material['sources']}
    if covered != required:
        raise ValueError('研读未覆盖专题中的全部可读论文')
    verify_teaching(data.get('teaching'), verified)
    return verified


def verify_teaching(plan, sources):
    """Check provenance handoff, not the truth or literary quality of explanations."""
    allowed = {s['id'] for s in sources}

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    def grounded(item):
        if not isinstance(item, dict) or not text(item.get('text')):
            return False
        ids = item.get('source_ids')
        return isinstance(ids, list) and bool(ids) and all(isinstance(s, str) and s in allowed for s in ids)

    if not isinstance(plan, dict):
        raise ValueError('研读缺少机制讲解提纲')
    questions, explanations = plan.get('reader_questions'), plan.get('explanations')
    if not isinstance(questions, list) or not 1 <= len(questions) <= 8 or not all(text(q) for q in questions):
        raise ValueError('研读缺少明确的读者问题')
    if not isinstance(explanations, list) or not 1 <= len(explanations) <= 12:
        raise ValueError('研读缺少机制讲解')
    for explanation in explanations:
        if not isinstance(explanation, dict) or not text(explanation.get('question')):
            raise ValueError('机制讲解缺少问题')
        steps = explanation.get('steps')
        if not isinstance(steps, list) or not 2 <= len(steps) <= 12 or not all(grounded(s) for s in steps):
            raise ValueError('机制步骤未关联已核实的原文')
        example = explanation.get('example')
        if example is not None and (not grounded(example) or example.get('kind') not in ('illustrative', 'reported')):
            raise ValueError('示例须说明是论文记载还是假设情境，并关联机制原文')


def verify_article(data, sources):
    text = data.get('markdown')
    if not isinstance(text, str) or not 600 <= len(text) <= 60000:
        raise ValueError('文章正文不完整或超出篇幅限制')
    # Include titled, reference-style and angle-wrapped Markdown destinations.
    # Reject unknown IDs even if a renderer accepts a syntax we do not emit.
    ids = re.findall(r'''#source-([^\s)"'<>\\]+)''', text)
    allowed = {s['id'] for s in sources}
    if not ids or set(ids) - allowed:
        raise ValueError('文章引用了未核实的来源')
    if any(not isinstance(data.get(key), str) or not data[key].strip() for key in ('title', 'dek', 'changes')):
        raise ValueError('文章缺少标题、导语或更新说明')
    return list(dict.fromkeys(ids))
