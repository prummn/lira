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
from sqlalchemy import delete, func, or_, select
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
    CollectionPapersAdd,
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


@router.delete('/collections/{collection_id}', status_code=204)
def delete_collection(
    collection_id: str, request: Request, session: Session = Depends(get_db)
) -> Response:
    # 与研究检查点共用锁；只通过外键级联删除集合子记录，不触碰论文和文件。
    with request.app.state.research_worker._mutation:
        require_collection(session, collection_id)
        deleted = session.scalars(
            delete(Collection).where(Collection.id == collection_id).returning(Collection.id)
        ).all()
        if len(deleted) != 1:
            raise HTTPException(409, '集合在删除期间发生变化')
        session.commit()
    return Response(status_code=204)


@router.post('/collections/{collection_id}/papers', response_model=CollectionRead)
def add_papers(
    collection_id: str, payload: CollectionPapersAdd, session: Session = Depends(get_db)
) -> CollectionRead:
    collection = require_collection(session, collection_id)
    paper_ids = set(payload.paper_ids)
    found = set(session.scalars(select(Paper.id).where(Paper.id.in_(paper_ids))).all())
    if found != paper_ids:
        raise HTTPException(404, '部分论文已不存在，请刷新文献库后重试')
    existing = set(session.scalars(
        select(CollectionPaper.paper_id).where(CollectionPaper.collection_id == collection_id)
    ).all())
    session.add_all(CollectionPaper(collection_id=collection_id, paper_id=paper_id)
                    for paper_id in paper_ids - existing)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        # Concurrent repeat submissions may have already inserted the full batch.
        stored = set(session.scalars(select(CollectionPaper.paper_id).where(
            CollectionPaper.collection_id == collection_id,
            CollectionPaper.paper_id.in_(paper_ids),
        )).all())
        if stored != paper_ids:
            raise HTTPException(409, '集合内容刚刚发生变化，请重试') from None
    session.expire(collection, ['paper_links'])
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
