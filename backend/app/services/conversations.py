"""Save question intent before model work; keep answers independent of model caches."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ..models import ChatConversation, ChatTurn, Paper
from ..providers.base import ProviderError


def normalize_context(kind, context):
    if len(json.dumps(context, ensure_ascii=False)) > 20000:
        raise HTTPException(422, '对话上下文过长')
    if kind == 'paper':
        return {}
    if kind == 'librarian':
        collection_id, paper_ids = context.get('collection_id'), context.get('paper_ids')
        if collection_id is not None and (not isinstance(collection_id, str) or len(collection_id) > 64):
            raise HTTPException(422, '集合编号格式无效')
        if paper_ids is not None and (not isinstance(paper_ids, list) or len(paper_ids) > 50
                or any(not isinstance(item, str) or not item or len(item) > 64 for item in paper_ids)):
            raise HTTPException(422, '论文范围格式无效')
        result = {'collection_id': collection_id} if collection_id else {}
        if paper_ids is not None:
            result['paper_ids'] = sorted(set(paper_ids))
        return result
    bbox = context.get('bbox')
    if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4
            or any(not isinstance(item, (int, float)) or isinstance(item, bool) for item in bbox)):
        raise HTTPException(422, '图表区域范围格式无效')
    if (context.get('page') is not None and (type(context['page']) is not int or context['page'] < 1)
            or context.get('chunk_id') is not None and not isinstance(context['chunk_id'], str)
            or context.get('selected_text') is not None and not isinstance(context['selected_text'], str)
            or context.get('translated_text') is not None and not isinstance(context['translated_text'], str)
            or context.get('visual') is not None and not isinstance(context['visual'], bool)
            or context.get('visual_kind') is not None and context['visual_kind'] not in {'figure', 'table'}
            or context.get('visual_label') is not None and (not isinstance(context['visual_label'], str) or len(context['visual_label']) > 100)):
        raise HTTPException(422, '选段上下文格式无效')
    result = {'page': context.get('page'), 'chunk_id': context.get('chunk_id'),
        'selected_text': re.sub(r'\s+', ' ', context.get('selected_text') or '').strip(),
        'visual': bool(context.get('visual'))}
    if context.get('visual') and isinstance(bbox, list):
        result['bbox'] = [float(item) for item in bbox]
    if context.get('visual') and context.get('visual_kind') in {'figure', 'table'}:
        result['visual_kind'] = context['visual_kind']
    if context.get('visual') and context.get('visual_label'):
        result['visual_label'] = context['visual_label'].strip()
    if context.get('translated_text'):
        result['translated_text'] = context['translated_text'].strip()
    return result


def context_key(kind, context):
    normalized = normalize_context(kind, context)
    # A translated excerpt is display context; the English evidence remains
    # the conversation identity, including for archives created before this field.
    normalized.pop('translated_text', None)
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def create_conversation(database, kind, paper_id, context):
    context = normalize_context(kind, context)
    with database.sessions() as session:
        if kind in {'paper', 'explanation'} and not paper_id:
            raise HTTPException(422, '论文对话需要指定论文')
        if paper_id and session.get(Paper, paper_id) is None:
            raise HTTPException(404, '论文不存在')
        conversation = ChatConversation(id='chat-' + uuid.uuid4().hex, kind=kind, paper_id=paper_id,
            context_json=json.dumps(context, ensure_ascii=False), context_key=context_key(kind, context))
        session.add(conversation)
        session.commit()
        return summary(conversation, 0)


def summary(conversation, count, latest=None):
    return {'id': conversation.id, 'kind': conversation.kind, 'paper_id': conversation.paper_id,
        'context': json.loads(conversation.context_json), 'title': conversation.title,
        'created_at': conversation.created_at.isoformat() + ('Z' if conversation.created_at.tzinfo is None else ''),
        'updated_at': conversation.updated_at.isoformat() + ('Z' if conversation.updated_at.tzinfo is None else ''), 'turn_count': count,
        'latest_status': latest['status'] if latest else None,
        'latest_question': latest['question'] if latest else '',
        'latest_turn_id': latest['id'] if latest else None}


def read_conversation(database, conversation_id):
    with database.sessions() as session:
        conversation = session.get(ChatConversation, conversation_id)
        if conversation is None:
            raise HTTPException(404, '对话不存在')
        turns = list(session.scalars(select(ChatTurn).where(ChatTurn.conversation_id == conversation_id)
            .order_by(ChatTurn.created_at, ChatTurn.id)))
        latest = {key: getattr(turns[-1], key) for key in ('id', 'status', 'question')} if turns else None
        return {**summary(conversation, len(turns), latest), 'turns': [
            {'id': turn.id, 'question': turn.question, 'status': turn.status,
             'response': json.loads(turn.response_json) if turn.response_json else None, 'error': turn.error,
             'created_at': turn.created_at.isoformat() + ('Z' if turn.created_at.tzinfo is None else '')}
            for turn in turns]}


def list_conversations(database, kind=None, paper_id=None, context=None, offset=0, limit=50):
    with database.sessions() as session:
        statement = select(ChatConversation, func.count(ChatTurn.id)).outerjoin(ChatTurn,
            ChatTurn.conversation_id == ChatConversation.id)
        if kind:
            statement = statement.where(ChatConversation.kind == kind)
        if paper_id:
            statement = statement.where(ChatConversation.paper_id == paper_id)
        if context is not None and kind:
            statement = statement.where(ChatConversation.context_key == context_key(kind, context))
        rows = session.execute(statement.group_by(ChatConversation.id).order_by(
            ChatConversation.updated_at.desc(), ChatConversation.id).offset(offset).limit(limit + 1)).all()
        ids = [conversation.id for conversation, _ in rows[:limit]]
        latest = {}
        if ids:
            ranked = select(ChatTurn.conversation_id, ChatTurn.id, ChatTurn.status, ChatTurn.question,
                func.row_number().over(partition_by=ChatTurn.conversation_id,
                    order_by=(ChatTurn.created_at.desc(), ChatTurn.id.desc())).label('position')
                ).where(ChatTurn.conversation_id.in_(ids)).subquery()
            latest = {row['conversation_id']: row for row in session.execute(
                select(ranked).where(ranked.c.position == 1)).mappings()}
        return {'items': [summary(conversation, count, latest.get(conversation.id))
            for conversation, count in rows[:limit]], 'has_more': len(rows) > limit}


def recover_interrupted(database):
    with database.sessions() as session:
        session.execute(update(ChatTurn).where(ChatTurn.status == 'running').values(
            status='interrupted', error='服务已重新启动，本次回答未完成。可以重新提问。'))
        session.commit()


def run_question(database, kind, paper_id, context, question, conversation_id, request_id, response_type, generate):
    key = context_key(kind, context)
    request_id = request_id or uuid.uuid4().hex
    with database.sessions() as session:
        previous = session.scalar(select(ChatTurn).where(ChatTurn.request_id == request_id))
        if previous:
            conversation = session.get(ChatConversation, previous.conversation_id)
            if (conversation.kind != kind or conversation.paper_id != paper_id or conversation.context_key != key
                    or previous.question != question or (conversation_id and previous.conversation_id != conversation_id)):
                raise HTTPException(409, '该请求编号已用于另一条问题')
            if previous.status == 'completed':
                return response_type.model_validate(json.loads(previous.response_json))
            raise HTTPException(409, '该问题正在处理或已经结束，请查看历史记录；重新提问会创建新的请求')
    if not conversation_id:
        conversation_id = create_conversation(database, kind, paper_id, context)['id']
    with database.sessions() as session:
        conversation = session.get(ChatConversation, conversation_id)
        if conversation is None:
            raise HTTPException(404, '对话不存在')
        if conversation.kind != kind or conversation.paper_id != paper_id or conversation.context_key != key:
            raise HTTPException(409, '对话与当前论文或检索范围不一致，请新建对话')
        turn = ChatTurn(id='turn-' + uuid.uuid4().hex, conversation_id=conversation_id, request_id=request_id, question=question)
        session.add(turn)
        if not conversation.title:
            conversation.title = question[:200]
        conversation.updated_at = datetime.now(timezone.utc)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, '这条问题或本对话已有请求正在处理，请查看历史记录')
        turn_id = turn.id
    try:
        response = generate().model_copy(update={'conversation_id': conversation_id, 'turn_id': turn_id})
        with database.sessions() as session:
            turn = session.get(ChatTurn, turn_id)
            if turn is not None:
                turn.status = 'completed'
                turn.response_json = response.model_dump_json()
                conversation = session.get(ChatConversation, conversation_id)
                conversation.updated_at = datetime.now(timezone.utc)
                session.commit()
        return response
    except Exception as error:
        with database.sessions() as session:
            turn = session.get(ChatTurn, turn_id)
            if turn is not None:
                turn.status = 'failed'
                turn.error = str(error) if isinstance(error, ProviderError) else str(error.detail) if isinstance(error, HTTPException) else '本次回答未完成，请重试。'
                session.get(ChatConversation, conversation_id).updated_at = datetime.now(timezone.utc)
                session.commit()
        raise
