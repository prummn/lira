"""Shared resource lookups with consistent, readable 404 errors."""

from fastapi import HTTPException
from sqlalchemy.orm import Session
from ..models import Collection, Paper
from ..services.serialization import find_paper


def require_paper(session: Session, paper_id: str) -> Paper:
    paper = find_paper(session, paper_id)
    if paper is None:
        raise HTTPException(404, "未找到这篇论文")
    return paper


def require_collection(session: Session, collection_id: str) -> Collection:
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(404, "未找到这个集合")
    return collection
