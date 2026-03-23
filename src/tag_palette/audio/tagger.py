"""音声ファイルのタグ付けモジュール。

PANNs (Pretrained Audio Neural Networks) を使って音声を分類し、
BGM / SE / Voice を自動判定する。Voice の場合は Whisper で文字起こしも行う。

Dependencies:
    pip install panns-inference librosa openai-whisper
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# AudioSet のクラスラベル数
_AUDIOSET_CLASSES = 527


class AudioType(str, Enum):
    """音声種別。DB の EnumAudioType と対応。"""

    BGM = "bgm"
    SE = "se"
    VOICE = "voice"


@dataclass
class AudioTagResult:
    """音声タグ付け結果。

    Attributes:
        audio_type: 自動判定された音声種別 (BGM/SE/Voice)
        tags: AudioSet タグ名と信頼度のマッピング (上位のみ)
        model_name: 使用した分類モデル名
        transcript: Voice の場合の文字起こしテキスト (それ以外は None)
        duration_ms: 音声の長さ (ミリ秒)
        sample_rate: サンプルレート (Hz)
    """

    audio_type: AudioType
    tags: dict[str, float]
    model_name: str = "panns-cnn14"
    transcript: str | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None


# ---------------------------------------------------------------------------
# PANNs 推論
# ---------------------------------------------------------------------------

_panns_model = None
_audioset_labels: list[str] | None = None


def _get_panns():
    """PANNs モデルを遅延ロードする。"""
    global _panns_model
    if _panns_model is None:
        import torch
        from panns_inference import AudioTagging

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _panns_model = AudioTagging(checkpoint_path=None, device=device)
        logger.info("PANNs モデルをロードしました (device=%s)", device)
    return _panns_model


def _get_audioset_labels() -> list[str]:
    """AudioSet のクラスラベル一覧を取得する。"""
    global _audioset_labels
    if _audioset_labels is None:
        import panns_inference

        _audioset_labels = panns_inference.labels
    return _audioset_labels


_MIN_SAMPLES = 32000  # PANNs CNN に必要な最低サンプル数 (1秒分)


def _load_audio(audio_path: Path, target_sr: int = 32000) -> tuple[np.ndarray, int, int]:
    """音声ファイルを読み込み、(waveform, sample_rate, duration_ms) を返す。

    短すぎる音声は PANNs の CNN でエラーになるため、ゼロパディングする。
    """
    import librosa

    waveform, sr = librosa.load(str(audio_path), sr=target_sr, mono=True)
    duration_ms = int(len(waveform) / sr * 1000)

    # 短すぎる音声をゼロパディング
    if len(waveform) < _MIN_SAMPLES:
        padded = np.zeros(_MIN_SAMPLES, dtype=waveform.dtype)
        padded[: len(waveform)] = waveform
        waveform = padded

    return waveform, sr, duration_ms


def _classify_with_panns(
    waveform: np.ndarray,
    top_k: int = 20,
    min_confidence: float = 0.05,
) -> dict[str, float]:
    """PANNs で音声を分類し、上位タグを返す。"""
    model = _get_panns()
    labels = _get_audioset_labels()

    # PANNs は (batch, samples) を期待
    audio_input = waveform[np.newaxis, :]
    clipwise_output, _ = model.inference(audio_input)

    probs = clipwise_output[0]  # shape: (527,)
    top_indices = np.argsort(probs)[::-1][:top_k]

    tags: dict[str, float] = {}
    for idx in top_indices:
        confidence = float(probs[idx])
        if confidence < min_confidence:
            break
        tags[labels[idx]] = round(confidence, 4)

    return tags


# ---------------------------------------------------------------------------
# 音声種別の自動判定
# ---------------------------------------------------------------------------

# AudioSet の主要クラスで判定に使うもの
_SPEECH_LABELS = {
    "Speech", "Male speech, man speaking", "Female speech, woman speaking",
    "Child speech, kid speaking", "Conversation", "Narration, monologue",
    "Singing", "Male singing", "Female singing",
}

_MUSIC_LABELS = {
    "Music", "Musical instrument", "Song", "Plucked string instrument",
    "Keyboard (musical)", "Drum", "Guitar", "Piano", "Synthesizer",
    "Orchestra", "Electronic music", "Hip hop music", "Jazz", "Rock music",
    "Pop music", "Techno", "Drum and bass",
}


def _detect_audio_type(tags: dict[str, float]) -> AudioType:
    """タグの信頼度から音声種別を自動判定する。"""
    speech_score = sum(tags.get(label, 0.0) for label in _SPEECH_LABELS)
    music_score = sum(tags.get(label, 0.0) for label in _MUSIC_LABELS)

    # Music が高ければ BGM
    if music_score > 0.5 and music_score > speech_score * 1.5:
        return AudioType.BGM

    # Speech が高ければ Voice
    if speech_score > 0.3 and speech_score > music_score * 1.5:
        return AudioType.VOICE

    # Music スコアがそこそこあれば BGM
    if music_score > 0.3:
        return AudioType.BGM

    # Speech スコアがそこそこあれば Voice
    if speech_score > 0.15:
        return AudioType.VOICE

    # どちらでもなければ SE
    return AudioType.SE


# ---------------------------------------------------------------------------
# Whisper 文字起こし
# ---------------------------------------------------------------------------

_whisper_model = None


def _get_whisper(model_size: str = "base"):
    """Whisper モデルを遅延ロードする。"""
    global _whisper_model
    if _whisper_model is None:
        import whisper

        _whisper_model = whisper.load_model(model_size)
        logger.info("Whisper モデルをロードしました (size=%s)", model_size)
    return _whisper_model


def _transcribe(audio_path: Path) -> str:
    """Whisper で音声ファイルを文字起こしする。"""
    model = _get_whisper()
    result = model.transcribe(str(audio_path), language="ja")
    return result["text"].strip()


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus", ".webm",
}


def is_audio_file(path: Path) -> bool:
    """音声ファイルかどうかを判定する。"""
    return path.suffix.lower() in _AUDIO_EXTENSIONS


def generate_audio_tags(
    audio_path: str | Path,
    *,
    audio_type_override: AudioType | None = None,
    top_k: int = 20,
    min_confidence: float = 0.05,
    transcribe_voice: bool = True,
) -> AudioTagResult:
    """音声ファイルからタグを生成する。

    Parameters:
        audio_path: 音声ファイルのパス
        audio_type_override: 種別を手動指定 (None なら自動判定)
        top_k: 返すタグの最大数
        min_confidence: 最低信頼度
        transcribe_voice: Voice 判定時に Whisper で文字起こしするか

    Returns:
        AudioTagResult
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_path}")

    # 音声読み込み
    waveform, sr, duration_ms = _load_audio(audio_path)

    # PANNs で分類
    tags = _classify_with_panns(waveform, top_k=top_k, min_confidence=min_confidence)

    # 種別判定
    if audio_type_override is not None:
        audio_type = audio_type_override
    else:
        audio_type = _detect_audio_type(tags)

    # Voice の場合は文字起こし
    transcript = None
    if audio_type == AudioType.VOICE and transcribe_voice:
        try:
            transcript = _transcribe(audio_path)
            logger.info("文字起こし完了: %s", audio_path.name)
        except Exception as e:
            logger.warning("文字起こし失敗: %s -> %s", audio_path.name, e)

    return AudioTagResult(
        audio_type=audio_type,
        tags=tags,
        model_name="panns-cnn14",
        transcript=transcript,
        duration_ms=duration_ms,
        sample_rate=sr,
    )


