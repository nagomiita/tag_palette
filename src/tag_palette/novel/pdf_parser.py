"""Parse 'なろう' PDF novels into plain text with metadata.

Handles vertical (縦書き) Japanese PDF layout by reconstructing text
from character-level coordinates. Supports chapter-level splitting for
series registration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


@dataclass
class NovelPdf:
    """Parsed novel from a なろう PDF (single work, legacy)."""

    n_code: str
    title: str
    author: str
    description: str
    tags: list[str]
    body: str
    source_path: str
    url: str = ""
    is_sensitive: bool = False


@dataclass
class NovelPdfChapter:
    """A single chapter extracted from a なろう PDF."""

    title: str
    body: str
    seq: int


@dataclass
class NovelPdfSeries:
    """A なろう PDF parsed as a series with chapters."""

    n_code: str
    title: str
    author: str
    description: str
    url: str
    is_sensitive: bool
    chapters: list[NovelPdfChapter]
    source_path: str


_SENSITIVE_PATTERN = re.compile(r"18禁|R[\-\s]?18|Ｒ[\-\s]?１８")
_URL_PATTERN = re.compile(r"https?://[^\s　]+")

# Full-width -> half-width alphabet/digit translation table
_FULLWIDTH_TO_HALFWIDTH = str.maketrans(
    "０１２３４５６７８９"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz",
)

# Column grouping tolerance (pixels)
_COL_TOLERANCE = 5


def _check_sensitive(text: str) -> bool:
    """Check if text contains R18/18禁 markers."""
    return bool(_SENSITIVE_PATTERN.search(text))


def _extract_url(text: str) -> str:
    """Extract the first URL from text."""
    m = _URL_PATTERN.search(text)
    return m.group(0) if m else ""


# Columns with this many characters or more are considered layout wraps
# (not real line breaks) in vertical text. Determined empirically from
# なろう PDFs where one vertical line holds ~30 characters.
_FULL_LINE_THRESHOLD = 29


def _extract_vertical_text(
    page: pdfplumber.page.Page,
    *,
    join_lines: bool = True,
) -> str:
    """Extract text from a vertical (縦書き) PDF page.

    Groups characters by x-coordinate (columns), sorts columns
    right-to-left, characters top-to-bottom within each column.

    Args:
        join_lines: If True, full-length columns (>=29 chars) are joined
            without line breaks (layout wrap removal). If False, every
            column is separated by a newline (for metadata parsing).
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
    # Skip columns that are just page numbers
    parts: list[str] = []
    for col in cols:
        col.sort(key=lambda c: c["top"])
        line = "".join(c["text"] for c in col)
        if _is_page_number(line):
            continue
        parts.append(line)
        if not join_lines or len(line) < _FULL_LINE_THRESHOLD:
            parts.append("\n")

    return "".join(parts).strip()


