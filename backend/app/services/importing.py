"""Validated synchronous PDF import, storage and parsing; duplicate content is rejected."""

from __future__ import annotations
import hashlib
import json
import re
import uuid
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import Author, Paper, PaperAuthor, PaperChunk
from ..providers.mock import MockProvider
from .analysis import analyze_paper
from .pdf import InvalidPDF, ParsedPDF, parse_pdf
from .metadata import enrich_metadata, normalize_doi
from .downloads import normalize_arxiv_id

MAX_PDF_BYTES = 50 * 1024 * 1024
METADATA_FIELDS = ('title', 'authors', 'year', 'venue', 'doi', 'arxiv_id')


def metadata_sources(paper: Paper) -> dict[str, str]:
    try:
        sources = json.loads(paper.metadata_sources_json or '{}')
    except json.JSONDecodeError:
        return {}
    return sources if isinstance(sources, dict) else {}


def sync_card_title(paper: Paper) -> None:
    if not paper.analysis:
        return
    try:
        card = json.loads(paper.analysis.card_json or '{}')
    except json.JSONDecodeError:
        return
    if isinstance(card, dict):
        card['title'] = paper.title
        paper.analysis.card_json = json.dumps(card, ensure_ascii=False)


def replace_authors(session: Session, paper: Paper, names: list[str]) -> None:
    names = list(dict.fromkeys(name.strip() for name in names if name.strip()))
    if [link.author.name for link in paper.author_links] == names:
        return
    paper.author_links.clear()
    # Remove association rows before recreating a changed author order.
    session.flush()
    for index, name in enumerate(names):
        author_id = 'author-' + uuid.uuid5(uuid.NAMESPACE_URL, name).hex[:12]
        author = session.get(Author, author_id)
        if author is None:
            author = Author(id=author_id, name=name)
            session.add(author)
        paper.author_links.append(PaperAuthor(author=author, order_index=index))


def apply_metadata(session: Session, paper: Paper, parsed: ParsedPDF | None, *, source_arxiv_id: str | None = None) -> None:
    sources = metadata_sources(paper)
    fields: dict[str, object] = {}
    parsed_sources = getattr(parsed, 'metadata_sources', {}) if parsed else {}
    if parsed:
        for name in METADATA_FIELDS:
            value = getattr(parsed, name, None)
            if value is not None and value != [] and value != '':
                fields[name] = value
    if source_arxiv_id and not fields.get('arxiv_id'):
        fields['arxiv_id'] = source_arxiv_id
        parsed_sources = {**parsed_sources, 'arxiv_id': 'source_url'}
    if 'arxiv_id' in fields:
        fields['arxiv_id'] = normalize_arxiv_id(str(fields['arxiv_id']))
    if 'doi' in fields:
        fields['doi'] = normalize_doi(str(fields['doi']))
    # A cleared manual identifier is intentional and must not be silently restored.
    arxiv_id = paper.arxiv_id if sources.get('arxiv_id') == 'manual' else fields.get('arxiv_id') or paper.arxiv_id or normalize_arxiv_id(paper.source_url)
    doi = paper.doi if sources.get('doi') == 'manual' else fields.get('doi') or paper.doi
    enriched = enrich_metadata(arxiv_id=arxiv_id, doi=doi)
    incoming_sources = {name: parsed_sources.get(name, 'pdf_text') for name in fields}
    fields.update(enriched.fields)
    incoming_sources.update(enriched.sources)
    warnings = list(enriched.warnings)
    for name, value in fields.items():
        if name not in METADATA_FIELDS or sources.get(name) == 'manual' or value is None or value == [] or value == '':
            continue
        if name == 'doi' and session.scalar(select(Paper.id).where(Paper.doi == value, Paper.id != paper.id)):
            raise HTTPException(409, '相同 DOI 已属于另一篇文献，请核对重复论文或手动修正编号')
        if name == 'authors':
            replace_authors(session, paper, value)
        else:
            setattr(paper, name, value)
        sources[name] = incoming_sources.get(name, 'pdf_text')
    paper.metadata_sources_json = json.dumps(sources, ensure_ascii=False)
    paper.metadata_warnings_json = json.dumps(list(dict.fromkeys(warnings)), ensure_ascii=False)
    sync_card_title(paper)


