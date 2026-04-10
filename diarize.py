#!/usr/bin/env python3
"""
Local speaker diarization - identify WHO is speaking WHEN.
No API keys, no registration, no cloud. Fully offline after model download.

Usage:
    python diarize.py --input audio.mp3 --speakers 2
    python diarize.py --input audio.mp3 --speakers 3 --method speechbrain
    python diarize.py --input /path/to/folder/ --speakers 2

If a .srt file exists next to the audio, diarization labels will be merged
with the existing transcription.
"""

import argparse
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

AUDIO_EXTENSIONS = (
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".oga", ".wma", ".aac", ".opus", ".webm",
    ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".m4v", ".ts", ".mts",
)


def fmt_ts(sec: float) -> str:
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"


def fmt_ts_srt(sec: float) -> str:
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def convert_to_wav(audio_path: str) -> str:
    """Convert audio to WAV via ffmpeg (required for simple_diarizer)."""
    wav_path = audio_path.rsplit(".", 1)[0] + "_tmp.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
        capture_output=True, timeout=300,
    )
    return wav_path if Path(wav_path).exists() else ""


def find_audio_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in AUDIO_EXTENSIONS else []
    elif input_path.is_dir():
        return sorted(f for ext in AUDIO_EXTENSIONS for f in input_path.glob(f"*{ext}"))
    return []


def diarize_simple(audio_path: str, num_speakers: int) -> list[dict]:
    """Diarization via simple_diarizer (ECAPA-TDNN + Silero VAD)."""
    # Convert to WAV first (simple_diarizer requires it)
    wav_path = convert_to_wav(audio_path)
    if not wav_path:
        raise RuntimeError("ffmpeg failed to convert audio to WAV")

    try:
        from simple_diarizer.diarizer import Diarizer
        diar = Diarizer(embed_model="ecapa")
        segments = diar.diarize(wav_path, num_speakers=num_speakers)
        return [
            {"start": seg["start"], "end": seg["end"], "speaker": f"SPEAKER_{seg['label']:02d}"}
            for seg in segments
        ]
    finally:
        if Path(wav_path).exists():
            Path(wav_path).unlink()


def diarize_speechbrain(audio_path: str, num_speakers: int) -> list[dict]:
    """Diarization via SpeechBrain ECAPA-TDNN + sklearn clustering."""
    import numpy as np
    import torch
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

    seg_samples = int(3.0 * sr)
    embeddings, timestamps = [], []

    for start in range(0, waveform.shape[1], seg_samples):
        end = min(start + seg_samples, waveform.shape[1])
        chunk = waveform[:, start:end]
        if chunk.shape[1] < sr:
            continue
        emb = classifier.encode_batch(chunk).squeeze().detach().numpy()
        embeddings.append(emb)
        timestamps.append((start / sr, end / sr))

    embeddings = np.array(embeddings)
    labels = AgglomerativeClustering(n_clusters=num_speakers).fit_predict(embeddings)

    return [
        {"start": timestamps[i][0], "end": timestamps[i][1], "speaker": f"SPEAKER_{labels[i]:02d}"}
        for i in range(len(timestamps))
    ]


def parse_srt_time(s: str) -> float:
    parts = s.replace(",", ".").split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def merge_with_transcription(diar_segments, audio_path: Path):
    """Merge diarization with existing .srt transcription."""
    srt_path = audio_path.with_suffix(".srt")
    if not srt_path.exists():
        return None

    transcript_segments = []
    lines = srt_path.read_text(encoding="utf-8").strip().split("\n")
    i = 0
    while i < len(lines):
        if lines[i].strip().isdigit():
            time_line = lines[i + 1] if i + 1 < len(lines) else ""
            text = lines[i + 2].strip() if i + 2 < len(lines) else ""
            if " --> " in time_line:
                start_str, end_str = time_line.split(" --> ")
                start = parse_srt_time(start_str.strip())
                end = parse_srt_time(end_str.strip())
                transcript_segments.append({"start": start, "end": end, "text": text})
            i += 4
        else:
            i += 1

    result = []
    for tseg in transcript_segments:
        mid = (tseg["start"] + tseg["end"]) / 2
        speaker = "UNKNOWN"
        for dseg in diar_segments:
            if dseg["start"] <= mid <= dseg["end"]:
                speaker = dseg["speaker"]
                break
        result.append({"start": tseg["start"], "end": tseg["end"], "speaker": speaker, "text": tseg["text"]})
    return result


def process_file(audio_path: Path, method: str, num_speakers: int):
    out_txt = audio_path.with_name(audio_path.stem + "_speakers.txt")
    out_srt = audio_path.with_name(audio_path.stem + "_speakers.srt")

    if out_txt.exists():
        print(f"  SKIP (already exists): {out_txt.name}")
        return

    print(f"  Diarizing: {audio_path.name} (method: {method}, speakers: {num_speakers})")
    t0 = time.time()

    if method == "simple":
        diar_segments = diarize_simple(str(audio_path), num_speakers)
    else:
        diar_segments = diarize_speechbrain(str(audio_path), num_speakers)

    elapsed = time.time() - t0
    print(f"  Diarization done in {elapsed:.1f}s, {len(diar_segments)} segments")

    # Check for existing transcription
    merged = merge_with_transcription(diar_segments, audio_path)

    txt_lines, srt_entries = [], []
    if merged:
        print(f"  Found transcription {audio_path.stem}.srt, merging...")
        for idx, seg in enumerate(merged, 1):
            txt_lines.append(f"{fmt_ts(seg['start'])} {seg['speaker']}: {seg.get('text', '')}")
            srt_entries.append(
                f"{idx}\n{fmt_ts_srt(seg['start'])} --> {fmt_ts_srt(seg['end'])}\n{seg['speaker']}: {seg.get('text', '')}\n"
            )
    else:
        for idx, seg in enumerate(diar_segments, 1):
            txt_lines.append(f"{fmt_ts(seg['start'])} {seg['speaker']}")
            srt_entries.append(
                f"{idx}\n{fmt_ts_srt(seg['start'])} --> {fmt_ts_srt(seg['end'])}\n{seg['speaker']}\n"
            )

    out_txt.write_text("\n".join(txt_lines), encoding="utf-8")
    out_srt.write_text("\n".join(srt_entries), encoding="utf-8")
    print(f"  -> {out_txt.name}, {out_srt.name}")


def main():
    parser = argparse.ArgumentParser(description="Local speaker diarization - no API keys needed")
    parser.add_argument("--input", "-i", required=True, help="Audio file or folder")
    parser.add_argument("--speakers", "-s", type=int, default=2, help="Number of speakers (default: 2)")
    parser.add_argument("--method", "-m", default="simple", choices=["simple", "speechbrain"],
                        help="Method: simple (accurate) or speechbrain (faster)")
    args = parser.parse_args()

    files = find_audio_files(Path(args.input))
    if not files:
        print("No audio files found.")
        sys.exit(1)

    print(f"\nFound: {len(files)} file(s) | Method: {args.method} | Speakers: {args.speakers}\n")
    for f in files:
        process_file(f, args.method, args.speakers)
    print("\nDone!")


if __name__ == "__main__":
    main()
