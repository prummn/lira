"""Focused HTTP endpoints for the local research workspace."""

from __future__ import annotations
import json
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from ..db import get_db
from ..models import Author, Collection, CollectionPaper, Edge, Note, Paper, PaperAuthor
from ..providers import get_model_provider
from ..schemas import (
    AskRequest,
    AskResponse,
    CollectionCreate,
    CollectionListResponse,
    CollectionRead,
    NoteCreate,
    NoteRead,
    PaperCreate,
    PaperDetail,
    PaperListResponse,
    PaperSummary,
    PaperUpdate,
    TranslateRequest,
)
from ..services.analysis import analyze_paper, evidence_for
from ..services.importing import MAX_PDF_BYTES, import_pdf_bytes
from ..services.search import search_chunks
from ..services.serialization import (
    collection_read,
    evidence_read,
    find_paper,
    load_options,
    note_read,
    paper_detail,
    paper_summary,
)

from .dependencies import require_paper, require_collection

router = APIRouter()


@router.get("/collections", response_model=CollectionListResponse)
def list_collections(session: Session = Depends(get_db)) -> CollectionListResponse:
    collections = session.scalars(
        select(Collection)
        .options(selectinload(Collection.paper_links))
        .order_by(Collection.created_at, Collection.id)
    ).all()
    return CollectionListResponse(
        items=[collection_read(c) for c in collections], total=len(collections)
    )


@router.get("/collections/{collection_id}", response_model=CollectionRead)
def get_collection(
    collection_id: str, session: Session = Depends(get_db)
) -> CollectionRead:
    return collection_read(require_collection(session, collection_id))


@router.post("/collections", response_model=CollectionRead, status_code=201)
def create_collection(
    payload: CollectionCreate, session: Session = Depends(get_db)
) -> CollectionRead:
    collection = Collection(
        id="collection-" + uuid.uuid4().hex[:16],
        name=payload.name,
        description=payload.description,
        color=payload.color,
    )
    session.add(collection)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "同名集合已存在") from error
    return collection_read(collection)


@router.put(
    "/collections/{collection_id}/papers/{paper_id}", response_model=CollectionRead
)
def add_membership(
    collection_id: str, paper_id: str, session: Session = Depends(get_db)
) -> CollectionRead:
    collection = require_collection(session, collection_id)
    require_paper(session, paper_id)
    if session.get(CollectionPaper, (collection_id, paper_id)) is None:
        session.add(CollectionPaper(collection_id=collection_id, paper_id=paper_id))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if session.get(CollectionPaper, (collection_id, paper_id)) is None:
                raise
    session.expire(collection, ["paper_links"])
    return collection_read(collection)


@router.delete("/collections/{collection_id}/papers/{paper_id}", status_code=204)
def remove_membership(
    collection_id: str, paper_id: str, session: Session = Depends(get_db)
) -> Response:
    require_collection(session, collection_id)
    require_paper(session, paper_id)
    link = session.get(CollectionPaper, (collection_id, paper_id))
    if link is not None:
        session.delete(link)
        session.commit()
    return Response(status_code=204)
