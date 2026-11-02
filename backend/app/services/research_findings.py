"""Evidence-backed findings, immutable content history and local review scheduling."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from ..models import ResearchFinding, ResearchFindingRevision
from ..providers.validation import canonical_quote
from .research_materials import dumps

KINDS = {'connection': 'connections', 'gap': 'gaps', 'review': 'review', 'question': 'questions', 'reading': 'reading'}


def stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def finding_read(row):
    return {**{k: getattr(row, k) for k in ('id', 'collection_id', 'kind', 'title', 'body', 'next_step',
             'status', 'review_count', 'model')}, 'sources': json.loads(row.sources_json),
            'due_at': stamp(row.due_at), 'created_at': stamp(row.created_at), 'updated_at': stamp(row.updated_at)}


def list_findings(db, collection_id):
    rows = db.scalars(select(ResearchFinding).where(ResearchFinding.collection_id == collection_id)
                      .order_by(ResearchFinding.created_at.desc(), ResearchFinding.id)).all()
    return [finding_read(row) for row in rows]


def identity(kind, title, sources):
    normalized = re.sub(r'\s+', '', title.casefold())
    papers = sorted({s['paper_id'] for s in sources})
    return hashlib.sha256(dumps([kind, normalized, papers]).encode()).hexdigest()


def content_identity(item, sources):
    """Catch renamed copies without merging different questions on one passage."""
    def normalize(text):
        text = re.sub(r'\[[^\]]*\]\(\s*<?#source-[^)]*\)', '', text)
        return re.sub(r'\s+', '', text.casefold())
    anchors = sorted({(s['paper_id'], s['chunk_id']) for s in sources})
    return (item['kind'], normalize(item['body']), normalize(item['next_step']), tuple(anchors))


def verify_findings(data, material, existing):
    items = data.get('findings') if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) > 12:
        raise ValueError('研究线索须为至多12条的列表')
    available = {s['id']: s for s in material['sources']}
    previous = {s['id']: s for s in existing}
    content_matches = {}
    title_matches = {}
    for item in existing:
        content_matches.setdefault(content_identity(item, item['sources']), []).append(item)
        title_matches.setdefault(identity(item['kind'], item['title'], item['sources']), []).append(item)
    result, seen, seen_content, reused = [], set(), set(), set()
    for item in items:
        if not isinstance(item, dict) or KINDS.get(item.get('kind')) not in material['work_types']:
            raise ValueError('研究线索类型不在当前专题的选择范围')
        for key, limit in [('title', 300), ('body', 12000), ('next_step', 2000)]:
            if not isinstance(item.get(key), str) or not 1 <= len(item[key].strip()) <= limit:
                raise ValueError('研究线索缺少明确问题、解释或下一步')
        evidence = item.get('evidence')
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
            raise ValueError('研究线索缺少原文依据')
        sources = {}
        for evidence_item in evidence:
            source = available.get(evidence_item.get('source_id')) if isinstance(evidence_item, dict) else None
            quote = evidence_item.get('quote') if isinstance(evidence_item, dict) else None
            matched = (canonical_quote(source['text'], quote, allow_pdf_formatting=True)
                       if source and isinstance(quote, str) else None)
            if matched is None or len(matched.strip()) < 18:
                source_id = str(evidence_item.get('source_id', '?'))[:40] if isinstance(evidence_item, dict) else '?'
                raise ValueError(f'研究线索的引文未匹配原文（{source_id}）；请从该来源逐字摘取连续原文')
            sources[source['id']] = {**source, 'quote': matched, 'claim': item['title']}
        if item['kind'] == 'connection' and len({s['paper_id'] for s in sources.values()}) < 2:
            raise ValueError('跨论文联系需要至少两篇论文的原文依据')
        ids = re.findall(r'''#source-([^\s)"'<>\\]+)''', item['body'] + '\n' + item['next_step'])
        if set(ids) - sources.keys():
            raise ValueError('线索正文引用了未核实的出处')
        existing_id = item.get('existing_id')
        key = identity(item['kind'], item['title'], sources.values())
        reading_intent = item['kind'] == 'reading' and material.get('_intent_key')
        if reading_intent:
            key = hashlib.sha256(dumps(['reading-intent', material['_intent_key']]).encode()).hexdigest()
        content_key = content_identity(item, sources.values())
        if content_key in seen_content:
            raise ValueError('同一批研究结果包含重复解释')
        seen_content.add(content_key)
        matches = [] if reading_intent else title_matches.get(key) or content_matches.get(content_key, [])
        if not existing_id and len(matches) == 1:
            existing_id = matches[0]['id']
        if existing_id:
            prior = previous.get(existing_id)
            if not prior or prior['kind'] != item['kind'] or existing_id in reused:
                raise ValueError('只能更新本专题同一类型的已有线索')
            reused.add(existing_id)
        if key in seen:
            raise ValueError('同一批研究结果包含重复线索')
        seen.add(key)
        result.append({**{k: item[k].strip() for k in ('title', 'body', 'next_step')},
                       'kind': item['kind'], 'identity': key, 'existing_id': existing_id,
                       'sources': list(sources.values())})
    return result


def publish_findings(db, task, items, model):
    for item in items:
        row = db.get(ResearchFinding, item['existing_id']) if item.get('existing_id') else None
        if row is None:
            row = db.scalar(select(ResearchFinding).where(ResearchFinding.collection_id == task.collection_id,
                ResearchFinding.identity == item['identity']))
        if row is not None and (row.collection_id != task.collection_id or row.kind != item['kind']):
            raise ValueError('研究线索不属于当前专题')
        collision = db.scalar(select(ResearchFinding).where(ResearchFinding.collection_id == task.collection_id,
            ResearchFinding.identity == item['identity']))
        if row is not None and collision is not None and collision.id != row.id:
            raise ValueError('更新目标与已有线索重复，请沿用同一个条目')
        content = {**{k: item[k] for k in ('kind', 'title', 'body', 'next_step', 'sources')}, 'model': model}
        content_hash = hashlib.sha256(dumps(content).encode()).hexdigest()
        if row is None:
            row = ResearchFinding(id='finding-' + uuid.uuid4().hex, collection_id=task.collection_id,
                identity=item['identity'], kind=item['kind'], title=item['title'], body=item['body'],
                next_step=item['next_step'], sources_json=dumps(item['sources']), model=model,
                due_at=datetime.now(timezone.utc) if item['kind'] == 'review' else None)
            db.add(row)
            db.flush()
        latest = db.scalar(select(ResearchFindingRevision).where(ResearchFindingRevision.finding_id == row.id)
                           .order_by(ResearchFindingRevision.created_at.desc(), ResearchFindingRevision.id.desc()).limit(1))
        if latest and latest.content_hash == content_hash:
            continue
        row.title, row.body, row.next_step, row.sources_json, row.model = (
            item['title'], item['body'], item['next_step'], dumps(item['sources']), model)
        row.identity = item['identity']
        db.add(ResearchFindingRevision(id='finding-rev-' + uuid.uuid4().hex, finding_id=row.id,
            task_id=task.id, content_hash=content_hash, content_json=dumps(content)))
        db.flush()


def act(db, finding_id, action):
    row = db.get(ResearchFinding, finding_id)
    if row is None:
        raise HTTPException(404, '研究线索不存在')
    states = {'keep': 'kept', 'dismiss': 'dismissed', 'restore': 'unread', 'done': 'done'}
    if action in states:
        row.status = states[action]
    elif action in ('again', 'remembered'):
        if row.kind != 'review':
            raise HTTPException(409, '只有复习题可以安排下次复习')
        row.status = 'kept'
        if action == 'again':
            row.review_count, row.due_at = 0, datetime.now(timezone.utc) + timedelta(minutes=10)
        else:
            row.review_count += 1
            intervals = (1, 3, 7, 14, 30, 60)
            row.due_at = datetime.now(timezone.utc) + timedelta(days=intervals[min(row.review_count-1, len(intervals)-1)])
    else:
        raise HTTPException(422, '未知线索操作')
    db.commit()
    return finding_read(row)


def history(db, finding_id):
    if db.get(ResearchFinding, finding_id) is None:
        raise HTTPException(404, '研究线索不存在')
    rows = db.scalars(select(ResearchFindingRevision).where(ResearchFindingRevision.finding_id == finding_id)
        .order_by(ResearchFindingRevision.created_at.desc(), ResearchFindingRevision.id.desc())).all()
    return {'revisions': [{**json.loads(r.content_json), 'id': r.id, 'created_at': stamp(r.created_at)} for r in rows]}
