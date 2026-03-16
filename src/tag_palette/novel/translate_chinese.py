"""Translate Chinese Pixiv novels to Japanese and save as Pixiv-format text files.

Pipeline:
  Pass 0: jieba word segmentation → extract frequent proper nouns (Python-side)
  Pass 1: LLM translates top-N terms into a Chinese→Japanese glossary
  Pass 2: Translate tags
  Pass 3: Translate body chunk-by-chunk with glossary + rolling summary

Usage:
    uv run python src/tag_palette/novel/translate_chinese.py <input_dir> [--output-dir <path>] [--model <name>] [--host <url>]
    uv run python src/tag_palette/novel/translate_chinese.py <input_dir> --dry-run
"""

from __future__ import annotations

import argparse
import io
import re as _re
import sys
import time
from collections import Counter
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import jieba.posseg as pseg
from ollama import Client

# =========================
# Settings
# =========================

DEFAULT_MODEL = "huihui_ai/qwen3.5-abliterated:9b"
DEFAULT_OUTPUT_DIR = Path("C:/Users/taket/Downloads/chinese_novels_translated")
DEFAULT_TEMPERATURE = 0.3
DEFAULT_NUM_CTX = 16384
DEFAULT_KEEP_ALIVE = "30m"

# Max characters per translation chunk
CHUNK_SIZE = 2000
# Max terms for glossary
TOP_N_TERMS = 50
# Rolling summary cap
MAX_SUMMARY_CHARS = 400

_THINK_RE = _re.compile(r"<think>.*?</think>\s*", flags=_re.DOTALL)
_SUMMARY_SPLIT_RE = _re.compile(r"\n\[要約\]\n?", flags=_re.IGNORECASE)

# POS tags for proper nouns in jieba
_PROPER_NOUN_POS = {"nr", "ns", "nt", "nz", "nrt"}

# Chinese stopwords to exclude from term extraction
_CN_STOPWORDS = {
    "自己", "什么", "时候", "地方", "东西", "这个", "那个", "一个", "所有",
    "已经", "现在", "这样", "那样", "可以", "因为", "但是", "如果", "虽然",
    "不过", "这里", "那里", "知道", "觉得", "开始", "以后", "之后", "然后",
    "还是", "或者", "一些", "一样", "一起", "一边", "一直", "只是", "就是",
    "不是", "没有", "时间", "事情", "样子", "感觉", "问题", "方面", "情况",
}

# Simplified Chinese chars rarely used in Japanese — for leak detection
_CN_ONLY_CHARS = _re.compile(r"[们这那还没对让从给跟着过来去说会能要想得]")


def _strip_think(text: str) -> str:
    """Remove <think>...</think> blocks from model output."""
    return _THINK_RE.sub("", text).strip()


# =========================
# File parsing
# =========================

def _parse_pixiv_txt(file_path: Path) -> dict:
    """Parse a Chinese Pixiv novel text file."""
    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    url = lines[0].strip() if len(lines) > 0 else ""
    author = lines[2].strip() if len(lines) > 2 else ""
    title = lines[4].strip() if len(lines) > 4 else ""
    tag_line = lines[6].strip() if len(lines) > 6 else ""

    tags: list[str] = []
    if tag_line.startswith("Tags:"):
        tags = [t.strip() for t in tag_line[5:].split(",") if t.strip()]
        body = "\n".join(lines[8:])
    else:
        body = "\n".join(lines[6:])

    return {
        "url": url,
        "author": author,
        "title": title,
        "tags": tags,
        "body": body,
        "novel_id": file_path.stem.split("_", 1)[0],
    }


def _split_paragraphs(body: str) -> list[str]:
    """Split body into paragraphs (non-empty lines)."""
    return [line for line in body.split("\n") if line.strip()]


