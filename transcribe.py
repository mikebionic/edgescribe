#!/usr/bin/env python3
import argparse
import sys
import time
from pathlib import Path

from core.audio import find_audio_files
from core.engine import get_model, transcribe as _transcribe
from core.format import fmt_ts, fmt_srt, group_by_interval


def run(audio_path: Path, model_name: str, language, timestamp_mode: str, overwrite: bool, output_dir):
    txt_path = (output_dir or audio_path.parent) / (audio_path.stem + ".txt")
    srt_path = (output_dir or audio_path.parent) / (audio_path.stem + ".srt")

    if txt_path.exists() and not overwrite:
        print(f"skip (exists): {audio_path.name}")
        return

    print(f"{audio_path.name} ...", end=" ", flush=True)
    t0 = time.time()
    segments, detected = _transcribe(str(audio_path), model_name, language)

    if timestamp_mode not in ("auto", "none"):
        segments = group_by_interval(segments, float(timestamp_mode))

    txt_lines, srt_entries = [], []
    for i, seg in enumerate(segments, 1):
        text = seg["text"]
        txt_lines.append(text if timestamp_mode == "none" else f"{fmt_ts(seg['start'])} {text}")
        srt_entries.append(f"{i}\n{fmt_srt(seg['start'])} --> {fmt_srt(seg['end'])}\n{text}\n")

    txt_path.write_text("\n".join(txt_lines), encoding="utf-8")
    srt_path.write_text("\n".join(srt_entries), encoding="utf-8")
    print(f"done in {time.time()-t0:.0f}s (lang: {detected})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", default=".")
    parser.add_argument("--model", "-m", default="large-v3-turbo")
    parser.add_argument("--language", "-l", default="auto")
    parser.add_argument("--timestamps", "-t", default="auto")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--output", "-o", default=None)
    args = parser.parse_args()

    files = find_audio_files(Path(args.input).expanduser())
    if not files:
        print("no audio files found")
        sys.exit(1)

    lang = None if args.language == "auto" else args.language
    out_dir = Path(args.output).expanduser() if args.output else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    get_model(args.model)  # preload once

    print(f"{len(files)} file(s) | model: {args.model} | lang: {args.language}\n")
    for f in files:
        run(f, args.model, lang, args.timestamps, args.overwrite, out_dir)


if __name__ == "__main__":
    main()
