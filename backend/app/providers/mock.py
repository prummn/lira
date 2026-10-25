"""Deterministic extractive fallback. It quotes original PDF text and abstains."""

from __future__ import annotations
import re
from ..models import PaperChunk
from .base import AnalysisResult, AnswerResult
from .validation import chunk_body as body
from .sections import section_contexts

STOPWORDS = set(
    "a an the and or of to in on at for with is are was were be been this that it we our how what which who why does do did has have can from through about paper tell me explain happened".split()
)
SECTION_TERMS = {
    "problem": ("problem", "introduction", "background", "引言"),
    "method": ("method", "architecture", "pre-training", "pretraining", "adaptation", "方法", "approach"),
    "findings": ("result", "finding", "experiment", "evaluation", "结果"),
    "limitations": ("limitation", "discussion", "局限"),
}
SCIENTIFIC_TERMS = (
    'verifier', 'self-training', 'reasoning', 'agents', 'agent', 'RAG', 'LLM',
    'retrieval', 'synthetic data', 'alignment', 'calibration', 'tree search',
    'knowledge graph', 'provenance', 'memory', 'multimodal', 'audio',
    'process supervision', 'curriculum learning', 'citation', 'synthesis',
)


def extract_concepts(chunks: list[PaperChunk]) -> list[str]:
    source = '\n'.join(chunk.content for chunk in chunks)
    concepts: list[str] = []
    for term in SCIENTIFIC_TERMS:
        match = re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', source, re.I)
        if match:
            concepts.append(match.group(0))
    return concepts[:16]


def tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 2 and token not in STOPWORDS
    }


class MockProvider:
    name = "MockProvider"
    mode = "extractive"
    configured = False
    translation_available = False

    def analyze(self, chunks: list[PaperChunk]) -> AnalysisResult:
        sections = section_contexts(chunks)
        useful = [chunk for chunk in chunks if body(chunk) and len(body(chunk)) > 30]
        abstract = next(
            (
                c
                for c in useful
                if "abstract" in (c.section or "").lower()
                or "摘要" in (c.section or "")
            ),
            None,
        )
        result = AnalysisResult(
            one_liner=body(abstract or useful[0]) if useful else None
        )
        chosen = [abstract or useful[0]] if useful else []
        for field, terms in SECTION_TERMS.items():
            candidates = [c for c in useful if any(t in sections[c.id] for t in terms)]
            if field in {'method','findings'}:
                candidates = [c for c in candidates if not any(t in sections[c.id] for t in ('related', 'background', 'prior work', 'previous', 'existing', '相关工作'))]
            if field == 'findings':
                candidates = [c for c in candidates
                              if not body(c).rstrip().endswith(('?','？'))
                              and not re.fullmatch(r'result|results?:', (c.section or '').strip(), re.I)]
            chunk = min(candidates, key=lambda c: min(i for i, term in enumerate(terms) if term in sections[c.id]), default=None)
            if chunk:
                setattr(result, field, body(chunk))
                chosen.append(chunk)
        # Every selected item is a verbatim source quote; unknown sections stay null.
        result.evidence_chunks = list({c.id: c for c in chosen}.values())
        result.concepts = extract_concepts(chunks)
        from .cards import extractive_card
        result.card = extractive_card(chunks,result)
        result.prompt_version = 'extractive_card_v1'
        for item in result.card.values():
            entries = item if isinstance(item,list) else [item] if item is not None else []
            for entry in entries:
                result.citations.extend(entry.citations)
        return result

    def ask(self, question: str, chunks: list[PaperChunk]) -> AnswerResult:
        sections = section_contexts(chunks)
        query_tokens = tokens(question)
        aliases = {
            "方法": SECTION_TERMS["method"],
            "结果": SECTION_TERMS["findings"],
            "局限": SECTION_TERMS["limitations"],
            "摘要": ("abstract", "摘要"),
        }
        mapped_sections = [term for chinese, terms in aliases.items() if chinese in question for term in terms]
        for field, terms in SECTION_TERMS.items():
            if any(term in question.casefold() for term in terms if term.isascii()):
                mapped_sections.extend(terms)
        ranked: list[tuple[int, PaperChunk]] = []
        for chunk in chunks:
            if len(body(chunk)) < 30:
                continue
            overlap = query_tokens & tokens(body(chunk))
            section_hit = any(
                t in sections[chunk.id] for t in mapped_sections
            )
            if overlap or section_hit:
                ranked.append((len(overlap) + (2 if section_hit else 0), chunk))
        ranked.sort(key=lambda item: (-item[0], item[1].page or 0, item[1].id))
        selected = [item[1] for item in ranked[:3]]
        if not selected:
            return AnswerResult(
                "当前论文原文中没有找到足够的相关证据，无法回答这个问题。请换用原文术语，或先导入带文本层的 PDF。",
                [],
                True,
            )
        answer = (
            "以下是当前论文中与问题匹配的原文摘录（本地抽取模式，未生成推断）：\n\n"
            + "\n\n".join(f"第 {c.page} 页：{body(c)}" for c in selected)
        )
        return AnswerResult(answer, selected, False)

    def translate(self, chunk: PaperChunk) -> str:
        raise NotImplementedError("翻译需要配置模型，原文已保留")

    def audit_knowledge_bundle(self, bundle: dict) -> dict:
        """Local mode never invents maintenance proposals."""
        return {"issues": [], "model_version": self.name, "prompt_version": "local_none"}
