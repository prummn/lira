"""Build bounded, evidence-preserving context for questions about a selection."""

from __future__ import annotations

from collections.abc import Iterable
import re

from ..models import Paper, PaperChunk
from .reading_paragraphs import paragraphs_for
from ..providers.validation import canonical_quote


_RELATED_CUES = (
    '什么时候', '何时', '如何', '为什么', '为何', '关系', '流程', '机制', '区别',
    'when', 'how', 'why', 'relationship', 'relation', 'difference', 'workflow',
    'mechanism', 'function', 'parameter', 'argument', 'output', 'parse', 'parser',
    'heartbeat', 'yield', 'user', 'response', 'return',
)

# The paper is usually English while the reader's question is often Chinese.
# A tiny deterministic vocabulary bridge keeps mechanism retrieval useful
# without spending another model call just to translate a query.
_QUERY_EXPANSIONS = {
    '模型': ('model', 'llm', 'completion'),
    '输出': ('output', 'completion', 'token', 'buffer', 'response'),
    '函数': ('function', 'executor', 'schema', 'call'),
    '参数': ('parameter', 'argument', 'parser', 'validate'),
    '普通文字': ('output buffer', 'user', 'response', 'message'),
    '控制流': ('control flow', 'heartbeat', 'yield', 'queue'),
    '执行': ('execute', 'executor', 'run'),
    '用户': ('user', 'response', 'message'),
}


def _terms(value: str) -> set[str]:
    """Extract stable retrieval terms without introducing an embedding call."""
    lowered = value.casefold()
    english = set(re.findall(r"[a-z][a-z0-9_-]{2,}", lowered))
    chinese = set(re.findall(r"[\u4e00-\u9fff]{2,}", lowered))
    # Chinese questions have no whitespace boundaries. Bigrams retain enough
    # signal for a local lexical route while avoiding a large prompt or model
    # request just to decide the context scope.
    chinese_bigrams = {part[index:index + 2] for part in chinese for index in range(len(part) - 1)}
    terms = english | chinese | chinese_bigrams
    for phrase, aliases in _QUERY_EXPANSIONS.items():
        if phrase in lowered:
            terms.update(aliases)
    return terms


def _needs_related_context(question: str) -> bool:
    lowered = question.casefold()
    return any(cue in lowered for cue in _RELATED_CUES)


def _append_related(target: list[PaperChunk], chunks: list[PaperChunk], question: str, anchor: PaperChunk) -> bool:
    terms = _terms(question)
    if not terms:
        return False
    scored: list[tuple[int, int, str, PaperChunk]] = []
    for chunk in chunks:
        if chunk.id in {item.id for item in target}:
            continue
        section = (chunk.section or '').casefold()
        haystack = f'{section} {chunk.content}'.casefold()
        overlap = sum(1 for term in terms if term in haystack)
        # Section headings are a stronger signal than an incidental word in a
        # caption or reference entry. This keeps 2.3/2.4 beside a visual page
        # ahead of unrelated blocks that happen to mention “model”.
        section_overlap = sum(1 for term in terms if term in section)
        overlap += section_overlap * 2
        if overlap <= 0:
            continue
        # Nearby chunks are useful tie-breakers, but lexical evidence always
        # wins so an unrelated adjacent paragraph cannot displace a definition.
        distance = abs((chunk.page or 0) - (anchor.page or 0))
        scored.append((overlap, -distance, chunk.id, chunk))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    added = [item[3] for item in scored[:10]]
    _append_unique(target, added)
    return bool(added)


def _append_unique(target: list[PaperChunk], chunks: Iterable[PaperChunk]) -> None:
    seen = {chunk.id for chunk in target}
    for chunk in chunks:
        if chunk.id not in seen:
            target.append(chunk)
            seen.add(chunk.id)


def selection_context(
    paper: Paper,
    selected_chunk: PaperChunk,
    selected_text: str,
    scope: str = "auto",
    question: str = "",
    visual: bool = False,
) -> tuple[list[PaperChunk], str]:
    """Return chunks ordered from the user's selection out to the paper.

    The provider still applies its own token budget and relevance ranking. This
    ordering pins the selected passage and its derived paragraph ahead of the
    rest, while retaining enough surrounding material for questions whose
    answer is defined elsewhere in the paper.
    """
    chunks = sorted(list(paper.chunks), key=lambda item: (item.page or 0, item.id))
    by_id = {chunk.id: chunk for chunk in chunks}
    result: list[PaperChunk] = [selected_chunk]
    paragraph_ids: list[str] = []
    try:
        for paragraph in paragraphs_for(paper):
            if selected_chunk.id not in {anchor["chunk_id"] for anchor in paragraph["anchors"]}:
                continue
            if canonical_quote(paragraph["source_text"], selected_text) is not None or canonical_quote(selected_chunk.content, selected_text) is not None:
                # Keep the paragraph's document order.  A set made cross-page
                # passages appear shuffled, which is especially confusing when
                # the answer cites the continuation after a figure or footer.
                paragraph_ids = list(dict.fromkeys(
                    anchor["chunk_id"] for anchor in paragraph["anchors"]
                    if isinstance(anchor.get("chunk_id"), str)
                ))
                _append_unique(result, (by_id[item] for item in paragraph_ids if item in by_id))
                break
    except (OSError, RuntimeError, ValueError):
        # A damaged or image-only PDF must not make the question action fail;
        # the selected verified chunk remains usable on its own.
        paragraph_ids = []

    related_added = False
    # A visual page can contain many small OCR/text-layer blocks. Put the
    # lexical neighbours for a mechanism question ahead of those fragments so
    # the provider's bounded context does not spend its entire budget on the
    # current page and miss the section that defines the other half of the
    # answer. Full-paper mode keeps the same ordering while still exposing the
    # rest of the paper after the high-signal material.
    if scope in {'auto', 'full'} and _needs_related_context(question):
        related_added = _append_related(result, chunks, question + ' ' + selected_text, selected_chunk)

    if visual:
        # A rendered page can contain a caption, axis labels, and body text in
        # separate extraction blocks. Keep all same-page text beside the image.
        _append_unique(result, (chunk for chunk in chunks if chunk.page == selected_chunk.page))

    if scope in {"auto", "section", "full"}:
        _append_unique(result, (chunk for chunk in chunks if chunk.section == selected_chunk.section))
    if scope == "full":
        _append_unique(result, chunks)
    if scope == "auto" and related_added:
        return result, "related"
    return result, ("full" if scope == "full" else "section" if scope in {"auto", "section"} else "paragraph")
