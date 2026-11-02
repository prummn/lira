"""Follow actual unresolved reading intents, without replaying a topic synthesis."""
import hashlib
import json
import re
import uuid

from sqlalchemy import select

from ..models import ChatConversation, ChatTurn, Collection, CollectionPaper, Note, Paper, ResearchScope, ResearchTask, ResearchFinding, ResearchFindingRevision
from .research_agenda import investigation_material, source_fingerprint, sources_match, target_active
from .research_materials import dumps


def normalized(text):
    return re.sub(r'\s+', '', text.casefold())


def signature(origin):
    return hashlib.sha256(dumps({k: origin.get(k) for k in
        ('kind', 'id', 'paper_id', 'question', 'page', 'chunk_id', 'selected_text')}).encode()).hexdigest()


def note_origin(note):
    return dict(kind='note', id=note.id, paper_id=note.paper_id, question=note.content.strip(),
                page=note.page, chunk_id=None, selected_text=note.source_text)


def chat_origin(turn, conversation):
    context = json.loads(conversation.context_json)
    return dict(kind='chat', id=turn.id, paper_id=conversation.paper_id,
                conversation_id=conversation.id, question=turn.question.strip(), page=context.get('page'),
                chunk_id=context.get('chunk_id'), selected_text=context.get('selected_text'))


def intents(db, paper_ids):
    candidates = []
    for note in db.scalars(select(Note).where(Note.paper_id.in_(paper_ids), Note.kind == 'question')
                           .order_by(Note.updated_at.desc(), Note.id)):
        if note.content.strip():
            candidates.append(note_origin(note))
    rows = db.execute(select(ChatTurn, ChatConversation).join(ChatConversation).where(
        ChatConversation.paper_id.in_(paper_ids), ChatConversation.kind.in_(['paper', 'explanation']),
        ChatTurn.status.in_(['failed', 'interrupted'])).order_by(ChatTurn.created_at.desc(), ChatTurn.id))
    for turn, conversation in rows:
        candidates.append(chat_origin(turn, conversation))
    return candidates


def intent_active(db, collection_id, material):
    origin = material['origin']
    if not db.get(CollectionPaper, (collection_id, origin['paper_id'])):
        return False
    current = None
    if origin['kind'] == 'note':
        note = db.get(Note, origin['id'])
        if note and note.kind == 'question':
            current = note_origin(note)
    else:
        turn = db.get(ChatTurn, origin['id'])
        conversation = db.get(ChatConversation, turn.conversation_id) if turn else None
        if turn and turn.status in ('failed', 'interrupted') and conversation:
            current = chat_origin(turn, conversation)
    if not current or signature(current) != signature(origin):
        return False
    if origin['kind'] == 'chat':
        turn = db.get(ChatTurn, origin['id'])
        others = db.execute(select(ChatTurn, ChatConversation).join(ChatConversation).where(
            ChatConversation.paper_id == origin['paper_id'], ChatTurn.status.in_(['completed', 'running']),
            ChatTurn.created_at >= turn.created_at))
        for other, conversation in others:
            context = json.loads(conversation.context_json)
            same_context = (conversation.id == turn.conversation_id or not origin.get('selected_text') or
                            normalized(context.get('selected_text') or '') == normalized(origin['selected_text']))
            if same_context and normalized(other.question) == normalized(turn.question):
                return False
    return True


def current_material(db, scope, material):
    return ('reading' in json.loads(scope.work_types_json) and scope.focus == material['_reading_focus']
            and intent_active(db, scope.collection_id, material)
            and material['_source_fingerprint'] == source_fingerprint(db, [material['origin']['paper_id']])
            and sources_match(db, material) and target_active(db, scope.collection_id, material['investigation']))


def answer_reference(db, collection_id, material, data):
    """Link an existing explanation without changing its identity or text."""
    row = db.get(ResearchFinding, data.get('answered_by')) if isinstance(data.get('answered_by'), str) else None
    if (not row or row.collection_id != collection_id or row.kind != 'reading' or row.status in ('done', 'dismissed')
            or not isinstance(data.get('reason'), str) or not 8 <= len(data['reason']) <= 1000):
        raise ValueError('已有答案引用无效，请回答当前阅读问题')
    sources = json.loads(row.sources_json)
    if not sources or material['origin']['paper_id'] not in {s['paper_id'] for s in sources}:
        raise ValueError('已有答案未覆盖当前论文')
    if not sources_match(db, {'sources': sources}):
        raise ValueError('已有答案依据已经变化，请重新研读')
    return row.id