# ---------------------------------------------------------------------------
# ディレクトリ名による種別推定
# ---------------------------------------------------------------------------

_DIR_NAME_MAP: dict[str, AudioType] = {
    "bgm": AudioType.BGM,
    "music": AudioType.BGM,
    "ost": AudioType.BGM,
    "soundtrack": AudioType.BGM,
    "se": AudioType.SE,
    "sfx": AudioType.SE,
    "sound_effect": AudioType.SE,
    "sound_effects": AudioType.SE,
    "effect": AudioType.SE,
    "effects": AudioType.SE,
    "voice": AudioType.VOICE,
    "vocal": AudioType.VOICE,
    "dialogue": AudioType.VOICE,
    "speech": AudioType.VOICE,
    "セリフ": AudioType.VOICE,
    "ボイス": AudioType.VOICE,
    "効果音": AudioType.SE,
}


def detect_type_from_path(audio_path: Path) -> AudioType | None:
    """ファイルパスのディレクトリ名から音声種別を推定する。

    パスの各ディレクトリ名を下から順にチェックし、
    既知のディレクトリ名パターンにマッチすれば対応する種別を返す。
    マッチしなければ None。
    """
    for part in reversed(audio_path.parts[:-1]):  # ファイル名自体は除く
        normalized = part.lower().strip()
        if normalized in _DIR_NAME_MAP:
            return _DIR_NAME_MAP[normalized]
    return None
