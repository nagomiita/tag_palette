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


def _is_page_number_char(char: dict, page_height: float) -> bool:
    """Check if a character is part of a page number.

    In なろう PDFs, page numbers are rendered as halfwidth ASCII digits
    at a fixed vertical position near the bottom of the page (~89%).
    Body text uses fullwidth digits, so filtering halfwidth digits in
    the bottom area safely removes only page numbers.
    """
    return (
        char["text"].isascii()
        and char["text"].isdigit()
        and char["top"] > page_height * 0.85
    )


def _estimate_body_font_size(chars: list[dict]) -> float:
    """Estimate the dominant (body) font size from character list.

    Returns the most frequent font size, which corresponds to body text.
    Furigana uses a noticeably smaller size.
    """
    from collections import Counter
    sizes = Counter(round(c["size"], 1) for c in chars)
    return sizes.most_common(1)[0][0]


# Furigana is typically ~50% of body font size; reject chars below this ratio
_FURIGANA_SIZE_RATIO = 0.75


def _extract_vertical_text(
    page: pdfplumber.page.Page,
    *,
    join_lines: bool = True,
) -> str:
    """Extract text from a vertical (縦書き) PDF page.

    Groups characters by x-coordinate (columns), sorts columns
    right-to-left, characters top-to-bottom within each column.
    Filters out furigana (ruby) characters by font size.

    Args:
        join_lines: If True, full-length columns (>=29 chars) are joined
            without line breaks (layout wrap removal). If False, every
            column is separated by a newline (for metadata parsing).
    """
    chars = [
        c for c in page.chars
        if c["text"].strip() and not _is_page_number_char(c, page.height)
    ]
    if not chars:
        return ""

    # Filter out furigana (small font size characters)
    body_size = _estimate_body_font_size(chars)
    min_size = body_size * _FURIGANA_SIZE_RATIO
    chars = [c for c in chars if c["size"] >= min_size]
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

    # Sort each column top-to-bottom
    for col in cols:
        col.sort(key=lambda c: c["top"])

    # The body text's vertical extent on this page anchors what "full"
    # means: a column whose last char reaches the body bottom is a layout
    # wrap (continuation); a column ending well above it is a paragraph
    # break. This complements the character-count heuristic, which is
    # brittle because per-PDF column capacities vary (28 vs 29 vs 30).
    body_top = min(c["top"] for c in chars)
    body_bottom = max(c["bottom"] for c in chars)
    body_height = body_bottom - body_top
    height_tolerance = body_height * 0.05
    use_height_check = body_height > page.height * 0.4

    # Join chars; skip columns that are just page numbers
    parts: list[str] = []
    for col in cols:
        line = "".join(c["text"] for c in col)
        if _is_page_number(line):
            continue
        parts.append(line)
        last_bottom = col[-1]["bottom"]
        is_full = (
            len(line) >= _FULL_LINE_THRESHOLD
            or (use_height_check and (body_bottom - last_bottom) <= height_tolerance)
        )
        if not join_lines or not is_full:
            parts.append("\n")

    # Don't strip trailing "\n": its presence/absence encodes whether the
    # last column ended with a paragraph break (short column) vs a layout
    # wrap (full column). Callers concatenate pages and rely on this to
    # avoid inserting spurious line breaks across page boundaries when a
    # sentence spans pages.
    return _normalize_vertical_punct(_decode_cid_artifacts("".join(parts).lstrip()))


def _detect_chapter_title(page: pdfplumber.page.Page) -> str | None:
    """Detect if a page starts with a bold chapter title.

    In なろう PDFs, chapter titles appear as bold text in the rightmost
    column of vertical layout. Long titles can spill into the next
    column(s) to the left; each contiguous bold-leading column is
    treated as part of the title until a non-bold column is hit.

    Returns the chapter title string, or None if not a chapter start.
    """
    chars = [c for c in page.chars if c["text"].strip()]
    if not chars:
        return None

    # Group chars into columns, right-to-left.
    chars_sorted = sorted(chars, key=lambda c: -c["x0"])
    cols: list[list[dict]] = []
    current_col = [chars_sorted[0]]
    for c in chars_sorted[1:]:
        if abs(c["x0"] - current_col[0]["x0"]) < _COL_TOLERANCE:
            current_col.append(c)
        else:
            cols.append(current_col)
            current_col = [c]
    cols.append(current_col)
    for col in cols:
        col.sort(key=lambda c: c["top"])

    # The page is only a chapter start if the rightmost column begins with bold.
    if not _is_bold_font(cols[0][0].get("fontname", "")):
        return None

    # Walk left, accumulating bold chars from each column until we hit a
    # column whose first character is not bold (= start of body text).
    title_parts: list[str] = []
    for col in cols:
        if not _is_bold_font(col[0].get("fontname", "")):
            break
        bold_text = "".join(
            c["text"] for c in col if _is_bold_font(c.get("fontname", ""))
        )
        if not bold_text:
            break
        title_parts.append(bold_text)

    title = "".join(title_parts).strip()
    if not title:
        return None
    return _normalize_vertical_punct(title).translate(_FULLWIDTH_TO_HALFWIDTH)


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


