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


def test_real_rgb_figure_response_is_not_an_alphabetic_appendix_heading(monkeypatch):
    parsed = replay_layout(monkeypatch, 'rag_rgb_layout.json')
    replies = [block for block in parsed.blocks if block.content.startswith('I can not answer the question because of the')]
    assert replies
    assert all(block.section == 'Introduction' for block in replies)


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


def test_rgb_abstract_next_to_a_figure_and_bold_findings_remain_prose(monkeypatch):
    parsed = replay_layout(monkeypatch, "rag_rgb_layout.json")
    abstract = "\n".join(b.content for b in parsed.blocks if b.section == "Abstract")
    assert "Retrieval-Augmented Generation (RAG) is a promising" in abstract
    assert "considerable journey ahead" in abstract
    assert "Nobel" not in abstract
    finding = next(b for b in parsed.blocks if b.content.startswith("(2) The increasing noise rate"))
    assert finding.section == "Results on Noise Robustness"


def test_rgb_fallback_byline_does_not_use_figure_labels(monkeypatch):
    parsed = replay_layout(monkeypatch, 'rag_rgb_layout.json')
    assert parsed.authors == ['Jiawei Chen', 'Hongyu Lin', 'Xianpei Han', 'Le Sun']


def test_acm_publisher_boundary_applies_to_each_line_in_a_shared_block():
    with fitz.open() as doc:
        page = doc.new_page(width=600,height=800)
        page.insert_text((70,90),'A Source Paper',fontsize=18,fontname='hebo')
        page.insert_textbox(fitz.Rect(70,200,550,400),
                            'This study investigates retrieval evidence in a scientific research workspace.\n'
                            'We evaluate retrieval methods using original source passages and annotated data.\n'
                            'CCS Concepts\n'
                            'Information systems: Retrieval models; Knowledge management and text analysis.', fontsize=9)
        parsed = parse_pdf(doc.tobytes())
    abstract = '\n'.join(b.content for b in parsed.blocks if b.section=='Abstract')
    assert 'This study investigates' in abstract
    assert 'Information systems' not in abstract


def test_unlabeled_acm_abstract_excludes_all_lines_of_a_wide_caption():
    with fitz.open() as doc:
        page = doc.new_page(width=600,height=800)
        page.insert_text((70,90),'A Source Paper',fontsize=18,fontname='hebo')
        page.insert_textbox(fitz.Rect(50,150,550,230),
                            'This study investigates retrieval evidence in a scientific research workspace. '
                            'We evaluate retrieval methods using original source passages and annotated data.',fontsize=9)
        page.insert_textbox(fitz.Rect(50,240,550,310),
                            'Figure 1: A detailed comparison of model architectures used to retrieve documents across the evaluated collection. '
                            'The first panel describes the source processing stages, and the second panel presents measurement results.',fontsize=9)
        page.insert_text((50,330),'CCS Concepts: Information systems',fontsize=9)
        parsed = parse_pdf(doc.tobytes())
    abstract = '\n'.join(b.content for b in parsed.blocks if b.section=='Abstract')
    assert 'This study investigates' in abstract
    assert 'panel' not in abstract


def test_inline_abstract_byline_does_not_treat_company_as_an_author():
    parsed = parse_pdf(synthetic_pdf([
        ('Evaluation of Scientific Research',90,18,'hebo'),
        ('Alice Smith1,2, Bob Jones3',145,11,'helv'),
        ('Tencent Company',170,10,'helv'),
        ('Abstract. We investigate scientific evidence.',220,10,'helv'),
    ]))
    assert parsed.authors == ['Alice Smith','Bob Jones']


def test_abstract_does_not_include_a_following_figure_caption(monkeypatch):
    parsed = replay_layout(monkeypatch,'rag_caption_layout.json')
    abstract = '\n'.join(b.content for b in parsed.blocks if b.section=='Abstract')
    assert 'trajectory in the field' in abstract
    assert 'Figure 1:' not in abstract
    assert any(b.content.startswith('Figure 1:') for b in parsed.blocks)


