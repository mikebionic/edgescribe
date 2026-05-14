from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

_cache: dict[str, object] = {}


def get_model(model_name: str):
    if model_name not in _cache:
        from faster_whisper import WhisperModel
        _cache[model_name] = WhisperModel(
            model_name, device="cpu", compute_type="int8", cpu_threads=8
        )
    return _cache[model_name]


def transcribe(
    audio_path: str,
    model_name: str = "large-v3-turbo",
    language: str | None = None,
    on_progress: callable | None = None,
) -> tuple[list[dict], str]:
    model = get_model(model_name)
    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
        word_timestamps=False,
    )
    segments = []
    for s in segments_iter:
        segments.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        if on_progress:
            on_progress(s.end, len(segments))
    detected = getattr(info, "language", language or "unknown")
    return segments, detected