def _recovered_section(chunk: PaperChunk, bounds: tuple[float, ...], parsed: ParsedPDF) -> tuple[bool, str | None]:
    if len(bounds) != 4:
        return False, None
    normalized = lambda content: re.sub(r'\s+', ' ', content).strip()
    original_text = normalized(chunk.content)
    fragments = [block for block in parsed.blocks if block.page == chunk.page
                 and block.bbox[0] >= bounds[0] and block.bbox[1] >= bounds[1]
                 and block.bbox[2] <= bounds[2] and block.bbox[3] <= bounds[3]
                 and normalized(block.content) in original_text]
    if not fragments or normalized(' '.join(block.content for block in fragments)) != original_text:
        return False, None
    sections = {block.section for block in fragments}
    if len(sections) != 1:
        return False, None
    return True, fragments[0].section


def refresh_metadata(session: Session, paper: Paper) -> None:
    parsed = None
    warnings = []
    if paper.pdf_path and Path(paper.pdf_path).is_file():
        try:
            data = Path(paper.pdf_path).read_bytes()
            if len(data) > MAX_PDF_BYTES:
                raise InvalidPDF('PDF 超过大小上限')
            parsed = parse_pdf(data)
        except (InvalidPDF, OSError):
            warnings.append('原始 PDF 暂无法重新解析，已保留现有原文和研究笔记')
    if parsed is None and not paper.arxiv_id and not paper.doi and not normalize_arxiv_id(paper.source_url):
        raise HTTPException(422, '没有可读取的原始 PDF 或论文编号，请上传 PDF 或手动补全元数据')
    apply_metadata(session, paper, parsed)
    if parsed:
        matching = {(block.page, block.content, tuple(block.bbox)): block for block in parsed.blocks}
        sections = {}
        unmatched = 0
        for chunk in paper.chunks:
            try:
                bounds = tuple(json.loads(chunk.bbox_json or '[]'))
            except (json.JSONDecodeError, TypeError):
                bounds = ()
            block = matching.get((chunk.page, chunk.content, bounds))
            if block is None:
                recovered, section = _recovered_section(chunk, bounds, parsed)
                if not recovered:
                    unmatched += 1
                    continue
            else:
                section = block.section
            chunk.section = section
            sections[chunk.id] = section
        for evidence in paper.evidence:
            if evidence.chunk_id in sections:
                evidence.section = sections[evidence.chunk_id]
        abstracts = [block.content for block in parsed.blocks if block.section and ('abstract' in block.section.lower() or '摘要' in block.section)]
        if abstracts:
            paper.abstract = '\n\n'.join(abstracts)
        if unmatched:
            warnings.append(f'{unmatched} 个现有原文块与新版解析布局不完全匹配，已保留其 ID、内容和定位')
    if warnings:
        current = json.loads(paper.metadata_warnings_json or '[]')
        paper.metadata_warnings_json = json.dumps(list(dict.fromkeys(current + warnings)), ensure_ascii=False)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, '识别出的 DOI 与已有文献冲突，请手动核对元数据') from error


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
    session: Session, storage: Path, filename: str, data: bytes, *, source_url: str | None = None, source_arxiv_id: str | None = None
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
        source_url=source_url,
        metadata_sources_json=json.dumps({'title': 'filename'} if not parsed.title else {}, ensure_ascii=False),
        metadata_warnings_json='[]',
    )
    attach_parsed(paper, parsed)
    session.add(paper)
    try:
        apply_metadata(session, paper, parsed, source_arxiv_id=source_arxiv_id)
        session.flush()
        # Import is local-first even when a remote provider is configured.
        analyze_paper(session, paper, MockProvider())
        storage.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(409, "相同 PDF 或 DOI 已在文献库中，请核对重复文献") from error
    except Exception:
        session.rollback()
        target.unlink(missing_ok=True)
        raise
    return paper
