from __future__ import annotations

from pathlib import Path

from core.audio import convert_to_wav


def diarize(audio_path: str, num_speakers: int, method: str = "simple") -> list[dict]:
    if method == "simple":
        return _diarize_simple(audio_path, num_speakers)
    return _diarize_speechbrain(audio_path, num_speakers)


def build_label_map(diar_segments: list[dict]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for seg in diar_segments:
        for t in range(int(seg["start"] * 10), int(seg["end"] * 10)):
            labels[t] = seg["speaker"]
    return labels


def _diarize_simple(audio_path: str, num_speakers: int) -> list[dict]:
    wav_path = convert_to_wav(audio_path)
    if not wav_path:
        raise RuntimeError("ffmpeg failed to convert audio")
    try:
        from simple_diarizer.diarizer import Diarizer
        diar = Diarizer(embed_model="ecapa")
        segments = diar.diarize(wav_path, num_speakers=num_speakers)
        return [
            {"start": s["start"], "end": s["end"], "speaker": f"SPEAKER_{s['label']:02d}"}
            for s in segments
        ]
    finally:
        Path(wav_path).unlink(missing_ok=True)


def _diarize_speechbrain(audio_path: str, num_speakers: int) -> list[dict]:
    import numpy as np
    import torchaudio
    from sklearn.cluster import AgglomerativeClustering
    from speechbrain.inference.speaker import EncoderClassifier

    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        run_opts={"device": "cpu"},
    )
    waveform, sr = torchaudio.load(audio_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)
        sr = 16000

    chunk_samples = int(3.0 * sr)
    embeddings, time_ranges = [], []
    for start in range(0, waveform.shape[1], chunk_samples):
        end = min(start + chunk_samples, waveform.shape[1])
        chunk = waveform[:, start:end]
        if chunk.shape[1] < sr:
            continue
        emb = classifier.encode_batch(chunk).squeeze().detach().numpy()
        embeddings.append(emb)
        time_ranges.append((start / sr, end / sr))

    labels = AgglomerativeClustering(n_clusters=num_speakers).fit_predict(np.array(embeddings))
    return [
        {"start": time_ranges[i][0], "end": time_ranges[i][1], "speaker": f"SPEAKER_{labels[i]:02d}"}
        for i in range(len(time_ranges))
    ]
