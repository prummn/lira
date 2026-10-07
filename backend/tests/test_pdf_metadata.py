from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz
import pytest

from app.services.pdf import HEADING, ParsedPDF, parse_pdf
from app.services.pdf_metadata import detect_headings, read_lines


def replay_layout(monkeypatch: pytest.MonkeyPatch, filename: str) -> ParsedPDF:
    """Replay the external PDF engine's actual layout, including Unicode spans."""
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / filename).read_text(
            encoding="utf-8"
        )
    )

    class Page:
        def __init__(self, source: dict) -> None:
            self.source = source
            self.cropbox = fitz.Rect(0, 0, source["width"], source["height"])

        def get_text(self, mode: str, sort: bool = False) -> dict:
            assert mode == "dict"
            return {"blocks": self.source["blocks"]}

    class Document:
        needs_pass = False
        page_count = len(fixture["pages"])
        metadata = fixture["metadata"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter(Page(page) for page in fixture["pages"])

    monkeypatch.setattr("app.services.pdf.fitz.open", lambda **kwargs: Document())
    return parse_pdf(b"%PDF-layout-regression")


@pytest.fixture
def attention(monkeypatch: pytest.MonkeyPatch) -> ParsedPDF:
    return replay_layout(monkeypatch, "attention_layout.json")


def test_title_ignores_permission_and_larger_rotated_arxiv_stamp(attention: ParsedPDF):
    assert attention.title == "Attention Is All You Need"
    assert attention.metadata_sources["title"] == "pdf_layout"


def test_authors_follow_visual_rows_and_preserve_unicode(attention: ParsedPDF):
    assert attention.authors == [
        "Ashish Vaswani",
        "Noam Shazeer",
        "Niki Parmar",
        "Jakob Uszkoreit",
        "Llion Jones",
        "Aidan N. Gomez",
        "Łukasz Kaiser",
        "Illia Polosukhin",
    ]


def test_publication_year_does_not_use_revision_or_pdf_creation_date(attention: ParsedPDF):
    assert attention.year == 2017
    assert attention.arxiv_id == "1706.03762"
    assert attention.venue and "NIPS 2017" in attention.venue


def test_generic_numbered_headings_combine_separate_layout_lines(attention: ParsedPDF):
    sections = {block.section for block in attention.blocks}
    assert "3 Model Architecture" in sections
    assert "3.1 Encoder and Decoder Stacks" in sections
    assert "3.2.1 Scaled Dot-Product Attention" in sections
    assert "Encoder:" not in sections


def test_abstract_excludes_rotated_stamp_footnotes_and_footer(attention: ParsedPDF):
    abstract = [b.content for b in attention.blocks if b.section == "Abstract"]
    assert any("The dominant sequence transduction models" in text for text in abstract)
    assert all("arXiv:" not in text for text in abstract)
    assert all("Equal contribution" not in text for text in abstract)
    assert all("31st Conference" not in text for text in abstract)


def test_source_text_and_canonical_geometry_are_preserved(attention: ParsedPDF):
    title = next(b for b in attention.blocks if b.content == "Attention Is All You Need")
    assert title.bbox == pytest.approx((211.488007, 148.829880, 399.893494, 166.045273))
    assert (title.page_width, title.page_height) == (612, 792)
    assert any(b.content.startswith("Provided proper attribution") for b in attention.blocks)
    assert any("Łukasz Kaiser∗" == b.content for b in attention.blocks)
    method = next(b for b in attention.blocks if "Model Architecture" in b.content)
    assert method.content == "3\nModel Architecture"


def synthetic_pdf(lines: list[tuple[str, float, float, str]], metadata: dict | None = None,
                  references: str | None = None) -> bytes:
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        for text, y, size, font in lines:
            page.insert_text((70, y), text, fontsize=size, fontname=font)
        if references:
            page = document.new_page(width=600, height=800)
            page.insert_text((70, 80), "References", fontsize=12, fontname="hebo")
            page.insert_text((70, 120), references, fontsize=10)
        if metadata:
            document.set_metadata(metadata)
        return document.tobytes()


def test_multiline_title_and_plain_author_names():
    parsed = parse_pdf(synthetic_pdf([
        ("Learning Reliable Scientific", 90, 18, "hebo"),
        ("Representations from Evidence", 113, 18, "hebo"),
        ("Alice Smith, Bob A. Jones", 155, 11, "helv"),
        ("University of Example", 175, 10, "helv"),
        ("Abstract", 220, 12, "hebo"),
        ("We study evidence representations.", 240, 10, "helv"),
    ]))
    assert parsed.title == "Learning Reliable Scientific Representations from Evidence"
    assert parsed.authors == ["Alice Smith", "Bob A. Jones"]


def test_identifiers_come_from_front_matter_not_abstract_or_references():
    parsed = parse_pdf(synthetic_pdf([
        ("A Study of Reliable Evidence", 90, 18, "hebo"),
        ("doi: 10.1234/own-paper.2020", 170, 10, "helv"),
        ("Abstract", 220, 12, "hebo"),
        ("We compare arXiv:1801.01234 and doi:10.5555/other.", 245, 10, "helv"),
    ], references="Other Paper. 10.9999/referenced. arXiv:1901.01234."))
    assert parsed.doi == "10.1234/own-paper.2020"
    assert parsed.arxiv_id is None
    assert parsed.year is None


def test_creation_date_and_reference_identifiers_are_not_bibliography():
    parsed = parse_pdf(synthetic_pdf([
        ("Undated Reliable Research", 90, 18, "hebo"),
        ("Abstract", 180, 12, "hebo"),
        ("We investigate a dataset from 2016.", 205, 10, "helv"),
    ], metadata={"creationDate": "D:20240410211143Z"},
       references="Other Paper (2022). DOI:10.9999/referenced. arXiv:2201.01234."))
    assert parsed.year is None
    assert parsed.doi is None
    assert parsed.arxiv_id is None


def test_labeled_publication_year_is_distinct_from_labeled_revision_year():
    published = parse_pdf(synthetic_pdf([
        ("A Research Paper with a Publication Date", 90, 18, "hebo"),
        ("Published online: 2020", 155, 10, "helv"),
        ("Revised: 2024", 175, 10, "helv"),
        ("Abstract", 220, 12, "hebo"),
        ("We investigate reliable evidence.", 245, 10, "helv"),
    ]))
    assert published.year == 2020
    assert published.metadata_sources["year"] == "pdf_text"


def test_bold_authors_do_not_include_unstyled_affiliation_city():
    parsed = parse_pdf(synthetic_pdf([
        ("A Research Paper with Affiliations", 90, 18, "hebo"),
        ("Alice Smith", 155, 11, "hebo"),
        ("Example University", 175, 10, "helv"),
        ("New York", 195, 10, "helv"),
        ("Abstract", 230, 12, "hebo"),
        ("We investigate reliable evidence.", 255, 10, "helv"),
    ]))
    assert parsed.authors == ["Alice Smith"]


def test_styled_generic_heading_routes_following_body_without_rewriting_text():
    parsed = parse_pdf(synthetic_pdf([
        ("Reliable Scientific Research", 90, 18, "hebo"),
        ("Abstract", 180, 12, "hebo"),
        ("We study reliable evidence.", 205, 10, "helv"),
        ("Experimental Protocol", 280, 12, "hebo"),
        ("Each system is evaluated on three tasks.", 305, 10, "helv"),
    ]))
    body = next(b for b in parsed.blocks if "Each system" in b.content)
    assert body.section == "Experimental Protocol"


def test_two_column_abstract_does_not_capture_neighboring_body_column():
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((100, 90), "A Two Column Research Paper", fontsize=18, fontname="hebo")
        page.insert_text((125, 180), "Abstract", fontsize=12, fontname="hebo")
        page.insert_textbox(fitz.Rect(70, 205, 280, 310),
                            "We study reliable evidence.\nThis is the actual abstract.", fontsize=10)
        page.insert_textbox(fitz.Rect(320, 168, 550, 290),
                            "The body continues in the right column.\nThis is not the abstract.", fontsize=10)
        page.insert_text((70, 360), "1 Introduction", fontsize=12, fontname="hebo")
        parsed = parse_pdf(document.tobytes())
    abstract = "\n".join(b.content for b in parsed.blocks if b.section == "Abstract")
    assert "actual abstract" in abstract
    assert "right column" not in abstract


def test_bold_table_cells_and_multiline_prose_do_not_start_sections():
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((70, 80), "A Research Evaluation", fontsize=18, fontname="hebo")
        page.insert_text((70, 160), "4 Results", fontsize=12, fontname="hebo")
        for x, text in [(70, "Parser"), (250, "Training"), (430, "Score")]:
            page.insert_text((x, 200), text, fontsize=10, fontname="hebo")
        page.insert_text((70, 225), "Model performance is shown above.", fontsize=10)
        page.insert_textbox(fitz.Rect(70, 260, 550, 310),
                            "For each experiment the model uses a different configuration\n"
                            "and we evaluate all configurations on the same tasks.",
                            fontsize=10, fontname="hebo")
        parsed = parse_pdf(document.tobytes())
    assert all(b.section == "4 Results" for b in parsed.blocks if b.bbox[1] > 180)


@pytest.mark.parametrize("example_index", [0, 1, 2])
def test_official_lora_figure_and_table_method_labels_are_not_headings(example_index: int):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "lora_figure_table_layout.json")
        .read_text(encoding="utf-8")
    )
    example = fixture["examples"][example_index]
    lines = read_lines(example["page"] - 1, example["blocks"])
    headings = detect_headings(lines, HEADING, example["body_font"], set(), first_page=False)
    assert any(line.text == "Method" for line in lines)
    assert "Method" not in headings.values(), example["context"]
    assert "Dataset" not in headings.values(), example["context"]


