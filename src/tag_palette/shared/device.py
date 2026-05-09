from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def get_torch_device() -> str:
    """Return the preferred torch device for this runtime."""
    try:
        import torch
    except Exception:
        return "cpu"

    return "cuda" if torch.cuda.is_available() else "cpu"


@lru_cache(maxsize=1)
def get_onnx_device() -> str:
    """Return the preferred ONNX Runtime device for this runtime."""
    try:
        import onnxruntime as ort
    except Exception:
        return "cpu"

    return "cuda" if "CUDAExecutionProvider" in ort.get_available_providers() else "cpu"


def get_onnx_providers() -> list[str]:
    """Return providers ordered by preference for the current runtime."""
    if get_onnx_device() == "cuda":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]
