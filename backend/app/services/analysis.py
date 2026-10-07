"""Analysis persistence binds every citation to a stored, actual PDF text block."""

from __future__ import annotations
import json
import hashlib
import uuid
from sqlalchemy.orm import Session
from ..models import Evidence, Paper, PaperAnalysis, PaperChunk
from ..providers.base import CardEntry, ModelProvider, ProviderError, VerifiedCitation
from ..schemas import PaperCard
from ..providers.mock import body
from ..providers.validation import canonical_quote


def evidence_for(chunk: PaperChunk) -> Evidence:
    source = body(chunk)
    if not source or source not in chunk.content:
        raise ValueError("Evidence must be a literal substring of the source chunk")
    return Evidence(
        id="evidence-" + uuid.uuid5(uuid.NAMESPACE_URL, chunk.id).hex[:20],
        paper_id=chunk.paper_id,
        claim=source,
        source_text=source,
        page=chunk.page,
        section=chunk.section,
        confidence=1.0,
        source_type="explicit",
        chunk_id=chunk.id,
        bbox_json=chunk.bbox_json,
        page_width=chunk.page_width,
        page_height=chunk.page_height,
    )


def evidence_for_citation(citation: VerifiedCitation, original: PaperChunk) -> Evidence:
    source = canonical_quote(original.content, citation.source_text)
    if source is None:
        raise ProviderError('模型引文无法在当前论文原文中验证，已有结果已保留')
    source_type = 'explicit' if citation.claim == source else 'llm_summary'
    digest = hashlib.sha256(json.dumps([original.id,source,citation.claim,source_type],ensure_ascii=False).encode()).hexdigest()[:24]
    return Evidence(id='evidence-' + digest, paper_id=original.paper_id, claim=citation.claim, source_text=source, page=original.page, section=original.section, confidence=1.0, source_type=source_type, chunk_id=original.id, bbox_json=original.bbox_json, page_width=original.page_width, page_height=original.page_height)


def analyze_paper(session: Session, paper: Paper, provider: ModelProvider) -> None:
    if not paper.chunks:
        paper.analysis = None
        paper.evidence.clear()
        paper.analysis_status = "no_text"
        session.flush()
        return
    result = provider.analyze(list(paper.chunks))
    chunk_lookup = {chunk.id: chunk for chunk in paper.chunks}
    verified = []
    def materialize(citation: VerifiedCitation) -> Evidence:
        original = chunk_lookup.get(citation.chunk.id)
        if original is None:
            raise ProviderError('模型引文不属于当前论文，已有结果已保留')
        if provider.mode == 'extractive' and citation.claim == body(original) and citation.source_text == body(original):
            return evidence_for(original)
        return evidence_for_citation(citation,original)
    for citation in result.citations:
        verified.append(materialize(citation))
    for candidate in result.evidence_chunks:
        original = chunk_lookup.get(candidate.id)
        if original is None or body(candidate) not in original.content:
            raise ValueError("Model returned evidence outside the current paper")
        verified.append(evidence_for(original))
    if provider.mode == 'remote' and not verified:
        raise ProviderError('模型没有返回可验证的原文证据，已有结果已保留')
    verified = list({item.id:item for item in verified}.values())
    verified.sort(key=lambda item:(item.page or 0,item.id))
    card_data: dict[str,object] = {'title':paper.title}
    def card_item(item: CardEntry,section_summary: bool = False) -> dict[str,object]:
        ids = list(dict.fromkeys(materialize(citation).id for citation in item.citations))
        data: dict[str,object] = {'content':item.content,'evidence_ids':ids}
        if section_summary:
            data['section'] = item.section or '未识别章节'
        return data
    for field,item in result.card.items():
        if isinstance(item,list):
            card_data[field] = [card_item(entry,field == 'section_summaries') for entry in item]
        elif isinstance(item,CardEntry):
            card_data[field] = card_item(item)
        else:
            card_data[field] = None
    card = PaperCard.model_validate(card_data)
    paper.evidence.clear()
    session.flush()
    paper.evidence.extend(verified)
    analysis = paper.analysis or PaperAnalysis(paper_id=paper.id)
    for key in ("one_liner", "problem", "method", "findings", "limitations"):
        setattr(analysis, key, getattr(result, key))
    analysis.concepts_json = json.dumps(result.concepts, ensure_ascii=False)
    analysis.provider = provider.name
    analysis.mode = provider.mode
    analysis.evidence_ids_json = json.dumps([item.id for item in verified])
    analysis.card_json = card.model_dump_json()
    analysis.model_version = result.model_version
    analysis.prompt_version = result.prompt_version
    paper.analysis = analysis
    paper.analysis_status = "ready"
    session.flush()
