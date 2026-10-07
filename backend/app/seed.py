"""Deterministic mock dataset used for local development and first-run demos."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Author,
    Collection,
    CollectionPaper,
    Edge,
    Evidence,
    Paper,
    PaperAnalysis,
    PaperAuthor,
    PaperChunk,
)

MOCK_PAPERS: tuple[dict[str, object], ...] = (
    {
        "id": "paper-001",
        "title": "Self-Improving Reasoning through Iterative Verification",
        "abstract": "We study a verifier-guided loop that lets language models generate, critique, and repair multi-step solutions without external labels.",
        "year": 2024,
        "venue": "NeurIPS",
        "authors": ["Mira Chen", "Arjun Rao", "Elena Park"],
        "tags": ["reasoning", "verification", "self-improvement"],
        "analysis": {
            "one_liner": "Verifier feedback turns sampled solutions into a stable self-improvement loop.",
            "problem": "Long-form reasoning models often improve their answer fluency without improving correctness.",
            "method": "The method alternates proposal generation with a learned process verifier and keeps edits with increasing confidence.",
            "findings": "Iterative verification improves GSM8K-style accuracy while using fewer samples than best-of-N.",
            "limitations": "The verifier remains brittle on tasks whose intermediate steps are under-specified.",
            "concepts": ["process supervision", "verifier", "test-time compute"],
        },
        "evidence": [
            (
                "The verifier scores each intermediate step before a candidate solution is accepted.",
                "Section 3 introduces a step-level verifier that rejects locally inconsistent traces.",
                5,
                "3.1",
            ),
            (
                "Iterative repair outperforms best-of-N at the same inference budget.",
                "Across arithmetic and symbolic benchmarks, the repair loop delivers a 6.2 point gain over best-of-N.",
                8,
                "4.2",
            ),
        ],
    },
    {
        "id": "paper-002",
        "title": "Bootstrapped Self-Training for Language Model Reasoning",
        "abstract": "A data-centric recipe for bootstrapping rationales from a small set of verified answers.",
        "year": 2025,
        "venue": "ICLR",
        "authors": ["Noah Williams", "Yuki Tanaka"],
        "tags": ["reasoning", "self-training", "synthetic data"],
        "analysis": {
            "one_liner": "Verified synthetic traces provide a practical curriculum for reasoning models.",
            "problem": "High-quality chain-of-thought annotations are expensive and difficult to scale.",
            "method": "A teacher samples rationales, a checker filters them, and a student is trained in confidence-weighted stages.",
            "findings": "The student retains gains after the teacher is removed from the loop.",
            "limitations": "Filtering quality is the main bottleneck for open-ended tasks.",
            "concepts": ["bootstrapping", "synthetic data", "curriculum learning"],
        },
        "evidence": [
            (
                "Confidence-weighted traces reduce error propagation during self-training.",
                "We weight each rationale by agreement between two independent checkers.",
                6,
                "3.3",
            )
        ],
    },
    {
        "id": "paper-003",
        "title": "Toolformer-Style Agents with Persistent Memory",
        "abstract": "We introduce a lightweight memory protocol for agents that call tools over long research sessions.",
        "year": 2024,
        "venue": "ACL Findings",
        "authors": ["Sofia Martinez", "David Kim"],
        "tags": ["agents", "memory", "tools"],
        "analysis": {
            "one_liner": "A typed memory protocol helps tool-using agents resume research tasks across sessions.",
            "problem": "Agent plans and intermediate evidence are often lost between sessions.",
            "method": "Memory entries are stored as claims with provenance, freshness, and a revalidation policy.",
            "findings": "Persistent memory raises multi-session task completion while keeping context windows small.",
            "limitations": "Stale claims can still influence planning when revalidation is skipped.",
            "concepts": ["agents", "provenance", "long-horizon tasks"],
        },
        "evidence": [
            (
                "Every memory entry carries an explicit freshness policy.",
                "Entries older than the policy horizon are marked for revalidation before planning.",
                4,
                "2.2",
            )
        ],
    },
    {
        "id": "paper-004",
        "title": "A Scaling Law for Retrieval-Augmented Generation",
        "abstract": "We characterize how corpus coverage, retriever quality, and generator capacity interact in retrieval-augmented language models.",
        "year": 2023,
        "venue": "EMNLP",
        "authors": ["Priya Nair", "Lucas Berg", "Hannah Lee"],
        "tags": ["retrieval", "scaling laws", "rag"],
        "analysis": {
            "one_liner": "Retrieval coverage determines when extra generator parameters stop helping factuality.",
            "problem": "RAG systems are tuned by trial and error across retriever and generator scales.",
            "method": "We fit a three-factor scaling model over controlled corpus, retriever, and decoder experiments.",
            "findings": "Coverage dominates early, then retriever precision becomes the limiting factor.",
            "limitations": "The law is measured on English knowledge benchmarks only.",
            "concepts": ["RAG", "scaling", "factuality"],
        },
        "evidence": [
            (
                "Retriever recall is the dominant factor at small corpus sizes.",
                "At fixed decoder size, doubling recall gives larger gains than doubling decoder parameters.",
                7,
                "4.1",
            )
        ],
    },
    {
        "id": "paper-005",
        "title": "Constitutional Feedback for Safe Generative Agents",
        "abstract": "A rule-based feedback process for improving refusal consistency without collecting harmful demonstrations.",
        "year": 2022,
        "venue": "Anthropic Technical Report",
        "authors": ["Amelia Zhao", "Theo Martin"],
        "tags": ["alignment", "feedback", "safety"],
        "analysis": {
            "one_liner": "Written principles can guide a self-critique loop for safer agent behavior.",
            "problem": "Human preference data under-represents rare but consequential safety failures.",
            "method": "The model critiques and revises responses against a compact constitution before preference training.",
            "findings": "Constitutional feedback improves refusal consistency with fewer direct harmful examples.",
            "limitations": "Principles can conflict and require careful ordering.",
            "concepts": ["alignment", "self-critique", "policy"],
        },
        "evidence": [
            (
                "The constitution is applied during critique and revision, before preference ranking.",
                "The training pipeline separates principle-guided revision from the final preference optimization stage.",
                3,
                "2.1",
            )
        ],
    },
    {
        "id": "paper-006",
        "title": "Audio Reasoning with Cross-Modal Scratchpads",
        "abstract": "We align acoustic events and text rationales through a shared scratchpad for spoken question answering.",
        "year": 2025,
        "venue": "Interspeech",
        "authors": ["Jun Seo", "Rina Patel"],
        "tags": ["audio", "multimodal", "reasoning"],
        "analysis": {
            "one_liner": "Intermediate acoustic tokens make spoken reasoning errors easier to diagnose.",
            "problem": "End-to-end audio language models hide whether an error came from perception or reasoning.",
            "method": "The model emits timestamped acoustic events before producing a natural-language answer.",
            "findings": "Cross-modal scratchpads improve temporal question answering and error attribution.",
            "limitations": "Scratchpad supervision requires timestamped transcripts.",
            "concepts": ["audio reasoning", "multimodal", "interpretability"],
        },
        "evidence": [
            (
                "Timestamped events expose perception failures before language generation.",
                "Ablations show that removing event tokens primarily harms temporal localization.",
                6,
                "4.3",
            )
        ],
    },
    {
        "id": "paper-007",
        "title": "Learning to Search with Verifier-Guided Tree Expansion",
        "abstract": "We combine Monte Carlo tree search with learned value and verifier models for mathematical problem solving.",
        "year": 2024,
        "venue": "ICML",
        "authors": ["Ethan Brooks", "Wei Liu", "Nadia El-Sayed"],
        "tags": ["search", "math", "verification"],
        "analysis": {
            "one_liner": "A verifier-guided tree policy allocates search budget to promising proof prefixes.",
            "problem": "Uniform reasoning traces waste compute on invalid branches.",
            "method": "Tree expansion combines a learned value estimate with a binary proof checker.",
            "findings": "The hybrid policy reaches stronger proofs under a fixed node budget.",
            "limitations": "It assumes access to an executable checker.",
            "concepts": ["tree search", "verifier", "mathematical reasoning"],
        },
        "evidence": [
            (
                "The checker is used to prune branches before value backpropagation.",
                "Verifier rejection prevents invalid prefixes from contributing to the tree policy.",
                5,
                "3.2",
            )
        ],
    },
    {
        "id": "paper-008",
        "title": "Evaluating Scientific Claims with Citation-Aware Models",
        "abstract": "A benchmark and model for checking whether generated scientific claims are supported by cited passages.",
        "year": 2023,
        "venue": "Nature Machine Intelligence",
        "authors": ["Isabel Green", "Marco Rossi"],
        "tags": ["evaluation", "citations", "evidence"],
        "analysis": {
            "one_liner": "Citation entailment is a measurable axis of scientific generation quality.",
            "problem": "Fluent summaries can cite relevant papers without actually supporting their claims.",
            "method": "The benchmark labels claim-passage entailment and citation completeness across disciplines.",
            "findings": "Citation-aware reranking reduces unsupported claims with a modest recall cost.",
            "limitations": "Annotation remains expensive for nuanced scientific claims.",
            "concepts": ["citation entailment", "evaluation", "scientific NLP"],
        },
        "evidence": [
            (
                "Citation completeness is reported separately from citation relevance.",
                "A citation can be relevant to a topic while failing to entail the generated claim.",
                2,
                "1.2",
            )
        ],
    },
    {
        "id": "paper-009",
        "title": "Graph Memory for Cross-Paper Research Synthesis",
        "abstract": "We represent paper claims, methods, and evidence as a typed graph to support cross-paper synthesis.",
        "year": 2025,
        "venue": "KDD",
        "authors": ["Lena Hoffmann", "Omar Haddad"],
        "tags": ["knowledge graph", "synthesis", "research tools"],
        "analysis": {
            "one_liner": "Typed evidence edges make synthesis queries inspectable and updateable.",
            "problem": "Flat notes lose the links between claims, methods, and the papers that support them.",
            "method": "A graph schema stores claims with typed support, contradiction, and extension edges.",
            "findings": "Graph queries surface convergent and conflicting evidence across a field.",
            "limitations": "Entity resolution remains difficult for changing terminology.",
            "concepts": ["knowledge graph", "synthesis", "provenance"],
        },
        "evidence": [
            (
                "Edges retain the evidence span that justified each cross-paper relation.",
                "Every synthesized relation points back to one or more source spans.",
                7,
                "3.4",
            )
        ],
    },
    {
        "id": "paper-010",
        "title": "Uncertainty Calibration for Research Copilots",
        "abstract": "We calibrate uncertainty estimates for retrieval-grounded assistants answering technical questions.",
        "year": 2024,
        "venue": "AAAI",
        "authors": ["Grace Wilson", "Kenji Ito"],
        "tags": ["uncertainty", "research assistant", "calibration"],
        "analysis": {
            "one_liner": "Answer confidence should reflect evidence coverage as well as model likelihood.",
            "problem": "Research assistants often sound certain when retrieved evidence is incomplete.",
            "method": "A calibration head combines retrieval coverage, agreement, and language-model uncertainty.",
            "findings": "Evidence-aware confidence improves selective answering and abstention.",
            "limitations": "Coverage estimates are sensitive to chunking quality.",
            "concepts": ["calibration", "abstention", "retrieval"],
        },
        "evidence": [
            (
                "Evidence coverage is an explicit feature of the confidence estimator.",
                "Removing coverage features increases overconfident answers on out-of-domain questions.",
                5,
                "3.1",
            )
        ],
    },
)


COLLECTIONS = (
    (
        "collection-reasoning",
        "Reasoning & Verification",
        "Methods for reliable multi-step reasoning.",
        "#E17A4D",
    ),
    (
        "collection-agents",
        "Agents & Memory",
        "Tool use, persistent memory, and long-horizon workflows.",
        "#4F8FBA",
    ),
    (
        "collection-evidence",
        "Evidence & Synthesis",
        "Citation, provenance, and cross-paper synthesis.",
        "#6B9B78",
    ),
)


def _demo_pdf(item: dict[str, object], previous_title: str | None) -> bytes:
    """Render the fictional fixture into an actual PDF so citations are locatable."""
    import fitz

    with fitz.open() as document:
        first = document.new_page()
        first.insert_textbox(
            fitz.Rect(50, 35, 545, 115), str(item["title"]), fontsize=18
        )
        first.insert_text(
            (50, 125),
            "FICTIONAL DEMO PAPER - NOT REAL RESEARCH",
            fontsize=10,
            color=(0.65, 0.2, 0.15),
        )
        first.insert_textbox(
            fitz.Rect(50, 143, 545, 205),
            "Fictional authors: "
            + ", ".join(item["authors"])
            + "\nAll venues, results and citations here are synthetic fixtures.",
            fontsize=10,
        )
        analysis = item["analysis"]
        for y, heading, text in (
            (225, "Abstract", item["abstract"]),
            (370, "1 Introduction", analysis["problem"]),
            (515, "2 Method", analysis["method"]),
        ):
            first.insert_text((50, y), heading, fontsize=14)
            first.insert_textbox(
                fitz.Rect(50, y + 15, 545, y + 115), str(text), fontsize=11
            )
        second = document.new_page()
        second.insert_text((50, 50), "3 Results", fontsize=14)
        texts = [str(analysis["findings"])] + [str(e[1]) for e in item["evidence"]]
        second.insert_textbox(
            fitz.Rect(50, 70, 545, 310), "\n\n".join(texts), fontsize=11
        )
        second.insert_text((50, 355), "4 Limitations", fontsize=14)
        second.insert_textbox(
            fitz.Rect(50, 375, 545, 505), str(analysis["limitations"]), fontsize=11
        )
        second.insert_text((50, 555), "References", fontsize=14)
        reference = (
            "Synthetic demo reference: " + previous_title
            if previous_title
            else "This fictional fixture has no references."
        )
        second.insert_textbox(fitz.Rect(50, 575, 545, 705), reference, fontsize=10)
        document.set_metadata(
            {
                "title": str(item["title"]),
                "author": "Fictional demo authors",
                "subject": "Fictional demo; not real research",
            }
        )
        return document.tobytes()


def seed_database(session: Session, storage: Path) -> None:
    """Seed empty libraries and repair only recognized fixtures from the old skeleton."""
    from .services.pdf import parse_pdf
    from .services.importing import attach_parsed
    from .services.analysis import analyze_paper
    from .providers.mock import MockProvider

    empty = session.scalar(select(Paper.id).limit(1)) is None
    if not empty and not any(
        session.get(Paper, str(item["id"])) is not None for item in MOCK_PAPERS
    ):
        return
    storage.mkdir(parents=True, exist_ok=True)
    for collection_id, name, description, color in COLLECTIONS:
        if session.get(Collection, collection_id) is None:
            session.add(
                Collection(
                    id=collection_id,
                    name=name,
                    description="Fictional demo collection. " + description,
                    color=color,
                )
            )
    session.flush()
    collection_for_tag = {
        "reasoning": "collection-reasoning",
        "verification": "collection-reasoning",
        "self-training": "collection-reasoning",
        "agents": "collection-agents",
        "memory": "collection-agents",
        "tools": "collection-agents",
        "citations": "collection-evidence",
        "evidence": "collection-evidence",
        "synthesis": "collection-evidence",
    }
    for index, item in enumerate(MOCK_PAPERS):
        paper = session.get(Paper, str(item["id"]))
        if paper is not None and paper.title != item["title"]:
            continue
        if paper is None:
            if not empty:
                continue
            paper = Paper(
                id=str(item["id"]),
                title=str(item["title"]),
                year=int(item["year"]),
                venue=str(item["venue"]),
                reading_status=(
                    "read" if item["id"] in {"paper-001", "paper-004"} else "unread"
                ),
                is_favorite=item["id"] in {"paper-001", "paper-009"},
                analysis_status="pending",
                tags_json=json.dumps(item["tags"], ensure_ascii=False),
                is_demo=True,
            )
            session.add(paper)
            session.flush()
        for order_index, name in enumerate(item["authors"]):
            demo_name = str(name) + " (fictional demo)"
            author_id = "author-" + hashlib.sha1(demo_name.encode()).hexdigest()[:12]
            author = session.get(Author, author_id)
            if author is None:
                author = Author(
                    id=author_id,
                    name=demo_name,
                    affiliation="Fictional demo author; no real affiliation",
                )
                session.add(author)
            if not any(
                link.author.name in {str(name), demo_name}
                for link in paper.author_links
            ):
                paper.author_links.append(
                    PaperAuthor(author=author, order_index=order_index)
                )
        for link in paper.author_links:
            link.author.affiliation = "Fictional demo author; no real affiliation"
        for collection_id in {
            collection_for_tag[str(tag)]
            for tag in item["tags"]
            if str(tag) in collection_for_tag
        }:
            if session.get(CollectionPaper, (collection_id, paper.id)) is None:
                session.add(
                    CollectionPaper(collection_id=collection_id, paper_id=paper.id)
                )
        if (
            paper.is_demo
            and paper.pdf_path
            and Path(paper.pdf_path).is_file()
            and any(c.bbox_json for c in paper.chunks)
        ):
            if paper.analysis is None or paper.analysis.concepts_json == '[]' or paper.analysis.card_json == '{}':
                analyze_paper(session, paper, MockProvider())
            continue
        data = _demo_pdf(item, str(MOCK_PAPERS[index - 1]["title"]) if index else None)
        parsed = parse_pdf(data)
        target = storage / f"{paper.id}.pdf"
        target.write_bytes(data)
        paper.pdf_path = str(target.resolve())
        paper.sha256 = hashlib.sha256(data).hexdigest()
        paper.is_demo = True
        paper.chunks.clear()
        session.flush()
        attach_parsed(paper, parsed)
        session.flush()
        analyze_paper(session, paper, MockProvider())
    session.flush()
    for index in range(1, len(MOCK_PAPERS)):
        source_id, target_id = str(MOCK_PAPERS[index]["id"]), str(
            MOCK_PAPERS[index - 1]["id"]
        )
        source, target = session.get(Paper, source_id), session.get(Paper, target_id)
        if not source or not target or not source.is_demo or not target.is_demo:
            continue
        edge_id = f"edge-{index:03d}"
        edge = session.get(Edge, edge_id)
        if edge is None:
            edge = Edge(
                id=edge_id, source_paper_id=source_id, target_paper_id=target_id
            )
            session.add(edge)
        edge.relation = "cites"
        edge.relation_source = "demo"
        edge.description = "Fictional fixture reference, explicitly printed in the demo PDF; not a real citation."
    session.commit()
