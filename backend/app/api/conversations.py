"""Read local chat archives without making model requests."""
import json
from fastapi import APIRouter, HTTPException, Query, Request
from ..conversation_schemas import ChatKind, ConversationCreate
from ..services.conversations import create_conversation, list_conversations, read_conversation

router = APIRouter(prefix='/conversations')


@router.post('', status_code=201)
def create(payload: ConversationCreate, request: Request):
    return create_conversation(request.app.state.database, payload.kind, payload.paper_id, payload.context)


@router.get('')
def list_saved(request: Request, kind: ChatKind | None = None, paper_id: str | None = None,
               context: str | None = Query(None, max_length=20000), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    try:
        parsed = json.loads(context) if context is not None else None
        if parsed is not None and not isinstance(parsed, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, '对话上下文格式无效')
    return list_conversations(request.app.state.database, kind, paper_id, parsed, offset, limit)


@router.get('/{conversation_id}')
def read(conversation_id: str, request: Request):
    return read_conversation(request.app.state.database, conversation_id)