_COLOPHON_PATTERN = re.compile(
    r"syosetu\.com|ncode\.|小説家になろう|ご覧ください|この作品の詳細",
    re.IGNORECASE,
)


def _is_colophon_page(text: str) -> bool:
    """Check if a page is a colophon (奥付) page."""
    if not text:
        return False
    return bool(_COLOPHON_PATTERN.search(text))


def _is_page_number(line: str) -> bool:
    """Check if a line is just a page number.

    Only halfwidth ASCII digits are page numbers — fullwidth digits like
    `２` are body content (chapter section markers, dates, etc.) and must
    not be filtered.
    """
    return bool(re.fullmatch(r"[0-9]{1,4}", line.strip()))


_BOLD_WEIGHT_RE = re.compile(r"W[6-9]")

# Some PDFs embed fonts whose ToUnicode CMap doesn't cover every CID — most
# commonly small kana and vertical-presentation forms. pdfplumber surfaces
# those as literal `(cid:N)` strings, which then break downstream tokenization
# (the chunker matches `(...)` as inner-thought). Mappings below were derived
# from contextual evidence in observed Hiragino Sans PDFs (Adobe-Japan1
# encoding); unknown CIDs are dropped so at least no `(cid:N)` artifacts
# remain in body text or chunks.
_CID_PATTERN = re.compile(r"\(cid:(\d+)\)")
_KNOWN_CIDS: dict[int, str] = {
    7891: "ー",  # ワンピース, グループ, ピース
    7918: "あ",  # まあ, ああ
    7920: "う",  # うう
    7923: "っ",  # 早朝だった, なかった (most common)
    7924: "ゃ",  # じゃない, じゃあ
    7926: "ょ",  # でしょう, ちょっと
    7928: "ァ",  # ファスナー
    7933: "ッ",  # ピッタリ, スッ, ネット
    7934: "ャ",  # キャンバス, Tシャツ
    7935: "ュ",  # メニュー
}


def _decode_cid_artifacts(text: str) -> str:
    """Replace `(cid:N)` artifacts in extracted text.

    Maps known CIDs to their Unicode equivalents and drops unknown ones.
    Leaving the literal `(cid:N)` strings intact would otherwise be picked
    up by the chunker's parenthesis-based inner-thought regex.
    """
    if "(cid:" not in text:
        return text
    return _CID_PATTERN.sub(
        lambda m: _KNOWN_CIDS.get(int(m.group(1)), ""), text,
    )


# Some PDF generators embed Unicode "Presentation Forms for Vertical" (U+FE10
# block, plus a handful of CJK Compatibility Forms) instead of the regular
# horizontal punctuation. They render correctly inside the original vertical
# layout but look wrong when extracted as horizontal text — and, critically,
# break the chunker's dialogue regex which only matches 「/」/『/』. Normalize
# them back to standard forms.
_VERTICAL_TO_HORIZONTAL = str.maketrans({
    "︑": "、",  # ideographic comma
    "︒": "。",  # ideographic full stop
    "︐": "，",  # comma
    "︕": "！",  # exclamation
    "︖": "？",  # question
    "﹁": "「",  # left corner bracket
    "﹂": "」",  # right corner bracket
    "﹃": "『",  # left white corner bracket
    "﹄": "』",  # right white corner bracket
    "︵": "（",  # left parenthesis
    "︶": "）",  # right parenthesis
    "︻": "【",  # left lenticular
    "︼": "】",  # right lenticular
    "︽": "《",  # left double angle
    "︾": "》",  # right double angle
    "︿": "〈",  # left angle
    "﹀": "〉",  # right angle
    "︗": "〘",  # left tortoise shell
    "︘": "〙",  # right tortoise shell
    "﹇": "［",  # left square
    "﹈": "］",  # right square
    "︱": "―",  # em dash
    "︲": "‐",  # hyphen
    "︙": "…",  # vertical ellipsis → horizontal ellipsis
})


