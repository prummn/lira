"""Read-only librarian: explicit local scope, no agent write tools."""
from fastapi import APIRouter, Request

from ..library_schemas import LibraryAnswer, LibraryQuestion
from ..providers import get_model_provider
from ..services.librarian import answer_library

router = APIRouter()


@router.post('/intelligence/ask', response_model=LibraryAnswer)
def ask_library(payload: LibraryQuestion, request: Request) -> LibraryAnswer:
    return answer_library(request.app.state.database, get_model_provider(), payload)
