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
        page.insert_text((190, 510), 'P = rho R T + mu * du/dx', fontsize=12)
        page.insert_text((510, 510), '(3)', fontsize=9)

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
    equation = next(region for region in regions if region["kind"] == "equation")
    assert figure["kind"] == "figure"
    assert figure["bbox"][1] > 145
    assert figure["bbox"][3] < 430
    assert table["kind"] == "table"
    assert table["bbox"][1] < 550
    assert table["bbox"][3] < 655
    assert equation['label'] == 'Equation (3)'
    assert equation['bbox'][3] < table['bbox'][1]

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


def test_chinese_hyphenated_figure_number_is_kept_whole():
    from app.services.visual_regions import CAPTION, _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.draw_rect(fitz.Rect(100, 100, 500, 260), width=1)
        page.insert_text((105, 282), 'Figure 1-1 Scramjet combustor schematic', fontsize=10)

        regions = _page_regions(page, 1)

        assert len(regions) == 1
        assert regions[0]['label'] == 'Figure 1-1'
        assert CAPTION.match('图1-1 超声速燃烧室结构示意图').group(1) == '图1-1'


def test_chinese_body_figure_reference_is_not_detected_as_a_caption():
    from app.services.visual_regions import _body_reference_caption

    assert _body_reference_caption('图1', '所示，近年来对这些内容的研究仍在进行')


def test_bilingual_captions_for_one_figure_are_one_visual_region():
    from app.services.visual_regions import _merge_bilingual_regions

    base = {'id':'figure-cn','page':1,'kind':'figure','label':'图 1',
            'caption':'图 1 SST 湍流模型主要发展历程','bbox':[100,100,500,320],
            'page_width':600,'page_height':800}
    english = {**base,'id':'figure-en','label':'Fig. 1',
               'caption':'Fig. 1 Major developments in SST turbulence model'}

    regions = _merge_bilingual_regions([base,english])

    assert len(regions) == 1
    assert '图 1' in regions[0]['caption']
    assert 'Fig. 1' in regions[0]['caption']


def test_contents_and_figure_index_pages_do_not_emit_visual_regions():
    from app.services.visual_regions import _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((250, 40), 'Figure List', fontsize=14)
        for index, text in enumerate((
            'Figure 1-1 Engine schematic ........................................ 1',
            'Figure 1-2 Combustion process ..................................... 2',
            'Figure 2-1 Computational domain ................................... 3',
        )):
            page.insert_text((65, 100 + index * 24), text, fontsize=10)
        page.draw_rect(fitz.Rect(100, 190, 500, 260), width=1)

        assert _page_regions(page, 1) == []


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


def test_display_equations_are_selectable_regions_but_inline_math_is_not():
    from app.services.visual_regions import _equation_regions

    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_textbox(fitz.Rect(60, 70, 540, 125),
            'The objective uses x = y to describe the result in this ordinary sentence. '
            'This inline expression must stay part of the paragraph.', fontsize=11)
        page.insert_text((205, 190), 'F1 = tanh(arg1) + (1 - F1) phi2', fontsize=12)
        page.insert_text((510, 190), '(1)', fontsize=9)
        page.insert_text((190, 240), 'Dk/Dt = -rho u_i du_i/dx_j', fontsize=11)
        page.insert_text((205, 256), '+ d/dx_j [(mu + mu_t) dk/dx_j]', fontsize=11)
        page.insert_text((510, 256), '(2)', fontsize=9)

        regions = _equation_regions(page, 1)

    assert len(regions) == 2
    assert regions[0]['kind'] == 'equation'
    assert regions[0]['label'] == 'Equation (1)'
    assert regions[1]['label'] == 'Equation (2)'
    assert regions[1]['bbox'][3] - regions[1]['bbox'][1] > 25


def test_same_baseline_equations_in_two_columns_remain_separate():
    from app.services.visual_regions import _equation_regions

    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_textbox(fitz.Rect(60, 50, 285, 125),
            'The left column introduces a model and describes its assumptions in several lines of ordinary prose.', fontsize=10)
        page.insert_textbox(fitz.Rect(315, 50, 540, 125),
            'The right column discusses a separate model and explains the evaluation setup in regular prose.', fontsize=10)
        page.insert_text((65, 190), 'x = a + b', fontsize=12)
        page.insert_text((320, 190), 'y = c + d', fontsize=12)

        regions = _equation_regions(page, 1)

    assert len(regions) == 2
    assert regions[0]['bbox'][2] < 300
    assert regions[1]['bbox'][0] > 300


@pytest.fixture
def real_equation_page():
    import json
    from pathlib import Path
    from types import SimpleNamespace

    samples = json.loads((Path(__file__).parent / 'fixtures/chinese_equation_layout.json').read_text(encoding='utf-8'))
    def load(source, number):
        sample = next(item for item in samples if item['source'] == source and item['page'] == number)
        return SimpleNamespace(cropbox=SimpleNamespace(width=sample['width'], height=sample['height']),
                               get_text=lambda *args, **kwargs: {'blocks': sample['blocks']},
                               get_drawings=lambda: sample['drawings'],
                               get_images=lambda **kwargs: [(index,) for index, _ in enumerate(sample['images'])],
                               get_image_rects=lambda index: [sample['images'][index]])
    return load


