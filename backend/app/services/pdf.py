"""PyMuPDF parser: original page coordinates, no OCR and no synthesized text."""

from __future__ import annotations
from dataclasses import dataclass, field
import re
import pymupdf as fitz

from .pdf_metadata import (
    ABSTRACT, LayoutLine, abstract_bounds, body_font, detect_headings,
    extract_bibliography, read_lines, section_reading_order,
)


class InvalidPDF(ValueError):
    pass


@dataclass(frozen=True)
class ParsedBlock:
    page: int
    section: str | None
    content: str
    bbox: tuple[float, float, float, float]
    page_width: float
    page_height: float


@dataclass(frozen=True)
class ParsedPDF:
    page_count: int
    title: str | None
    blocks: list[ParsedBlock]
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    metadata_sources: dict[str, str] = field(default_factory=dict)


HEADING = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+)?(?:abstract|introduction|motivation|background|core idea|contributions?|datasets?|metrics?|baselines?|ablation(?:s| findings| study)?|future work|claims?|related methods|prerequisite concepts|related work|problem(?: statement)?|method(?:s|ology)?|approach|experiment(?:s)?|results?|findings|evaluation|limitations?|discussion|conclusion(?:s)?|references|摘要|引言|动机|背景|核心思路|贡献|数据集|评估指标|基线|消融实验|未来工作|方法|实验|结果|局限性|结论)(?:\s*[:：].*)?$",
    re.I,
)


def parse_pdf(data: bytes) -> ParsedPDF:
    if not data.startswith(b"%PDF-"):
        raise InvalidPDF("文件内容不是有效 PDF")
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise InvalidPDF("PDF 已加密，请导入解锁后的文件")
            if document.page_count == 0:
                raise InvalidPDF("PDF 没有可读取的页面")
            pages = []
            for page_index, page in enumerate(document):
                raw_blocks = page.get_text("dict", sort=True)["blocks"]
                pages.append((float(page.cropbox.width), float(page.cropbox.height),
                              raw_blocks, read_lines(page_index, raw_blocks)))
            body_size = body_font([line for _, _, _, lines in pages for line in lines])
            facts, title_keys = extract_bibliography(
                document.metadata, pages[0][3], pages[0][1], body_size
            )
            blocks: list[ParsedBlock] = []
            current_section: str | None = None
            for page_index, (width, height, raw_blocks, lines) in enumerate(pages):
                # Canonical top-left coordinates relative to the unrotated CropBox.
                # PDF.js owns display rotation, including inverse selection transforms.
                headings = detect_headings(lines, HEADING, body_size, title_keys,
                                           first_page=page_index == 0)
                abstract_region = abstract_bounds(lines)
                lookup = {line.key: line for line in lines}
                following_heading = next((label for label in headings.values()
                                          if not ABSTRACT.fullmatch(label)), None)
                page_blocks: list[tuple[int, ParsedBlock]] = []
                for block_index in section_reading_order(raw_blocks, lines, width, body_size):
                    block = raw_blocks[block_index]
                    if block.get("type") != 0:
                        continue
                    group: list[str] = []
                    bounds: list[tuple[float, float, float, float]] = []
                    group_section: str | None = None

                    def flush() -> None:
                        if group:
                            x0 = max(0.0, min(b[0] for b in bounds))
                            y0 = max(0.0, min(b[1] for b in bounds))
                            x1 = min(width, max(b[2] for b in bounds))
                            y1 = min(height, max(b[3] for b in bounds))
                            if x0 < x1 and y0 < y1:
                                page_blocks.append((block_index,
                                    ParsedBlock(
                                        page_index + 1,
                                        group_section,
                                        "\n".join(group).strip(),
                                        (x0, y0, x1, y1),
                                        width,
                                        height,
                                    )
                                ))
                            group.clear()
                            bounds.clear()

                    for line_index, _ in enumerate(block["lines"]):
                        key = (page_index, block_index, line_index)
                        line: LayoutLine | None = lookup.get(key)
                        if line is None:
                            continue
                        if key in headings:
                            flush()
                            current_section = headings[key]
                        section = current_section
                        if section and ABSTRACT.fullmatch(section) and not ABSTRACT.fullmatch(line.text):
                            if not line.horizontal:
                                section = None
                            elif (line.text.startswith(("∗", "*", "†", "‡"))
                                  or line.bbox[1] > height * .9
                                  or (abstract_region and line.size < abstract_region[2] * .92)):
                                current_section = section = None
                            elif abstract_region:
                                x0, x1, _ = abstract_region
                                overlap = max(0, min(x1, line.bbox[2]) - max(x0, line.bbox[0]))
                                if overlap < (line.bbox[2] - line.bbox[0]) * .5:
                                    section = following_heading
                        if group and group_section != section:
                            flush()
                        group_section = section
                        group.append(line.text)
                        bounds.append(line.bbox)
                    flush()
                blocks.extend(block for _, block in sorted(page_blocks, key=lambda entry: entry[0]))
            return ParsedPDF(page_count=document.page_count, blocks=blocks, **facts)
    except InvalidPDF:
        raise
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise InvalidPDF("PDF 文档损坏或无法解析") from error
