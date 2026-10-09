"""Focused HTTP endpoints for the local research workspace."""

from __future__ import annotations
import json
import os
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
from ..providers import OpenAICompatibleProvider, get_model_provider
from ..providers.config import MODEL_ENV_KEYS, clear_model_config, persist_model_config
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
    ModelSettingsUpdate,
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
from ..schemas import ReadingStatus

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "research-intelligence-api"}


def _settings_payload() -> dict[str, object]:
    provider = get_model_provider()
    return {
        "provider": provider.name,
        "mode": provider.mode,
        "configured": provider.configured,
        "translation_available": provider.translation_available,
        "metadata_connected": True,
        "metadata_providers": ["arxiv", "crossref"],
        "embeddings_connected": False,
        "model": getattr(provider,'model',None),
        "base_url": getattr(provider,'base_url',None),
        "wire_api": getattr(provider,'wire_api',None),
        "reasoning_effort": getattr(provider,'reasoning_effort',None),
        "api_key_configured": bool(os.getenv('PAPER_READER_MODEL_API_KEY','').strip()),
        "configuration_error": getattr(provider,'configuration_error',None),
    }


@router.get("/settings")
def settings() -> dict[str, object]:
    return _settings_payload()


@router.put('/settings/model')
def update_model_settings(payload: ModelSettingsUpdate, request: Request) -> dict[str, object]:
    current_key = os.getenv('PAPER_READER_MODEL_API_KEY', '').strip()
    api_key = payload.api_key.strip() if payload.api_key is not None and payload.api_key.strip() else current_key
    if not api_key:
        raise HTTPException(422, '请输入模型 API key')
    try:
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=payload.base_url.strip(),
            model=payload.model.strip(),
            wire_api=payload.wire_api,
            reasoning_effort=payload.reasoning_effort,
            timeout=payload.timeout,
            completion_parameter=os.getenv('PAPER_READER_MODEL_COMPLETION_PARAMETER', 'max_completion_tokens'),
            json_mode=os.getenv('PAPER_READER_MODEL_JSON_MODE', 'json_object'),
        )
        if payload.test_connection:
            provider.test_connection()
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except Exception as error:
        from ..providers.base import ProviderError
        if isinstance(error, ProviderError):
            raise
        raise HTTPException(502, '模型连接测试失败，请检查地址、模型名、协议和 API key') from None
    values = {
        'PAPER_READER_MODEL_BASE_URL': payload.base_url.strip(),
        'PAPER_READER_MODEL_NAME': payload.model.strip(),
        'PAPER_READER_MODEL_API_KEY': api_key,
        'PAPER_READER_MODEL_WIRE_API': payload.wire_api,
        'PAPER_READER_MODEL_REASONING_EFFORT': payload.reasoning_effort,
        'PAPER_READER_MODEL_TIMEOUT': str(payload.timeout).rstrip('0').rstrip('.') if '.' in str(payload.timeout) else str(payload.timeout),
    }
    try:
        persist_model_config(request.app.state.model_config_path, values)
    except OSError:
        raise HTTPException(500, '模型连接已通过，但本机配置文件无法保存') from None
    os.environ.update(values)
    return _settings_payload()


@router.delete('/settings/model')
def reset_model_settings(request: Request) -> dict[str, object]:
    for key in MODEL_ENV_KEYS:
        os.environ.pop(key, None)
    try:
        clear_model_config(request.app.state.model_config_path)
    except OSError:
        raise HTTPException(500, '模型配置已从当前进程移除，但本机配置文件无法更新') from None
    return _settings_payload()


@router.get("/stats")
def stats(session: Session = Depends(get_db)) -> dict[str, int]:
    return {
        "papers": session.scalar(select(func.count(Paper.id))) or 0,
        "collections": session.scalar(select(func.count(Collection.id))) or 0,
    }


@router.get("/search")
def search(
    query: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(50, ge=1, le=200),
    collection_id: str | None = None,
    reading_status: ReadingStatus | None = None,
    is_favorite: bool | None = None,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    if not query.strip():
        raise HTTPException(422, "搜索内容不能为空")
    if collection_id:
        require_collection(session,collection_id)
    items = search_chunks(session, query.strip(), limit, collection_id=collection_id, reading_status=reading_status, is_favorite=is_favorite)
    return {"items": items, "total": len(items)}


@router.get("/graph")
def graph(
    collection_id: str | None = None, session: Session = Depends(get_db)
) -> dict[str, list[dict[str, object]]]:
    statement = select(Paper).options(
        selectinload(Paper.author_links).selectinload(PaperAuthor.author)
    )
    if collection_id:
        require_collection(session, collection_id)
        statement = statement.where(
            select(CollectionPaper.paper_id)
            .where(
                CollectionPaper.paper_id == Paper.id,
                CollectionPaper.collection_id == collection_id,
            )
            .exists()
        )
    papers = session.scalars(statement).all()
    paper_ids = {paper.id for paper in papers}
    edges = (
        session.scalars(
            select(Edge).where(
                Edge.source_paper_id.in_(paper_ids), Edge.target_paper_id.in_(paper_ids)
            )
        ).all()
        if paper_ids
        else []
    )
    return {
        "nodes": [
            {
                "id": p.id,
                "label": p.title,
                "year": p.year,
                "authors": [l.author.name for l in p.author_links],
                "is_demo": p.is_demo,
            }
            for p in papers
        ],
        "edges": [
            {
                "id": e.id,
                "source": e.source_paper_id,
                "target": e.target_paper_id,
                "relation": e.relation,
                "description": e.description,
                "relation_source": e.relation_source,
            }
            for e in edges
        ],
    }