def test_real_sst_equation_nine_includes_both_lines_and_fraction_extents(real_equation_page):
    from app.services.visual_regions import _equation_regions
    regions = _equation_regions(real_equation_page('sst', 10), 10)
    equation = next(region for region in regions if region['label'] == 'Equation (9)')
    assert equation['bbox'][0] <= 308
    assert equation['bbox'][1] < 104
    assert equation['bbox'][3] >= 188
    assert equation['bbox'][3] < 197


def test_real_sst_dense_math_never_merges_across_columns(real_equation_page):
    from app.services.visual_regions import _equation_regions
    page = real_equation_page('sst', 20)
    regions = _equation_regions(page, 20)
    assert any(region['label'] == 'Equation (16)' for region in regions)
    for region in regions:
        left, _, right, _ = region['bbox']
        assert right < 302 or left > 298, region


def test_real_thesis_symbol_font_equations_keep_hyphenated_numbers(real_equation_page):
    from app.services.visual_regions import _equation_regions
    regions = _equation_regions(real_equation_page('thesis', 22), 22)
    for number in range(1, 7):
        assert any(region['label'] == f'Equation (2-{number})' for region in regions)
    first = next(region for region in regions if region['label'] == 'Equation (2-1)')
    assert first['bbox'][1] < 336
    assert first['bbox'][3] >= 367
    assert first['bbox'][3] < 380


def test_formula_literals_in_running_prose_are_not_display_equations():
    from app.services.visual_regions import _equation_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((60, 100), 'The loss x = a + b is measured for every training example.', fontsize=11)
        page.insert_text((60, 150), 'For x >= 2 and y <= 5 we observe a stable configuration.', fontsize=11)
        assert _equation_regions(page, 1) == []


def test_numbered_simple_fraction_needs_no_second_operator():
    from app.services.visual_regions import _equation_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((260, 190), 'Ma =', fontsize=12)
        page.insert_text((300, 184), 'u', fontsize=12)
        page.insert_text((300, 198), 'c', fontsize=12)
        page.insert_text((510, 190), '(3-6)', fontsize=11)
        regions = _equation_regions(page, 1)
        assert len(regions) == 1
        assert regions[0]['label'] == 'Equation (3-6)'
        assert regions[0]['bbox'][3] >= 201


@pytest.mark.parametrize('page,label,bottom', [(36,'表3-1',737),(37,'表3-2',491),(42,'表3-3',709)])
def test_real_thesis_three_rule_tables_include_all_data_rows(real_equation_page, page, label, bottom):
    from app.services.visual_regions import _page_regions
    regions = _page_regions(real_equation_page('thesis', page), page)
    table = next(region for region in regions if region['label'] == label)
    assert table['bbox'][3] >= bottom
    assert table['bbox'][3] < 753


def test_real_sst_page_header_does_not_attach_itself_to_figure_six(real_equation_page):
    from app.services.visual_regions import _page_regions
    regions = _page_regions(real_equation_page('sst', 20), 20)
    figure = next(region for region in regions if region['kind'] == 'figure' and region['label'] == '图 6')
    assert figure['bbox'][0] > 300
    assert figure['bbox'][1] > 80
    assert any(region['kind'] == 'equation' and region['bbox'][1] < 200 for region in regions)


def test_adjacent_thesis_images_do_not_merge_through_their_captions(real_equation_page):
    from app.services.visual_regions import _page_regions
    regions = _page_regions(real_equation_page('thesis', 42), 42)
    first = next(region for region in regions if region['label'] == '图3-10')
    second = next(region for region in regions if region['label'] == '图3-11')
    assert first['bbox'][3] < second['bbox'][1]


def test_nearly_transparent_watermark_does_not_expand_the_figure_into_body_text():
    from app.services.visual_regions import _page_regions
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        watermark = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), True)
        watermark.clear_with(0)
        watermark.set_alpha(bytes([5]) * 10000)
        page.insert_image(fitz.Rect(100, 200, 500, 600), pixmap=watermark)
        page.insert_text((110, 230), 'Ordinary body text above the actual chart.', fontsize=11)
        page.draw_rect(fitz.Rect(110, 450, 490, 630))
        page.insert_text((150, 655), 'Figure 1: The actual visible chart.', fontsize=10)
        figure = next(r for r in _page_regions(page, 1) if r['kind'] == 'figure')
        assert figure['bbox'][1] >= 440


def test_real_sst_multiline_bilingual_caption_is_complete_without_the_next_paragraph(real_equation_page):
    from app.services.visual_regions import _page_regions
    figure = next(r for r in _page_regions(real_equation_page('sst', 20), 20) if r['label'] == '图 6')
    assert 'mental data for two' in figure['caption']
    assert '数与实验数据的比较' in figure['caption']
    assert figure['bbox'][3] >= 272.4
    assert figure['bbox'][3] < 285
