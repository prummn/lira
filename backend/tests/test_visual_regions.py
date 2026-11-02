import fitz
import pytest


def pdf_with_figure_and_table() -> bytes:
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((55, 35), "3 Results", fontsize=14)
        page.insert_textbox(
            fitz.Rect(55, 55, 540, 145),
            "A long introductory paragraph explains the research setting and remains ordinary selectable prose. It contains enough detail to behave like a normal reading paragraph.",
            fontsize=11,
        )
        page.draw_rect(fitz.Rect(100, 190, 500, 350), color=(0.1, 0.2, 0.3), width=1.5)
        page.draw_line((130, 320), (450, 220), color=(0.8, 0.2, 0.1), width=2)
        page.draw_line((130, 320), (450, 320), color=(0.2, 0.4, 0.8), width=1)
        page.insert_textbox(fitz.Rect(90, 365, 510, 405), "Figure 1: A long caption for the system architecture.", fontsize=10)
        page.insert_textbox(
            fitz.Rect(55, 430, 545, 485),
            "This long paragraph below the figure must remain a separate selectable and translatable paragraph. It explains the result in complete sentences without becoming part of the figure selection.",
            fontsize=11,
        )

        page.insert_text((90, 535), "Table 5: SWE-bench results", fontsize=10)
        for y in (550, 575, 600, 625):
            page.draw_line((80, y), (520, y), color=(0.2, 0.2, 0.2), width=0.7)
        page.draw_line((80, 550), (80, 625), color=(0.2, 0.2, 0.2), width=0.7)
        page.draw_line((520, 550), (520, 625), color=(0.2, 0.2, 0.2), width=0.7)
        page.insert_text((95, 568), "Model   Resolved   Apply", fontsize=9)
        page.insert_text((95, 593), "Agent A   18.2   31.4", fontsize=9)
        page.insert_text((95, 618), "Agent B   20.1   34.8", fontsize=9)
        page.insert_textbox(
            fitz.Rect(55, 655, 545, 725),
            "A second long paragraph explains how to interpret the benchmark and remains available for translation. It also contains a full explanation that should stay independent of the table region.",
            fontsize=11,
        )
        return document.tobytes()


def test_visual_regions_are_precomputed_and_do_not_swallow_prose(client):
    imported = client.post(
        "/api/papers/import",
        files={"file": ("visual-regions.pdf", pdf_with_figure_and_table(), "application/pdf")},
    )
    assert imported.status_code == 201, imported.text
    paper = imported.json()

    response = client.get(f"/api/papers/{paper['id']}/visual-regions")

    assert response.status_code == 200, response.text
    regions = response.json()["items"]
    figure = next(region for region in regions if region["label"].startswith("Figure 1"))
    table = next(region for region in regions if region["label"].startswith("Table 5"))
    assert figure["kind"] == "figure"
    assert figure["bbox"][1] > 145
    assert figure["bbox"][3] < 430
    assert table["kind"] == "table"
    assert table["bbox"][1] < 550
    assert table["bbox"][3] < 655

    reading = client.get(f"/api/papers/{paper['id']}/reading-paragraphs").json()["paragraphs"]
    prose = [paragraph for paragraph in reading if paragraph["kind"] == "prose"]
    assert any("long paragraph below the figure" in paragraph["text"] for paragraph in prose)
    assert any("second long paragraph" in paragraph["text"] for paragraph in prose)


def page_with_adjacent_long_tables(document):
    """Sparse rules and merged cell blocks reproduce NL2Repo tables 3 and 4."""
    page = document.new_page(width=600, height=800)
    columns = (95, 250, 310, 375, 435, 490)

    def rule(y):
        page.draw_line((85, y), (535, y), width=0.7)

    def row(y, values):
        for x, value in zip(columns, values):
            page.insert_text((x, y), value, fontsize=8)

    page.insert_text((65, 75), 'Table 3: Main results across difficulty levels', fontsize=10)
    rule(100)
    row(112, ('Model', 'Overall', 'Pass@1', 'Easy', 'Medium', 'Hard'))
    rule(120)
    for index in range(12):
        row(132 + index * 11, (f'Claude-Sonnet-4.5-{index}', '40.2', '3', '51.8', '44.5', '25.1'))
    rule(260)

    page.insert_text((125, 281), 'Table 4: Model performance by task category', fontsize=10)
    rule(305)
    row(316, ('Model', 'Web Dev', 'Testing', 'Utility', 'ML', 'Data'))
    rule(324)
    for index in range(12):
        row(335 + index * 10, (f'Claude-Sonnet-4.5-{index}', '56.9%', '30.4%', '59.8%', '19.7%', '36.7%'))
    rule(452)
    row(464, ('Model', 'Database', 'Network', 'Batch', 'System', '-'))
    rule(472)
    for index in range(12):
        row(484 + index * 10, (f'Claude-Sonnet-4.5-{index}', '41.3%', '23.4%', '43.3%', '43.6%', '-'))
    rule(602)
    page.insert_textbox(fitz.Rect(65, 627, 545, 710),
        'As shown in Table 3, models struggle to complete repository-level tasks. '
        'This ordinary prose explains the results and must remain outside both table selections.', fontsize=11)
    return page