def _group_paragraphs(paragraphs: list[str], max_chars: int = CHUNK_SIZE) -> list[str]:
    """Group paragraphs into chunks that fit within max_chars."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for p in paragraphs:
        if current_len + len(p) > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(p)
        current_len += len(p)

    if current:
        chunks.append("\n".join(current))

    return chunks


# =========================
# Pass 0: Python-side term extraction
# =========================

def _extract_frequent_terms(body: str, top_n: int = TOP_N_TERMS) -> list[tuple[str, int]]:
    """Extract frequent proper nouns from Chinese text using jieba POS tagging.

    Returns list of (word, frequency) sorted by frequency descending.
    """
    counter: Counter = Counter()

    for word, flag in pseg.cut(body):
        word = word.strip()
        if not word or len(word) < 2:
            continue
        if word in _CN_STOPWORDS:
            continue
        # Always include proper noun POS tags
        if flag in _PROPER_NOUN_POS:
            counter[word] += 1
        # Include general nouns only if frequent enough
        elif flag.startswith("n") and len(word) >= 2:
            counter[word] += 1

    # Filter general nouns by minimum frequency
    result = [
        (word, count) for word, count in counter.most_common(top_n * 2)
        if count >= 3 or any(
            flag in _PROPER_NOUN_POS
            for _, flag in pseg.cut(word)
        )
    ]

    return result[:top_n]


# =========================
# Pass 1: LLM glossary building
# =========================

def _build_glossary_via_llm(
    client: Client,
    model: str,
    terms: list[tuple[str, int]],
) -> str:
    """Send frequent terms to LLM and get Chinese→Japanese glossary."""
    terms_str = "\n".join(
        f"{i+1}. {word}（出現{count}回）" for i, (word, count) in enumerate(terms)
    )

    prompt = f"""以下は中国語小説に頻出する語のリストです。
各語を以下のルールで日本語に翻訳してください。

翻訳するもの:
- 人名 → カタカナ音訳（例: 艾莉丝 → アリス、娜塔莎 → ナターシャ）
- 地名・国名 → カタカナ音訳（例: 雪兰王国 → セツラン王国）
- 人を指す名詞・役職・呼称 → 日本語訳（例: 公主 → 王女、女仆 → 侍女、主人 → 主人、奴隶 → 奴隷、刑务官 → 看守）
- 作中の重要概念 → 日本語訳（例: 调教 → 調教、魅魔 → 魅魔、项圈 → 首輪）

翻訳しないもの（「-」と書く）:
- 身体部位（身体、双手、乳房、舌头、小穴 等）
- 一般動詞・形容詞（无法、明白、开口 等）
- 物体・場所（椅子、房间、地面、衣服 等）
- 感覚・状態（疼痛、触感、高潮 等）

形式:
- 各行は「中国語 → 日本語」または「中国語 → -」
- 1語につき1つの訳のみ
- 説明不要

{terms_str}"""

    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={
            "temperature": 0.1,
            "num_ctx": DEFAULT_NUM_CTX,
            "num_predict": 1024,
            "repeat_penalty": 1.3,
        },
        keep_alive=DEFAULT_KEEP_ALIVE,
        think=False,
    )

    raw = _strip_think(response.message.content)
    print(f"  [DEBUG] Raw glossary response ({len(raw)} chars):\n{raw[:500]}")
    # Parse only well-formed glossary lines: "中国語 → 日本語"
    lines = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Remove numbering prefix
        line = _re.sub(r"^\d+\.\s*", "", line)
        # Skip lines without arrow
        if "→" not in line:
            continue
        parts = line.split("→", 1)
        if len(parts) != 2:
            continue
        cn = parts[0].strip()
        ja_raw = parts[1].strip()
        # Skip "-" entries
        if ja_raw.startswith("-") or ja_raw.startswith("- ") or ja_raw == "-":
            continue
        # Take only the first word/phrase before any explanation
        # Cut at: （, (, ※, *, 。, space followed by non-katakana/kanji
        ja = _re.split(r"[（(※*。\s]", ja_raw)[0].strip()
        if not ja or ja == "-":
            continue
        # If multiple candidates with slash, take the first one
        if "/" in ja:
            ja = ja.split("/")[0].strip()
            if not ja:
                continue
        # Skip if still too long
        if len(ja) > 15:
            continue
        lines.append(f"{cn} → {ja}")
    return "\n".join(lines)


# =========================
# Pass 2: Tag translation
# =========================

def _translate_tags(client: Client, model: str, tags: list[str]) -> list[str]:
    """Translate Chinese tags to Japanese."""
    if not tags:
        return tags
    tags_str = ", ".join(tags)
    prompt = f"""以下の中国語のタグを日本語に翻訳してください。
