"""PyMuPDF parser: original page coordinates, no OCR and no synthesized text."""

from __future__ import annotations
from dataclasses import dataclass
import re
import fitz


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
            title = (document.metadata.get("title") or "").strip() or None
            blocks: list[ParsedBlock] = []
            current_section: str | None = None
            for page_index, page in enumerate(document):
                # Canonical top-left coordinates relative to the unrotated CropBox.
                # PDF.js owns display rotation, including inverse selection transforms.
                rect = page.cropbox
                width, height = float(rect.width), float(rect.height)
                for block in page.get_text("dict", sort=True)["blocks"]:
                    if block.get("type") != 0:
                        continue
                    group: list[str] = []
                    bounds: list[tuple[float, float, float, float]] = []

                    def flush() -> None:
                        if group:
                            x0 = max(0.0, min(b[0] for b in bounds))
                            y0 = max(0.0, min(b[1] for b in bounds))
                            x1 = min(width, max(b[2] for b in bounds))
                            y1 = min(height, max(b[3] for b in bounds))
                            if x0 < x1 and y0 < y1:
                                blocks.append(
                                    ParsedBlock(
                                        page_index + 1,
                                        current_section,
                                        "\n".join(group).strip(),
                                        (x0, y0, x1, y1),
                                        width,
                                        height,
                                    )
                                )
                            group.clear()
                            bounds.clear()

                    for line in block["lines"]:
                        content = "".join(
                            span["text"] for span in line["spans"]
                        ).strip()
                        if not content:
                            continue
                        if (
                            title is None
                            and page_index == 0
                            and not blocks
                            and not group
                        ):
                            title = content[:500]
                        if HEADING.fullmatch(content):
                            flush()
                            current_section = content
                        group.append(content)
                        bounds.append(tuple(float(n) for n in line["bbox"]))
                    flush()
            return ParsedPDF(document.page_count, title, blocks)
    except InvalidPDF:
        raise
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise InvalidPDF("PDF 文档损坏或无法解析") from error
