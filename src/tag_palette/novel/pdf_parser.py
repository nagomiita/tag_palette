"""Parse 'なろう' PDF novels into plain text with metadata.

Handles vertical (縦書き) Japanese PDF layout by reconstructing text
from character-level coordinates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber


@dataclass
class NovelPdf:
    """Parsed novel from a なろう PDF."""

    n_code: str
    title: str
    author: str
    description: str
    tags: list[str]
    body: str
    source_path: str


# Column grouping tolerance (pixels)
_COL_TOLERANCE = 5


def _extract_vertical_text(page: pdfplumber.page.Page) -> str:
    """Extract text from a vertical (縦書き) PDF page.

    Groups characters by x-coordinate (columns), sorts columns
    right-to-left, characters top-to-bottom within each column.
    """
    chars = [c for c in page.chars if c["text"].strip()]
    if not chars:
        return ""

    # Group by x0 (column)
    chars_sorted = sorted(chars, key=lambda c: -c["x0"])  # right to left
    cols: list[list[dict]] = []
    current_col = [chars_sorted[0]]

    for c in chars_sorted[1:]:
        if abs(c["x0"] - current_col[0]["x0"]) < _COL_TOLERANCE:
            current_col.append(c)
        else:
            cols.append(current_col)
            current_col = [c]
    cols.append(current_col)

    # Sort each column top-to-bottom, join chars
    lines = []
    for col in cols:
        col.sort(key=lambda c: c["top"])
        line = "".join(c["text"] for c in col)
        lines.append(line)

    return "\n".join(lines)


def _parse_metadata(info_text: str) -> dict[str, str]:
    """Parse metadata from the info page (usually page 2).

    Expected format:
        【作品タイトル】
        Title text
        【Ｎコード】
        N0510HD
        【作者名】
        Author name
        【あらすじ】
        Description text
    """
    result: dict[str, str] = {}

    # Title
    m = re.search(r"【作品タイトル】\s*\n(.+?)(?=\n【)", info_text, re.DOTALL)
    if m:
        result["title"] = m.group(1).strip().replace("\n", "")

    # N-code — find the line starting with Ｎ between 【Ｎコード】 and next 【
    m = re.search(r"【Ｎコード】\s*\n(.+?)(?=\n【)", info_text, re.DOTALL)
    if m:
        # Extract only the line that starts with Ｎ (skip page numbers etc.)
        for line in m.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith("Ｎ") or line.startswith("N"):
                raw = line
                # Normalize fullwidth to halfwidth
                result["n_code"] = raw.translate(
                    str.maketrans("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ",
                                  "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                ).replace("Ｎ", "N")
                break

    # Author
    m = re.search(r"【作者名】\s*\n(.+?)(?=\n【)", info_text, re.DOTALL)
    if m:
        result["author"] = m.group(1).strip().replace("\n", "")

    # Description (あらすじ) - goes to end of text
    m = re.search(r"【あらすじ】\s*\n(.+)", info_text, re.DOTALL)
    if m:
        result["description"] = m.group(1).strip()

    return result


def _is_chapter_header_page(text: str) -> bool:
    """Check if a page is a chapter header (前書き/後書き marker or very short)."""
    if not text:
        return True
    # Short pages with (前書き) or (後書き)
    if "（前書き）" in text or "（後書き）" in text:
        return True
    return False


def _is_page_number(line: str) -> bool:
    """Check if a line is just a page number."""
    return bool(re.fullmatch(r"\d{1,4}", line.strip()))


def _clean_body_text(text: str) -> str:
    """Remove page numbers and clean up body text."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if _is_page_number(line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def parse_pdf(pdf_path: str | Path) -> NovelPdf:
    """Parse a なろう PDF novel file.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        NovelPdf with extracted metadata and body text.
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)

        # Page 2 (index 1) contains metadata
        info_text = _extract_vertical_text(pdf.pages[1]) if total_pages > 1 else ""
        metadata = _parse_metadata(info_text)

        n_code = metadata.get("n_code", pdf_path.stem)
        title = metadata.get("title", pdf_path.stem)
        author = metadata.get("author", "")
        description = metadata.get("description", "")

        # Extract body text from page 3 onward (skip cover + info + notes)
        body_parts: list[str] = []
        start_page = 2  # 0-indexed, skip cover(0) and info(1)

        for i in range(start_page, total_pages):
            page_text = _extract_vertical_text(pdf.pages[i])
            if not page_text:
                continue

            # Skip 前書き/後書き header pages
            if _is_chapter_header_page(page_text):
                continue

            cleaned = _clean_body_text(page_text)
            if cleaned.strip():
                body_parts.append(cleaned)

    body = "\n".join(body_parts)

    return NovelPdf(
        n_code=n_code,
        title=title,
        author=author,
        description=description,
        tags=[],  # なろう PDFs don't include tags
        body=body,
        source_path=str(pdf_path),
    )