def enqueue_reading(db, scope):
    if not scope.enabled or 'reading' not in json.loads(scope.work_types_json):
        return []
    paper_ids = list(db.scalars(select(CollectionPaper.paper_id).where(CollectionPaper.collection_id == scope.collection_id)))
    # When a paper belongs to several opted-in collections, use one stable home.
    homes = {}
    for paper_id, collection_id, types in db.execute(select(CollectionPaper.paper_id, ResearchScope.collection_id,
            ResearchScope.work_types_json).join(ResearchScope, ResearchScope.collection_id == CollectionPaper.collection_id)
            .where(CollectionPaper.paper_id.in_(paper_ids), ResearchScope.enabled == True)
            .order_by(ResearchScope.collection_id)):
        if 'reading' in json.loads(types):
            homes.setdefault(paper_id, collection_id)
    result, seen, digests = [], set(), {}
    active_count = len(list(db.scalars(select(ResearchTask.id).where(ResearchTask.collection_id == scope.collection_id,
        ResearchTask.intent_key.is_not(None), ResearchTask.status.in_(['queued', 'running', 'paused'])))))
    for origin in intents(db, paper_ids):
        if homes.get(origin['paper_id']) != scope.collection_id or not intent_active(db, scope.collection_id, {'origin': origin}):
            continue
        intent_key = hashlib.sha256(dumps(['reading-v1', origin['paper_id'], normalized(origin['question']),
            origin.get('selected_text'), origin.get('page'), origin.get('chunk_id')]).encode()).hexdigest()
        if intent_key in seen:
            continue
        seen.add(intent_key)
        if origin['paper_id'] not in digests:
            digests[origin['paper_id']] = source_fingerprint(db, [origin['paper_id']])
        full = digests[origin['paper_id']]
        key = hashlib.sha256(dumps([intent_key, full, scope.focus]).encode()).hexdigest()
        previous_intents = list(db.scalars(select(ResearchTask).where(ResearchTask.intent_key == intent_key)
                                          .order_by(ResearchTask.created_at.desc())))
        stable, target_id = None, None
        for prior in previous_intents:
            stored = json.loads(prior.material_json)
            outcome = db.scalar(select(ResearchFinding).join(ResearchFindingRevision).where(
                ResearchFindingRevision.task_id == prior.id).limit(1))
            if outcome is None:
                reused_id = json.loads(prior.checkpoint_json).get('reused_answer')
                reused = db.get(ResearchFinding, reused_id) if isinstance(reused_id, str) else None
                if reused and reused.collection_id == prior.collection_id and reused.kind == 'reading':
                    outcome = reused
            if outcome and outcome.status in ('dismissed', 'done'):
                stable = prior
                break
            if outcome and prior.collection_id == scope.collection_id:
                target_id = target_id or outcome.id
            if prior.status == 'cancelled' or prior.status == 'completed' and stored['_source_fingerprint'] == full:
                stable = prior
                break
            if prior.status in ('queued', 'paused', 'running'):
                owner = db.get(ResearchScope, prior.collection_id)
                if owner and owner.enabled and current_material(db, owner, stored):
                    stable = prior
                    break
                prior.status = 'superseded'
        if stable:
            result.append(stable)
            continue
        previous = db.scalar(select(ResearchTask).where(ResearchTask.collection_id == scope.collection_id,
                                                       ResearchTask.fingerprint == key))
        if previous:
            if previous.status == 'superseded':
                if active_count >= 6:
                    continue
                previous.status, previous.stage, previous.error, previous.attempts = 'queued', 'discover', None, 0
                previous.checkpoint_json = '{}'
                previous.material_json = dumps({**json.loads(previous.material_json), 'origin': origin})
                active_count += 1
            result.append(previous)
            continue
        if active_count >= 6:
            continue
        paper = db.get(Paper, origin['paper_id'])
        brief = dict(kind='reading', title=origin['question'][:180], question=origin['question'],
            rationale='接着阅读中留下的问题，回到相关原文查清。', paper_ids=[paper.id], section_hints=[], existing_id=target_id)
        material = investigation_material(db, scope.collection_id, key, brief, dict(
            collection=db.get(Collection, scope.collection_id).name, focus=scope.focus, origin=origin,
            papers=[dict(id=paper.id, title=paper.title, abstract=paper.abstract)], sources=[], coverage=[]))
        if not material['sources']:
            continue
        material.update(_reading_focus=scope.focus, _source_fingerprint=full, _intent_key=intent_key)
        task = ResearchTask(id='research-'+uuid.uuid4().hex, collection_id=scope.collection_id,
            kind='investigation', stage='discover', fingerprint=key, intent_key=intent_key, material_json=dumps(material))
        db.add(task)
        db.flush()
        result.append(task)
        active_count += 1
    return result
