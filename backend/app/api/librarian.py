"""Read-only librarian: explicit local scope, no agent write tools."""
from fastapi import APIRouter, Request

from ..library_schemas import LibraryAnswer, LibraryQuestion
from ..providers import get_model_provider
from ..services.librarian import answer_library
from ..services.conversations import run_question
from fastapi import HTTPException

router = APIRouter()


@router.post('/intelligence/ask', response_model=LibraryAnswer)
def ask_library(payload: LibraryQuestion, request: Request) -> LibraryAnswer:
    paper_id = None
    context = {'collection_id': payload.collection_id, 'paper_ids': payload.paper_ids}
    if payload.conversation_kind == 'paper':
        if not payload.paper_ids or len(payload.paper_ids) != 1 or payload.collection_id:
            raise HTTPException(422, '论文对话需要且只能指定一篇论文')
        paper_id = payload.paper_ids[0]
        context = {}
    return run_question(request.app.state.database, payload.conversation_kind, paper_id, context,
        payload.question, payload.conversation_id, payload.request_id, LibraryAnswer,
        lambda: answer_library(request.app.state.database, get_model_provider(), payload))