@pytest.mark.parametrize('label,bottom,top_limit', [('Table 3', 260, 270), ('Table 4', 602, 627)])
def test_long_table_regions_include_all_rows_without_crossing_adjacent_captions(label, bottom, top_limit):
    from app.services.visual_regions import _blocks, _page_regions
    with fitz.open() as document:
        page = page_with_adjacent_long_tables(document)
        blocks = _blocks(page, 600, 800)
        assert any(len(block['text']) > 160 and block['line_count'] > 30 for block in blocks)
        regions = _page_regions(page, 1)
        table = next(region for region in regions if region['label'] == label)
        assert table['bbox'][3] >= bottom, 'The final data rows and bottom rule must be included'
        assert table['bbox'][3] < top_limit, 'The following caption or prose must stay separate'
        if label == 'Table 4':
            assert table['bbox'][1] > 260, 'The preceding table bottom rule belongs to Table 3'


def test_bottom_caption_includes_full_table_but_stops_at_prose():
    from app.services.visual_regions import _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        for y in (100, 125, 275):
            page.draw_line((90, y), (510, y), width=0.7)
        for index in range(14):
            for x, value in zip((100, 280, 380, 470), (f'Model-{index}', '38.5', '19.4', '7.2')):
                page.insert_text((x, 115 + index * 11), value, fontsize=9)
        page.insert_text((120, 295), 'Table 2: Results with a caption below the table.', fontsize=10)
        page.insert_textbox(fitz.Rect(65, 322, 540, 390), 'This paragraph follows the bottom caption and explains the model results. It must not become part of the table selection.', fontsize=11)
        table = next(region for region in _page_regions(page, 1) if region['label'] == 'Table 2')
        assert table['bbox'][1] < 100
        assert table['bbox'][3] < 322


def test_two_columns_do_not_pull_a_neighboring_table_into_the_selection():
    from app.services.visual_regions import _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        for offset, number in ((0, 300), (300, 400)):
            page.insert_text((35 + offset, 85), f'Table {number}: Results', fontsize=10)
            for y in (100, 120, 250):
                page.draw_line((30 + offset, y), (270 + offset, y), width=0.7)
            for index in range(12):
                for x, value in zip((40, 135, 200), (f'Model-{index}', '18.7', '26.4')):
                    page.insert_text((x + offset, 115 + index * 11), value, fontsize=8)
        regions = _page_regions(page, 1)
        left = next(region for region in regions if region['label'] == 'Table 300')
        right = next(region for region in regions if region['label'] == 'Table 400')
        assert left['bbox'][2] < 300
        assert right['bbox'][0] > 300
        assert left['bbox'][3] >= 250 and right['bbox'][3] >= 250


def test_body_figure_reference_cannot_use_a_table_rule_as_its_graphic():
    from app.services.visual_regions import _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((150, 75), 'Table 6 Interaction turns and model performance.', fontsize=9)
        for y in (95, 120, 255):
            page.draw_line((140, y), (460, y), width=0.7)
        for index in range(10):
            for x, value in zip((150, 300, 390), (f'Model-{index}', '181.6', '39.9')):
                page.insert_text((x, 113 + index * 14), value, fontsize=8)
        page.insert_textbox(fitz.Rect(65, 280, 545, 365),
            'Efficiency and persistence vary across models. Increasing interaction attempts does not guarantee success. The quality of planning and execution matters more.', fontsize=11)
        page.insert_textbox(fitz.Rect(65, 400, 545, 485),
            'Figure 5 quantifies these phenomena. The non-finish rate is calculated as the percentage of tasks where the agent never invoked the finish tool.', fontsize=11)
        regions = _page_regions(page, 1)
        assert any(region['label'] == 'Table 6' for region in regions)
        assert not any(region['kind'] == 'figure' for region in regions)