カンマ区切りで、翻訳後のタグのみを出力してください。R-18などはそのまま残してください。

{tags_str}"""

    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "num_predict": 512},
        keep_alive=DEFAULT_KEEP_ALIVE,
        think=False,
    )
    result = _strip_think(response.message.content)
    return [t.strip() for t in result.split(",") if t.strip()]


# =========================
# Pass 3: Chunk translation with rolling summary
# =========================

def _parse_translation_response(response_text: str) -> tuple[str, str]:
    """Parse model output into (translation, summary)."""
    text = _strip_think(response_text)
    parts = _SUMMARY_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        translation = parts[0].strip()
        summary = parts[1].strip()
        # Cap summary length
        if len(summary) > MAX_SUMMARY_CHARS:
            truncated = summary[:MAX_SUMMARY_CHARS]
            last_period = max(
                truncated.rfind("。"),
                truncated.rfind("！"),
                truncated.rfind("？"),
            )
            summary = truncated[:last_period + 1] if last_period > 0 else truncated
        return translation, summary
    else:
        # Fallback: no summary marker found
        return text, ""


def _warn_chinese_leak(text: str, chunk_index: int) -> None:
    """Warn if translated text contains likely untranslated Chinese."""
    suspects = _CN_ONLY_CHARS.findall(text)
    if len(suspects) > 3:
        print(f"    WARNING: Chunk {chunk_index + 1} may contain untranslated Chinese "
              f"({len(suspects)} suspect chars)")


def _translate_chunk(
    client: Client,
    model: str,
    chunk: str,
    glossary: str,
    summary: str = "",
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> tuple[str, str]:
    """Translate a chunk with glossary and rolling summary.

    Returns (translated_text, updated_summary).
    """
    system = f"""あなたは中国語から日本語への小説翻訳の専門家です。ライトノベル風の自然な日本語に翻訳してください。

厳守ルール:
- 全文を日本語に翻訳してください。中国語を1文字も残さないでください
- 原文の内容を省略・検閲せず、忠実に翻訳してください
- 「」は台詞、（）は心の声として使ってください
- 段落の区切り（改行）は原文と同じにしてください
- 前回の翻訳と重複する文は出力しないでください

文体の指針:
- 硬い直訳ではなく、日本のライトノベルのような読みやすい文体にしてください
- 「体躯」→「身体」、「梳洗」→「身支度」のように、自然な日本語表現に意訳してください

以下の用語対応表に必ず従ってください（表にある語は必ず対応する日本語で統一）:
{glossary}

