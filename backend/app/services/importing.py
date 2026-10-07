"""Validated synchronous PDF import, storage and parsing; duplicate content is rejected."""

from __future__ import annotations
import hashlib
import json
import uuid
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import Paper, PaperChunk
from ..providers.mock import MockProvider
from .analysis import analyze_paper
from .pdf import InvalidPDF, ParsedPDF, parse_pdf

MAX_PDF_BYTES = 50 * 1024 * 1024


def attach_parsed(paper: Paper, parsed: ParsedPDF) -> None:
    paper.page_count = parsed.page_count
    for index, block in enumerate(parsed.blocks):
        paper.chunks.append(
            PaperChunk(
                id=f"chunk-{paper.id}-{index:06d}",
                paper_id=paper.id,
                page=block.page,
                section=block.section,
                content=block.content,
                bbox_json=json.dumps(block.bbox),
                page_width=block.page_width,
                page_height=block.page_height,
            )
        )
    abstracts = [
        block.content
        for block in parsed.blocks
        if block.section
        and ("abstract" in block.section.lower() or "摘要" in block.section)
    ]
    paper.abstract = "\n\n".join(abstracts) or None


def import_pdf_bytes(
    session: Session, storage: Path, filename: str, data: bytes
) -> Paper:
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF 文件超过 50 MB 上限")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(415, "仅支持导入 PDF 文件")
    digest = hashlib.sha256(data).hexdigest()
    if session.scalar(select(Paper.id).where(Paper.sha256 == digest)):
        raise HTTPException(409, "相同 PDF 已在文献库中，无需重复导入")
    try:
        parsed = parse_pdf(data)
    except InvalidPDF as error:
        raise HTTPException(422, str(error)) from error
    paper_id = "paper-" + uuid.uuid4().hex[:16]
    target = storage / f"{paper_id}.pdf"
    filename_title = Path(filename).stem.replace("_", " ").strip()
    paper = Paper(
        id=paper_id,
        title=parsed.title or filename_title or "未命名论文",
        pdf_path=str(target.resolve()),
        sha256=digest,
        reading_status="unread",
        analysis_status="pending",
        tags_json="[]",
        is_demo=False,
    )
    attach_parsed(paper, parsed)
    session.add(paper)
    try:
        session.flush()
        # Import is local-first even when a remote provider is configured.
        analyze_paper(session, paper, MockProvider())
        storage.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(409, "相同 PDF 已在文献库中，无需重复导入") from error
    except Exception:
        session.rollback()
        target.unlink(missing_ok=True)
        raise
    return paper