def test_ieee_inline_abstract_preserves_original_text_and_excludes_index_terms(monkeypatch):
    parsed = replay_layout(monkeypatch, "rag_ieee_layout.json")
    abstract = "\n".join(b.content for b in parsed.blocks if b.section == "Abstract")
    assert abstract.startswith("Abstract—Advancements")
    assert "suggest potential directions for future research" in abstract
    assert "Index Terms" not in abstract
    assert "Recent years have witnessed" not in abstract


def test_ieee_centered_roman_heading_remains_a_section(monkeypatch):
    parsed = replay_layout(monkeypatch, 'rag_ieee_layout.json')
    heading = next(block for block in parsed.blocks if block.content == 'I. INTRODUCTION')
    assert heading.section == 'I. INTRODUCTION'


@pytest.mark.parametrize("fixture,start,end", [
    ("rag_crud_acm_layout.json", "Retrieval-Augmented Generation (RAG) is a technique", "optimizing the RAG technology"),
    ("rag_feb_acm_layout.json", "Federated search systems aggregate", "context of RAG pipelines"),
    ("rag_survey_acm_layout.json", "Retrieval-Augmented Generation (RAG) merges", "applications of LLMs"),
])
def test_unlabeled_acm_abstract_is_bounded_by_publisher_front_matter(monkeypatch, fixture, start, end):
    parsed = replay_layout(monkeypatch, fixture)
    abstract = "\n".join(b.content for b in parsed.blocks if b.section == "Abstract")
    assert abstract.startswith(start)
    assert end in abstract
    assert "CCS Concepts" not in abstract
    assert "Permission to make" not in abstract
    assert "Authors’ addresses" not in abstract
    assert "ACM Reference Format" not in abstract


def test_arxiv_revision_is_retained_separately_from_canonical_identifier(monkeypatch):
    parsed = replay_layout(monkeypatch, "rag_crud_acm_layout.json")
    assert parsed.arxiv_id == "2401.17043"
    assert parsed.arxiv_version == 2


def test_crud_wrapped_affiliations_do_not_become_partial_fallback_byline(monkeypatch):
    parsed = replay_layout(monkeypatch, 'rag_crud_acm_layout.json')
    assert parsed.authors == []


def test_publisher_template_instructions_are_not_a_paper_venue(monkeypatch):
    parsed = replay_layout(monkeypatch, 'rag_survey_acm_layout.json')
    assert parsed.venue is None


@pytest.mark.parametrize('index,forbidden', [
    (0, {'Knowledge', 'Correction', 'Generation', 'Generator'}),
    (1, {'13 end'}),
])
def test_crag_diagram_labels_and_algorithm_lines_are_not_sections(index, forbidden):
    fixture = json.loads((Path(__file__).parent / 'fixtures/crag_headings_layout.json').read_text(encoding='utf-8'))
    example = fixture['examples'][index]
    headings = detect_headings(read_lines(example['page'] - 1, example['blocks']), HEADING,
        example['body_font'], set(), first_page=False)
    assert forbidden.isdisjoint(headings.values())


def test_crag_wrapped_numbered_heading_keeps_the_full_section_title():
    fixture = json.loads((Path(__file__).parent / 'fixtures/crag_headings_layout.json').read_text(encoding='utf-8'))
    example = fixture['examples'][2]
    headings = detect_headings(read_lines(example['page'] - 1, example['blocks']), HEADING,
        example['body_font'], set(), first_page=False)
    assert '5.7 Consistent Supplementation of Web Search Knowledge' in headings.values()
    assert 'Search Knowledge' not in headings.values()


@pytest.mark.parametrize('index', [0, 1, 2])
def test_real_appendix_titles_and_pseudocode_have_distinct_structure(index):
    fixture = json.loads((Path(__file__).parent / 'fixtures/rag_appendix_headings_layout.json').read_text(encoding='utf-8'))
    example = fixture['examples'][index]
    headings = detect_headings(read_lines(example['page'] - 1, example['blocks']), HEADING,
        example['body_font'], set(), first_page=False)
    if index == 0:
        assert 'C Results' in headings.values()
    else:
        assert {'end if', 'end for', 'end function'}.isdisjoint(headings.values())
