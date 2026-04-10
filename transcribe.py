#!/usr/bin/env python3
"""
Local audio/video transcription using faster-whisper.
Fully offline after initial model download.

Usage:
    python transcribe.py                          # transcribe all audio in current dir
    python transcribe.py --input recording.mp3    # single file
    python transcribe.py --input /path/to/folder  # folder
    python transcribe.py --language en             # specify language
    python transcribe.py --model medium            # faster, less accurate
    python transcribe.py --timestamps 10           # group by 10-second intervals
    python transcribe.py --timestamps none         # plain text, no timestamps
"""

import argparse
import sys
import time
from pathlib import Path

AUDIO_EXTENSIONS = (
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".oga", ".wma", ".aac", ".opus", ".webm",
    ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".m4v", ".ts", ".mts",
)


def fmt_ts_txt(sec: float) -> str:
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"


def fmt_ts_srt(sec: float) -> str:
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def group_by_interval(segments, interval):
    if not segments or interval <= 0:
        return segments
    grouped, texts = [], []
    win_start, win_end = 0.0, interval
    for seg in segments:
        while seg["start"] >= win_end:
            if texts:
                grouped.append({"start": win_start, "end": win_end, "text": " ".join(texts)})
                texts = []
            win_start, win_end = win_end, win_end + interval
        texts.append(seg["text"])
    if texts:
        grouped.append({"start": win_start, "end": segments[-1].get("end", win_end), "text": " ".join(texts)})
    return grouped


def find_audio_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in AUDIO_EXTENSIONS else []
    elif input_path.is_dir():
        return sorted(f for ext in AUDIO_EXTENSIONS for f in input_path.glob(f"*{ext}"))
    return []


def transcribe_file(model, audio_path: Path, language, timestamp_mode, overwrite):
    txt_path = audio_path.with_suffix(".txt")
    srt_path = audio_path.with_suffix(".srt")

    if txt_path.exists() and not overwrite:
        print(f"  SKIP (already exists, use --overwrite): {audio_path.name}")
        return

    print(f"  Transcribing: {audio_path.name} ...")
    t0 = time.time()

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        beam_size=5,
        word_timestamps=True,
    )

    raw_segments = []
    for seg in segments_iter:
        raw_segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        if len(raw_segments) % 50 == 0:
            elapsed = time.time() - t0
            print(f"    ... {len(raw_segments)} segments ({elapsed:.0f}s)")

    # Group by interval if requested
    if timestamp_mode not in ("auto", "none"):
        segments = group_by_interval(raw_segments, float(timestamp_mode))
    else:
        segments = raw_segments

    # Format output
    txt_lines, srt_entries = [], []
    for idx, seg in enumerate(segments, 1):
        text = seg["text"]
        if timestamp_mode == "none":
            txt_lines.append(text)
        else:
            txt_lines.append(f"{fmt_ts_txt(seg['start'])} {text}")
        srt_entries.append(f"{idx}\n{fmt_ts_srt(seg['start'])} --> {fmt_ts_srt(seg['end'])}\n{text}\n")

    txt_path.write_text("\n".join(txt_lines), encoding="utf-8")
    srt_path.write_text("\n".join(srt_entries), encoding="utf-8")
    elapsed = time.time() - t0
    detected = info.language if hasattr(info, "language") else "?"
    print(f"  Done: {len(segments)} segments in {elapsed:.0f}s (lang: {detected}) -> {txt_path.name}, {srt_path.name}")


def main():
    parser = argparse.ArgumentParser(description="Local audio transcription (faster-whisper)")
    parser.add_argument("--input", "-i", default=".", help="Audio file or folder (default: current dir)")
    parser.add_argument("--model", "-m", default="large-v3-turbo", help="Whisper model (default: large-v3-turbo)")
    parser.add_argument("--language", "-l", default="auto", help="Language code: ru, en, auto (default: auto)")
    parser.add_argument("--timestamps", "-t", default="auto", help="Timestamps: auto, none, or seconds (5, 10, 30)")
    parser.add_argument("--threads", default=8, type=int, help="CPU threads (default: 8)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing transcripts")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute() and args.input == ".":
        input_path = Path.cwd()

    files = find_audio_files(input_path)
    if not files:
        print("No audio files found.")
        sys.exit(1)

    lang = None if args.language == "auto" else args.language

    print(f"\nFound {len(files)} file(s)")
    print(f"Model: {args.model} | Language: {args.language} | Timestamps: {args.timestamps}")
    print(f"Loading model...")

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=args.threads)
    print("Model loaded.\n")

    for f in files:
        transcribe_file(model, f, lang, args.timestamps, args.overwrite)

    print("\nAll done!")


if __name__ == "__main__":
    main()