@pytest.mark.parametrize('with_caption', [False, True])
def test_body_reference_cannot_reach_a_figure_across_prose_or_another_caption(with_caption):
    from app.services.visual_regions import _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.draw_rect(fitz.Rect(100, 100, 500, 220), width=1)
        if with_caption:
            page.insert_text((110, 242), 'Figure 5 Early termination rates across models.', fontsize=9)
        page.insert_textbox(fitz.Rect(65, 275, 545, 345),
            'Failure to complete the repository is a primary cause of low pass rates. We categorize incomplete tasks into early termination and non-finish.', fontsize=11)
        page.insert_textbox(fitz.Rect(65, 370, 545, 440),
            'Figure 5 quantifies these phenomena. The non-finish rate measures tasks that never invoked the finish tool.', fontsize=11)
        regions = _page_regions(page, 1)
        assert len(regions) == int(with_caption)
        if with_caption:
            assert regions[0]['caption'].startswith('Figure 5 Early termination')
            assert regions[0]['bbox'][3] < 275


def test_reference_immediately_after_real_caption_does_not_create_a_second_figure():
    from app.services.visual_regions import _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.draw_rect(fitz.Rect(100, 100, 500, 220), width=1)
        page.insert_text((110, 242), 'Figure 5 Early termination rates across models.', fontsize=9)
        page.insert_textbox(fitz.Rect(65, 260, 545, 325),
            'Figure 5 quantifies these phenomena. This paragraph explains the rates and remains ordinary selectable prose.', fontsize=11)
        regions = _page_regions(page, 1)
        assert len(regions) == 1
        assert regions[0]['bbox'][3] < 260


@pytest.mark.parametrize('caption_above', [False, True])
def test_real_figure_caption_can_start_with_a_verb_without_special_typography(caption_above):
    from app.services.visual_regions import _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.draw_rect(fitz.Rect(100, 160, 500, 300), width=1)
        caption_y = 140 if caption_above else 325
        page.insert_text((100, caption_y), 'Figure 5 shows early termination rates across models.', fontsize=10)
        regions = _page_regions(page, 1)
        assert len(regions) == 1
        assert regions[0]['label'] == 'Figure 5'
        assert regions[0]['bbox'][1] < 160
        assert regions[0]['bbox'][3] > 300


@pytest.mark.parametrize('wrapped_caption', [False, True])
def test_body_figure_reference_remains_a_readable_prose_paragraph(client, wrapped_caption):
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((65, 40), 'Visual Selection and Reference Detection', fontsize=18)
        page.insert_text((65, 65), 'Results', fontsize=14)
        page.draw_rect(fitz.Rect(100, 100, 500, 220), width=1)
        if wrapped_caption:
            page.insert_textbox(fitz.Rect(100, 232, 500, 270),
                'Figure 5 shows early termination rates across models. Thinking models exhibit high rates of premature completion and incomplete tasks.', fontsize=10)
        else:
            page.insert_text((100, 242), 'Figure 5 shows early termination rates across models.', fontsize=10)
        page.insert_textbox(fitz.Rect(65, 280, 545, 350),
            'Failure to complete the repository is a primary cause of low pass rates. We categorize incomplete tasks into early termination and non-finish.', fontsize=11)
        page.insert_textbox(fitz.Rect(65, 375, 545, 455),
            'Figure 5 quantifies these phenomena. The non-finish rate is calculated as the percentage of tasks where the agent never invoked the finish tool.', fontsize=11)
        content = document.tobytes()
    imported = client.post('/api/papers/import', files={'file': ('figure-reference.pdf', content, 'application/pdf')})
    assert imported.status_code == 201, imported.text
    paper_id = imported.json()['id']
    paragraphs = client.get(f'/api/papers/{paper_id}/reading-paragraphs').json()['paragraphs']
    reference = next(p for p in paragraphs if p['text'].startswith('Figure 5 quantifies'))
    assert reference['kind'] == 'prose'
    caption = next(p for p in paragraphs if p['text'].startswith('Figure 5 shows'))
    assert caption['kind'] == 'caption'