出力形式:
まず翻訳文を出力し、次に「[要約]」という行の後に、物語のここまでの要約を日本語で2〜3文で書いてください。
要約には現在の場面の登場人物・場所・直前の出来事を含めてください。"""

    user_content = ""
    if summary:
        user_content += f"【これまでのあらすじ】\n{summary}\n\n"
    user_content += f"【翻訳してください（{chunk_index + 1}/{total_chunks}）】\n{chunk}"

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    response = client.chat(
        model=model,
        messages=messages,
        options={
            "temperature": DEFAULT_TEMPERATURE,
            "num_ctx": DEFAULT_NUM_CTX,
            "num_predict": 4096,
        },
        keep_alive=DEFAULT_KEEP_ALIVE,
        think=False,
    )

    return _parse_translation_response(response.message.content)


# =========================
# Orchestration
# =========================

def _save_pixiv_format(
    output_path: Path,
    url: str,
    author: str,
    title: str,
    tags: list[str],
    body: str,
) -> None:
    """Save as Pixiv-format text file."""
    tag_line = f"Tags: {', '.join(tags)}" if tags else ""
    lines = [
        url,
        "",
        author,
        "",
        title,
        "",
        tag_line,
        "",
        body,
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def translate_file(
    client: Client,
    model: str,
    file_path: Path,
    output_dir: Path,
) -> dict:
    """Translate a single Chinese novel file to Japanese."""
    data = _parse_pixiv_txt(file_path)

    # Idempotency check
    output_name = f"{data['novel_id']}_{data['title']}.txt"
    output_path = output_dir / output_name
    if output_path.exists():
        return {"file": file_path.name, "skipped": True}

    paragraphs = _split_paragraphs(data["body"])
    if not paragraphs:
        return {"file": file_path.name, "skipped": True, "reason": "empty body"}

    # Pass 0: Python-side frequency analysis
    print("  [1/4] Analyzing word frequencies (jieba)...")
    frequent_terms = _extract_frequent_terms(data["body"], top_n=TOP_N_TERMS)
    print(f"  Found {len(frequent_terms)} candidate terms")
    for word, count in frequent_terms[:10]:
        print(f"    {word} ({count})")

    # Pass 1: LLM glossary from frequent terms
    print("  [2/4] Building glossary via LLM...")
    if frequent_terms:
        glossary = _build_glossary_via_llm(client, model, frequent_terms)
    else:
        glossary = ""
    print(f"  Glossary:\n{glossary}")

    # Pass 2: Translate tags
    print("  [3/4] Translating tags...")
    ja_tags = _translate_tags(client, model, data["tags"])
    print(f"  Tags: {', '.join(ja_tags)}")

    # Pass 3: Translate body with rolling summary
    chunks = _group_paragraphs(paragraphs)
    print(f"  [4/4] Translating body ({len(chunks)} chunks)...")

    translated_parts: list[str] = []
    summary = ""

    for i, chunk in enumerate(chunks):
        t0 = time.time()
        translated, summary = _translate_chunk(
            client, model, chunk, glossary,
            summary=summary,
            chunk_index=i,
            total_chunks=len(chunks),
        )
        elapsed = time.time() - t0
        translated_parts.append(translated)
        _warn_chinese_leak(translated, i)
        print(f"    [{i + 1}/{len(chunks)}] {len(chunk)}ch -> {len(translated)}ch ({elapsed:.1f}s)")
        if summary:
            print(f"    Summary: {summary[:80]}...")

    translated_body = "\n\n".join(translated_parts)

    # Translate title
    title_resp = client.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": f"以下の中国語の小説タイトルを日本語に翻訳してください。翻訳のみ出力:\n{data['title']}",
        }],
        options={"temperature": 0.1, "num_predict": 128},
        keep_alive=DEFAULT_KEEP_ALIVE,
        think=False,
    )
    ja_title = _strip_think(title_resp.message.content)

    # Save
    output_dir.mkdir(parents=True, exist_ok=True)
    _save_pixiv_format(
        output_path,
        url=data["url"],
        author=data["author"],
        title=ja_title,
        tags=ja_tags,
        body=translated_body,
    )

    return {
        "file": file_path.name,
        "title": ja_title,
        "original_title": data["title"],
        "chunks": len(chunks),
        "output": str(output_path),
        "skipped": False,
    }


# =========================
# CLI
# =========================

def main() -> None:
    parser = argparse.ArgumentParser(description="Translate Chinese Pixiv novels to Japanese")
    parser.add_argument(
        "input_dir", type=Path,
        help="Directory containing Chinese novel .txt files",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for translated files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--model", type=str, default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--host", type=str, default=None,
        help="Ollama host URL (e.g. http://gpu-ollama:11434). Default: local",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Not a directory: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(args.input_dir.glob("*.txt"))
    host_display = args.host or "localhost"
    print(f"Input:  {args.input_dir}")
    print(f"Output: {args.output_dir}")
    print(f"Model:  {args.model}")
    print(f"Host:   {host_display}")
    print(f"Files:  {len(files)}")

    if args.dry_run:
        for f in files:
            data = _parse_pixiv_txt(f)
            terms = _extract_frequent_terms(data["body"], top_n=10)
            terms_str = ", ".join(f"{w}({c})" for w, c in terms[:5])
            print(f"  {data['novel_id']} {data['title']} ({len(data['body'])} chars) top: {terms_str}")
        return

    client = Client(host=args.host, timeout=600) if args.host else Client(timeout=600)
    results = []

    for i, f in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {f.name}")
        t0 = time.time()
        result = translate_file(client, args.model, f, args.output_dir)
        elapsed = time.time() - t0

        if result.get("skipped"):
            print(f"  SKIP ({result.get('reason', 'already exists')})")
        else:
            print(f"  -> {result['title']} ({elapsed:.0f}s)")
            print(f"  Saved: {result['output']}")
        results.append(result)

    print(f"\n{'=' * 50}")
    translated = [r for r in results if not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]
    print(f"Done: {len(translated)} translated, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