def test_unstyled_method_at_text_margin_remains_a_legitimate_heading():
    parsed = parse_pdf(synthetic_pdf([
        ("A Research Paper with Plain Headings", 90, 18, "hebo"),
        ("Method", 160, 11, "helv"),
        ("We compare the original source passages.", 185, 11, "helv"),
    ]))
    passage = next(b for b in parsed.blocks if "We compare" in b.content)
    assert passage.section == "Method"


def test_actual_bert_columns_keep_pretraining_out_of_experimental_results(monkeypatch):
    from app.models import PaperChunk
    from app.providers.mock import MockProvider

    parsed = replay_layout(monkeypatch, "bert_columns_layout.json")
    data = next(b for b in parsed.blocks if b.content.startswith("Pre-training data"))
    fine_tuning = next(b for b in parsed.blocks if b.content.startswith("Fine-tuning is straightforward"))
    right_continuation = next(b for b in parsed.blocks if b.content.startswith("Compared to pre-training"))
    results = next(b for b in parsed.blocks if "11 NLP tasks" in b.content)
    assert data.section == "3.1 Pre-training BERT"
    assert fine_tuning.section == "3.2 Fine-tuning BERT"
    assert right_continuation.section == "3.2 Fine-tuning BERT"
    assert results.section == "4 Experiments"
    # Keep extracted source blocks in their established order and coordinates.
    assert parsed.blocks.index(data) > next(i for i, b in enumerate(parsed.blocks)
                                            if b.content == "Experiments")
    assert data.bbox[0] == pytest.approx(72)
    assert data.bbox[1] == pytest.approx(320.119110)
    chunks = [PaperChunk(id=f"bert-{i}", paper_id="bert-layout", page=b.page,
                        content=b.content, section=b.section) for i, b in enumerate(parsed.blocks)]
    analysis = MockProvider().analyze(chunks)
    assert "11 NLP tasks" in analysis.findings
    assert "Pre-training data" not in analysis.findings
    assert analysis.card["main_results"].citations[0].source_text in results.content


def test_parsed_pdf_extension_keeps_original_constructor_compatible():
    parsed = ParsedPDF(1, "An existing caller", [])
    assert parsed.authors == []
    assert parsed.year is None
    assert parsed.metadata_sources == {}
