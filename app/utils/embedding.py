import numpy as np

# import spacy
import torch
from db.query import (
    add_tag_embedding,
    get_image_tag_embedding,
    get_tag_embedding,
    load_all_image_tag_embedding,
)
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# from spacy.cli import download
# from spacy.util import is_package

# SPACY_MODEL = "en_core_web_sm"

# # モデルが未インストールならダウンロード
# if not is_package(SPACY_MODEL):
#     print(f"[INFO] downloading spaCy model: {SPACY_MODEL}")
#     download(SPACY_MODEL)

# ロード
# spacy_nlp = spacy.load(SPACY_MODEL)
device = "cuda" if torch.cuda.is_available() else "cpu"
sentence_model = SentenceTransformer("paraphrase-MiniLM-L6-v2").to("cpu")


# def extract_nouns_en(text: str) -> str:
#     """英文から名詞・固有名詞だけを抽出"""
#     doc = spacy_nlp(text)
#     nouns = [token.text for token in doc if token.pos_ in ["NOUN", "PROPN"]]
#     return " ".join(nouns)


def tag_result_to_embedding(tag_result: dict[str, float]) -> np.ndarray:
    tag_names = list(tag_result.keys())
    weights = np.array([tag_result[tag] for tag in tag_names])
    vectors = []

    missing_tags = []
    missing_indices = []

    # 1. 既存のベクトルを探す（順序を崩さず）
    for i, tag in enumerate(tag_names):
        emb = get_tag_embedding(tag)
        if emb is not None and emb.size > 0:
            vectors.append(emb * weights[i])
        else:
            missing_tags.append(tag)
            missing_indices.append(i)
            vectors.append(None)  # 後から埋める

    # 2. 未登録タグを一括エンコード
    if missing_tags:
        new_embeddings = sentence_model.encode(
            missing_tags,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        for j, i in enumerate(missing_indices):
            vec = new_embeddings[j]
            vec_str = ",".join(map(str, vec))
            add_tag_embedding(missing_tags[j], vec_str)
            vectors[i] = vec * weights[i]

    # 3. 加重平均 → 正規化
    vectors = np.array(vectors)
    final_embedding = np.mean(vectors, axis=0)
    norm = np.linalg.norm(final_embedding)
    return final_embedding / norm if norm > 1e-6 else final_embedding


def get_similar_image_ids(
    image_id: int, show_sensitive: bool, top_k: int = 30
) -> list[int]:
    """
    類似画像のIDを取得する。
    """
    query_vec = get_image_tag_embedding(image_id)
    if query_vec is None:
        print("❌ クエリ画像のベクトルがありません")
        return []

    db_vectors = load_all_image_tag_embedding(
        exclude_id=image_id, show_sensitive=show_sensitive
    )
    return _search_top_similar_image_ids(query_vec, db_vectors, top_k=top_k)


def _search_top_similar_image_ids(
    query_vec: np.ndarray, db_vectors: list[tuple[int, np.ndarray]], top_k: int = 30
) -> list[int]:
    if query_vec is None or not db_vectors:
        return []

    ids, vecs = zip(*db_vectors)
    sims = cosine_similarity([query_vec], vecs)[0]
    sorted_indices = np.argsort(sims)[::-1]
    return [ids[i] for i in sorted_indices[:top_k]]
