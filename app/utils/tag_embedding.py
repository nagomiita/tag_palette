import numpy as np
import spacy
import torch
from sentence_transformers import SentenceTransformer
from spacy.cli import download
from spacy.util import is_package

SPACY_MODEL = "en_core_web_sm"

# # モデルが未インストールならダウンロード
if not is_package(SPACY_MODEL):
    print(f"[INFO] downloading spaCy model: {SPACY_MODEL}")
    download(SPACY_MODEL)

# ロード
spacy_nlp = spacy.load(SPACY_MODEL)
device = "cuda" if torch.cuda.is_available() else "cpu"
sentence_model = SentenceTransformer("stsb-xlm-r-multilingual").to(device)


def extract_nouns_en(text: str) -> str:
    """英文から名詞・固有名詞だけを抽出"""
    doc = spacy_nlp(text)
    nouns = [token.text for token in doc if token.pos_ in ["NOUN", "PROPN"]]
    return " ".join(nouns)


def tag_result_to_embedding(tag_result: dict[str, float]) -> np.ndarray:
    """
    TagResult から埋め込みベクトルを生成
    - タグ名のみ使う
    - 英語タグ名を前提とし、名詞のみで構成された文にしてからエンコード
    """
    tag_names = list(tag_result.keys())  # e.g. ['1girl', 'long_hair']
    tag_text = " ".join(tag_names)
    # tag_text = extract_nouns_en(tag_text)

    embedding = sentence_model.encode(
        tag_text,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    return embedding
