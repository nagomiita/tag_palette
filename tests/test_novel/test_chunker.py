"""Tests for chunk splitting logic."""

from tag_palette.novel.chunker import Chunk, chunk_text, split_by_kind


def test_split_dialogue():
    """「」で囲まれた部分がdialogueとして切り出されること。"""
    text = "地の文。「台詞だよ」また地の文。"
    segments = split_by_kind(text)
    assert segments[0] == ("narrative", "地の文。")
    assert segments[1] == ("dialogue", "「台詞だよ」")
    assert segments[2] == ("narrative", "また地の文。")


def test_split_thought():
    """()で囲まれた部分がthoughtとして切り出されること。"""
    text = "地の文。(心の声だ)また地の文。"
    segments = split_by_kind(text)
    assert segments[0] == ("narrative", "地の文。")
    assert segments[1] == ("thought", "(心の声だ)")
    assert segments[2] == ("narrative", "また地の文。")


def test_split_fullwidth_thought():
    """（）で囲まれた部分がthoughtとして切り出されること。"""
    text = "地の文。（心の声だ）また地の文。"
    segments = split_by_kind(text)
    assert segments[1] == ("thought", "（心の声だ）")


def test_split_mixed():
    """台詞・心の声・地の文が混在するテキストを正しく分割できること。"""
    text = '地の文。「台詞」さらに地の文。(心の声)最後。'
    segments = split_by_kind(text)
    kinds = [s[0] for s in segments]
    assert kinds == ["narrative", "dialogue", "narrative", "thought", "narrative"]


def test_chunk_text_seq():
    """seqが正しく振られること。"""
    text = "地の文。「台詞」また地の文。"
    chunks = chunk_text(text)
    seqs = [c.seq for c in chunks]
    assert seqs == list(range(len(chunks)))


def test_narrative_split_long():
    """500文字を超える地の文が分割されること。"""
    # 600文字の地の文（句点で区切れるように）
    sentence = "これはテスト文です。"  # 10文字
    text = sentence * 60  # 600文字
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.kind == "narrative"


def test_narrative_no_split_short():
    """500文字未満の地の文は分割されないこと。"""
    text = "短い地の文。"
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].kind == "narrative"
