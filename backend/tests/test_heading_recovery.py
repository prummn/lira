"""Original PDF glyph layouts: true titles, appendix prefixes and TOC rows."""
import json
from pathlib import Path

import pytest

from app.services.pdf import HEADING
from app.services.pdf_metadata import detect_headings, read_lines

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/recovered_headings_layout.json')
                     .read_text(encoding='utf-8'))['examples']


@pytest.mark.parametrize('paper,page,wanted', [
    ('self-rag', 7, '4.3 EXPERIMENTAL SETTINGS'),
    ('self-rag', 11, 'ETHICAL CONCERNS'),
    ('self-rag', 17, 'A.2 SELF-RAG TRAINING'),
    ('self-rag', 20, 'C RESULTS'),
    ('adaptive-rag', 14, 'A.3 Implementation Details'),
])
def test_observed_true_heading_is_detected(paper, page, wanted):
    example = next(item for item in EXAMPLES if item['paper'] == paper and item['page'] == page)
    headings = detect_headings(read_lines(page - 1, example['blocks']), HEADING,
        example['body_font'], set(), first_page=False)
    assert wanted in headings.values()


def test_appendix_toc_does_not_start_the_results_section():
    example = next(item for item in EXAMPLES if item['paper'] == 'self-rag' and item['page'] == 16)
    headings = detect_headings(read_lines(15, example['blocks']), HEADING,
        example['body_font'], set(), first_page=False)
    assert 'C Results' not in headings.values()