def _normalize_vertical_punct(text: str) -> str:
    """Translate vertical-presentation-form punctuation to standard forms."""
    return text.translate(_VERTICAL_TO_HORIZONTAL)


def _is_bold_font(fontname: str) -> bool:
    """Detect bold/heavy weight from a font name.

    Covers `MS-Mincho,Bold` (なろう PDFs) and `HiraginoSans-W6/W7/...`
    style heavy-weight notations used by other PDF generators.
    """
    if not fontname:
        return False
    if "Bold" in fontname:
        return True
    return bool(_BOLD_WEIGHT_RE.search(fontname))


def _clean_body_text(text: str) -> str:
    """Remove page numbers and clean up body text."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if _is_page_number(line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


# Sentence terminators that indicate the description has ended naturally.
_SENTENCE_TERMINATORS = "。！？）」』"

# Continuation pages of あらすじ are typically a few short columns;
# a full body page is ~600+ chars in vertical layout. Anything longer than
# this is treated as body content rather than description overflow.
_INFO_CONTINUATION_MAX_CHARS = 300


def _extract_info_text(pdf: pdfplumber.PDF) -> tuple[str, int]:
    """Extract metadata text from the info page and any あらすじ overflow pages.

    The info page (index 1) holds 【作品タイトル】, 【Ｎコード】, 【作者名】,
    and 【あらすじ】. When the あらすじ runs long it spills onto the next page
    with no bracketed markers, which the regex-based metadata parser would
    otherwise miss — and the body extractor would then treat as story text.

    Returns:
        (info_text, body_start) where body_start is the 0-indexed page from
        which body extraction should begin (always >= 2).
    """
    if len(pdf.pages) < 2:
        return "", 1

    info_text = _extract_vertical_text(pdf.pages[1], join_lines=False)
    body_start = 2

    if "【あらすじ】" not in info_text:
        return info_text, body_start

    desc_so_far = info_text.split("【あらすじ】", 1)[1].strip()
    if desc_so_far and desc_so_far[-1] in _SENTENCE_TERMINATORS:
        return info_text, body_start

    # Description was cut off mid-sentence — collect overflow pages until we
    # hit either a sentence terminator or a clear non-description boundary.
    last_page = len(pdf.pages) - 1
    for i in range(2, last_page):
        page = pdf.pages[i]
        page_text = _extract_vertical_text(page, join_lines=False)
        if not page_text:
            break
        if "【" in page_text:
            break
        if _is_chapter_header_page(page_text) or _is_colophon_page(page_text):
            break
        if _detect_chapter_title(page):
            break
        if len(page_text) > _INFO_CONTINUATION_MAX_CHARS:
            break

        # No explicit separator: with join_lines=False every column already
        # ends with "\n", so the previous page's tail and the next page's
        # head are already joined by a single newline.
        info_text += page_text
        body_start = i + 1

        stripped = page_text.strip()
        if stripped and stripped[-1] in _SENTENCE_TERMINATORS:
            break

    return info_text, body_start


def _is_naro_pdf(pdf: pdfplumber.PDF) -> bool:
    """Detect a なろう (pdfnovels.net-generated) PDF.

    なろう PDFs always carry a structured info page at index 1 with
    bracketed metadata sections (【小説タイトル】 / 【作品タイトル】).
    Other PDFs that happen to use vertical Japanese layout — e.g.
    handcrafted ones with no front matter — lack these markers and
    need a different parsing strategy.
    """
    if len(pdf.pages) < 2:
        return False
    info_text = _extract_vertical_text(pdf.pages[1], join_lines=False)
    return "【小説タイトル】" in info_text or "【作品タイトル】" in info_text


def _group_page_columns(page: pdfplumber.page.Page) -> list[list[dict]]:
    """Group a page's chars into vertical columns sorted right-to-left.

    Each column is sorted top-to-bottom. Page numbers and furigana are
    filtered out, mirroring `_extract_vertical_text`.
    """
    chars = [
        c for c in page.chars
        if c["text"].strip() and not _is_page_number_char(c, page.height)
    ]
    if not chars:
        return []
    body_size = _estimate_body_font_size(chars)
    chars = [c for c in chars if c["size"] >= body_size * _FURIGANA_SIZE_RATIO]
    if not chars:
        return []
    chars_sorted = sorted(chars, key=lambda c: -c["x0"])
    cols: list[list[dict]] = []
    current_col = [chars_sorted[0]]
    for c in chars_sorted[1:]:
        if abs(c["x0"] - current_col[0]["x0"]) < _COL_TOLERANCE:
            current_col.append(c)
        else:
            cols.append(current_col)
            current_col = [c]
    cols.append(current_col)
    for col in cols:
        col.sort(key=lambda c: c["top"])
    return cols


def _column_text_with_break(
    col: list[dict],
    *,
    body_bottom: float,
    body_height: float,
    page_height: float,
) -> str:
    """Render a single column to text, appending `\\n` if the column was
    short (= a paragraph break, not a layout wrap).

    Skips columns that are nothing but a page number. Returns "" for
    those, so the caller can drop them transparently.
    """
    line = "".join(c["text"] for c in col)
    if _is_page_number(line):
        return ""
    line = _normalize_vertical_punct(_decode_cid_artifacts(line))
    last_bottom = col[-1]["bottom"]
    height_tolerance = body_height * 0.05
    use_height_check = body_height > page_height * 0.4
    is_full = (
        len(line) >= _FULL_LINE_THRESHOLD
        or (use_height_check and (body_bottom - last_bottom) <= height_tolerance)
    )
    return line if is_full else line + "\n"


def _parse_misc_pdf_as_series(
    pdf: pdfplumber.PDF,
    pdf_path: Path,
) -> NovelPdfSeries:
    """Parse a non-なろう vertical-Japanese PDF as a chapter series.

    Format assumptions (differs from なろう):
      - No front-matter info page; title falls back to file stem.
      - Each chapter title appears as one or more consecutive bold-weight
        columns. The title may sit anywhere within a page (not just the
        rightmost column), so chapter breaks can occur mid-page: columns
        before the title belong to the previous chapter, columns after
        belong to the new one.
      - No colophon/URL on the last page.
    """
    chapters: list[NovelPdfChapter] = []
    current_title: str | None = None
    current_body_parts: list[str] = []
    chapter_seq = 0

    cover_text = pdf.pages[0].extract_text() or "" if pdf.pages else ""
    is_sensitive = _check_sensitive(cover_text)

    for page_idx in range(len(pdf.pages)):
        page = pdf.pages[page_idx]
        cols = _group_page_columns(page)
        if not cols:
            continue
        all_chars = [c for col in cols for c in col]
        body_top = min(c["top"] for c in all_chars)
        body_bottom = max(c["bottom"] for c in all_chars)
        body_height = body_bottom - body_top

        col_idx = 0
        n = len(cols)
        while col_idx < n:
            col = cols[col_idx]
            first_font = col[0].get("fontname", "")
            if _is_bold_font(first_font):
                # Chapter title: gather consecutive bold-leading columns
                # (long titles can wrap into the next column to the left).
                title_parts: list[str] = []
                while col_idx < n and _is_bold_font(cols[col_idx][0].get("fontname", "")):
                    bold_text = "".join(
                        c["text"] for c in cols[col_idx]
                        if _is_bold_font(c.get("fontname", ""))
                    )
                    if not bold_text:
                        break
                    title_parts.append(bold_text)
                    col_idx += 1
                title = _normalize_vertical_punct(
                    "".join(title_parts).strip()
                ).translate(_FULLWIDTH_TO_HALFWIDTH)
                if not title:
                    continue
                # Save previous chapter
                if current_title is not None and current_body_parts:
                    chapter_seq += 1
                    chapters.append(NovelPdfChapter(
                        title=current_title,
                        body="".join(current_body_parts),
                        seq=chapter_seq,
                    ))
                current_title = title
                current_body_parts = []
            else:
                # Body column — append to the current chapter (skip until
                # the first chapter title appears).
                if current_title is not None:
                    text = _column_text_with_break(
                        col,
                        body_bottom=body_bottom,
                        body_height=body_height,
                        page_height=page.height,
                    )
                    if text.strip():
                        current_body_parts.append(text)
                col_idx += 1

    if current_title is not None and current_body_parts:
        chapter_seq += 1
        chapters.append(NovelPdfChapter(
            title=current_title,
            body="".join(current_body_parts),
            seq=chapter_seq,
        ))

    return NovelPdfSeries(
        n_code=pdf_path.stem,
        title=pdf_path.stem,
        author="",
        description="",
        url="",
        is_sensitive=is_sensitive,
        chapters=chapters,
        source_path=str(pdf_path),
    )


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

        # Page 2 (index 1) — and any あらすじ overflow pages — contain metadata
        info_text, start_page = _extract_info_text(pdf)
        metadata = _parse_metadata(info_text)

        n_code = metadata.get("n_code", pdf_path.stem)
        title = metadata.get("title", pdf_path.stem)
        author = metadata.get("author", "")
        description = metadata.get("description", "")

        # Extract body text after the info page(s) (skip cover, info, and last page)
        body_parts: list[str] = []
        end_page = total_pages - 1  # skip last page (colophon/URL)

        for i in range(start_page, end_page):
            page_text = _extract_vertical_text(pdf.pages[i])
            if not page_text:
                continue

            # Skip 前書き/後書き header pages and colophon (奥付) pages
            if _is_chapter_header_page(page_text) or _is_colophon_page(page_text):
                continue

            cleaned = _clean_body_text(page_text)
            if cleaned.strip():
                body_parts.append(cleaned)

    # Concatenate without an extra "\n": each page text already carries its
    # trailing-newline state, so a sentence that wraps a page boundary stays
    # joined while a paragraph-break-ended page keeps its newline.
    body = "".join(body_parts)

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
    """Parse a vertical-Japanese PDF novel as a series with chapters.

    Dispatches between two formats:
      - なろう (pdfnovels.net): structured info page at index 1, chapter
        title in the rightmost column of a page.
      - Misc: no info page, chapter title is any bold-weight column on a
        page (may sit mid-page, splitting it across two chapters).

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        NovelPdfSeries with metadata and chapter list.
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(str(pdf_path)) as pdf:
        if not _is_naro_pdf(pdf):
            return _parse_misc_pdf_as_series(pdf, pdf_path)

        total_pages = len(pdf.pages)

        # Page 1 (index 0) — cover page, check for R18 markers
        cover_text = pdf.pages[0].extract_text() or "" if total_pages > 0 else ""
        is_sensitive = _check_sensitive(cover_text)

        # Last page — extract URL (syosetu.com link)
        last_text = pdf.pages[-1].extract_text() or "" if total_pages > 0 else ""
        url = _extract_url(last_text)

        # Page 2 (index 1) — and any あらすじ overflow pages — contain metadata
        info_text, start_page = _extract_info_text(pdf)
        metadata = _parse_metadata(info_text)

        n_code = metadata.get("n_code", pdf_path.stem)
        title = metadata.get("title", pdf_path.stem)
        author = metadata.get("author", "")
        description = metadata.get("description", "")

        # Scan pages after the info page(s), split by chapter boundaries.
        # Each chapter boundary = bold title at rightmost column of a page.
        chapters: list[NovelPdfChapter] = []
        current_title: str | None = None
        current_body_parts: list[str] = []
        chapter_seq = 0
        end_page = total_pages - 1  # skip last page (colophon/URL)

        for i in range(start_page, end_page):
            page = pdf.pages[i]

            # Skip 前書き/後書き header pages and colophon (奥付) pages
            page_text = _extract_vertical_text(page)
            if not page_text or _is_chapter_header_page(page_text) or _is_colophon_page(page_text):
                continue

            # Check for chapter boundary
            chapter_title = _detect_chapter_title(page)
            if chapter_title:
                # Save previous chapter if exists
                if current_title is not None and current_body_parts:
                    chapter_seq += 1
                    chapters.append(NovelPdfChapter(
                        title=current_title,
                        body="".join(current_body_parts),
                        seq=chapter_seq,
                    ))
                # Discard any pages before the first chapter title
                current_body_parts = []
                current_title = chapter_title

            # Only collect body text after the first chapter title is found
            if current_title is None:
                continue

            cleaned = _clean_body_text(page_text)
            if chapter_title and cleaned:
                # The chapter title occupies the rightmost column on this
                # page and ends up at the start of page_text. It's already
                # captured separately as `chapter.title`, so strip it here
                # to avoid duplicating it in `chapter.body`. Compare in
                # halfwidth form because `_detect_chapter_title` translates
                # the title but body text retains fullwidth digits/letters.
                title_len = len(chapter_title)
                leading = cleaned[:title_len].translate(_FULLWIDTH_TO_HALFWIDTH)
                if leading == chapter_title:
                    cleaned = cleaned[title_len:].lstrip("\n")
            if cleaned.strip():
                current_body_parts.append(cleaned)

        # Save last chapter
        if current_title is not None and current_body_parts:
            chapter_seq += 1
            chapters.append(NovelPdfChapter(
                title=current_title,
                body="".join(current_body_parts),
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