def _detect_chapter_title(page: pdfplumber.page.Page) -> str | None:
    """Detect if a page starts with a bold chapter title.

    In なろう PDFs, chapter titles appear as bold text in the rightmost
    column (first column in vertical layout).

    Returns the chapter title string, or None if not a chapter start.
    """
    chars = [c for c in page.chars if c["text"].strip()]
    if not chars:
        return None

    # Find the rightmost column (highest x0 = first column in vertical text)
    max_x0 = max(c["x0"] for c in chars)
    first_col = [c for c in chars if abs(c["x0"] - max_x0) < _COL_TOLERANCE]
    first_col.sort(key=lambda c: c["top"])

    if not first_col:
        return None

    # Check if the first character in this column is Bold
    if "Bold" not in first_col[0].get("fontname", ""):
        return None

    # Collect all bold chars from the first column
    bold_text = "".join(
        c["text"] for c in first_col if "Bold" in c.get("fontname", "")
    )
    title = bold_text.strip()
    if not title:
        return None
    return title.translate(_FULLWIDTH_TO_HALFWIDTH)


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

    # Title (【作品タイトル】 or 【小説タイトル】)
    m = re.search(r"【(?:作品|小説)タイトル】\s*\n(.+?)(?=\n【)", info_text, re.DOTALL)
    if m:
        # Take only non-page-number lines (page numbers are standalone digits)
        title_lines = [
            line for line in m.group(1).strip().split("\n")
            if not re.fullmatch(r"\d{1,4}", line.strip())
        ]
        result["title"] = "".join(title_lines).strip().translate(_FULLWIDTH_TO_HALFWIDTH)

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
    """Parse a なろう PDF novel file (legacy single-novel mode).

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        NovelPdf with extracted metadata and body text.
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)

        # Page 1 (index 0) — cover page, check for R18 markers
        cover_text = pdf.pages[0].extract_text() or "" if total_pages > 0 else ""
        is_sensitive = _check_sensitive(cover_text)

        # Last page — extract URL (syosetu.com link)
        last_text = pdf.pages[-1].extract_text() or "" if total_pages > 0 else ""
        url = _extract_url(last_text)

        # Page 2 (index 1) contains metadata
        info_text = _extract_vertical_text(pdf.pages[1], join_lines=False) if total_pages > 1 else ""
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
        url=url,
        is_sensitive=is_sensitive,
    )


def parse_pdf_as_series(pdf_path: str | Path) -> NovelPdfSeries:
    """Parse a なろう PDF novel file as a series with chapters.

    Chapters are detected by bold text at the start of a page (rightmost
    column in vertical layout). Each chapter becomes a separate entry.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        NovelPdfSeries with metadata and chapter list.
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)

        # Page 1 (index 0) — cover page, check for R18 markers
        cover_text = pdf.pages[0].extract_text() or "" if total_pages > 0 else ""
        is_sensitive = _check_sensitive(cover_text)

        # Last page — extract URL (syosetu.com link)
        last_text = pdf.pages[-1].extract_text() or "" if total_pages > 0 else ""
        url = _extract_url(last_text)

        # Page 2 (index 1) contains metadata
        info_text = _extract_vertical_text(pdf.pages[1], join_lines=False) if total_pages > 1 else ""
        metadata = _parse_metadata(info_text)

        n_code = metadata.get("n_code", pdf_path.stem)
        title = metadata.get("title", pdf_path.stem)
        author = metadata.get("author", "")
        description = metadata.get("description", "")

        # Scan pages from page 3 onward, split by chapter boundaries
        # Each chapter boundary = bold title at rightmost column of a page
        chapters: list[NovelPdfChapter] = []
        current_title: str | None = None
        current_body_parts: list[str] = []
        chapter_seq = 0
        start_page = 2  # 0-indexed

        for i in range(start_page, total_pages):
            page = pdf.pages[i]

            # Skip 前書き/後書き header pages
            page_text = _extract_vertical_text(page)
            if not page_text or _is_chapter_header_page(page_text):
                continue

            # Check for chapter boundary
            chapter_title = _detect_chapter_title(page)
            if chapter_title:
                # Save previous chapter if exists
                if current_title is not None and current_body_parts:
                    chapter_seq += 1
                    chapters.append(NovelPdfChapter(
                        title=current_title,
                        body="\n".join(current_body_parts),
                        seq=chapter_seq,
                    ))
                # Discard any pages before the first chapter title
                current_body_parts = []
                current_title = chapter_title

            # Only collect body text after the first chapter title is found
            if current_title is None:
                continue

            cleaned = _clean_body_text(page_text)
            if cleaned.strip():
                current_body_parts.append(cleaned)

        # Save last chapter
        if current_title is not None and current_body_parts:
            chapter_seq += 1
            chapters.append(NovelPdfChapter(
                title=current_title,
                body="\n".join(current_body_parts),
                seq=chapter_seq,
            ))

    return NovelPdfSeries(
        n_code=n_code,
        title=title,
        author=author,
        description=description,
        url=url,
        is_sensitive=is_sensitive,
        chapters=chapters,
        source_path=str(pdf_path),
    )
