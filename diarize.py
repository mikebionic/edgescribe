#!/usr/bin/env python3
import argparse
import sys
import time
from pathlib import Path

from core.audio import find_audio_files
from core.diarize import diarize, build_label_map
from core.format import fmt_ts, fmt_srt


def _parse_srt_time(s: str) -> float:
    parts = s.replace(",", ".").split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def _merge_with_srt(diar_segments: list[dict], srt_path: Path) -> list[dict] | None:
    if not srt_path.exists():
        return None
    labels = build_label_map(diar_segments)
    entries = []
    lines = srt_path.read_text(encoding="utf-8").strip().split("\n")
    i = 0
    while i < len(lines):
        if lines[i].strip().isdigit() and i + 2 < len(lines):
            time_line = lines[i + 1]
            text = lines[i + 2].strip()
            if " --> " in time_line:
                start_str, end_str = time_line.split(" --> ")
                start = _parse_srt_time(start_str.strip())
                end = _parse_srt_time(end_str.strip())
                mid_key = int(((start + end) / 2) * 10)
                speaker = labels.get(mid_key, "UNKNOWN")
                entries.append({"start": start, "end": end, "speaker": speaker, "text": text})
            i += 4
        else:
            i += 1
    return entries


def run(audio_path: Path, method: str, num_speakers: int, output_dir):
    dest = output_dir or audio_path.parent
    out_txt = dest / (audio_path.stem + "_speakers.txt")
    out_srt = dest / (audio_path.stem + "_speakers.srt")

    if out_txt.exists():
        print(f"skip (exists): {out_txt.name}")
        return

    print(f"{audio_path.name} ({method}, {num_speakers} speakers) ...", end=" ", flush=True)
    t0 = time.time()
    diar_segments = diarize(str(audio_path), num_speakers, method)
    print(f"done in {time.time()-t0:.1f}s, {len(diar_segments)} segments")

    srt_path = audio_path.with_suffix(".srt")
    if output_dir:
        candidate = output_dir / (audio_path.stem + ".srt")
        if candidate.exists():
            srt_path = candidate

    merged = _merge_with_srt(diar_segments, srt_path)

    txt_lines, srt_entries = [], []
    if merged:
        for i, seg in enumerate(merged, 1):
            txt_lines.append(f"{fmt_ts(seg['start'])} {seg['speaker']}: {seg['text']}")
            srt_entries.append(
                f"{i}\n{fmt_srt(seg['start'])} --> {fmt_srt(seg['end'])}\n"
                f"{seg['speaker']}: {seg['text']}\n"
            )
    else:
        for i, seg in enumerate(diar_segments, 1):
            txt_lines.append(f"{fmt_ts(seg['start'])} {seg['speaker']}")
            srt_entries.append(
                f"{i}\n{fmt_srt(seg['start'])} --> {fmt_srt(seg['end'])}\n{seg['speaker']}\n"
            )

    out_txt.write_text("\n".join(txt_lines), encoding="utf-8")
    out_srt.write_text("\n".join(srt_entries), encoding="utf-8")
    print(f"-> {out_txt.name}, {out_srt.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--speakers", "-s", type=int, default=2)
    parser.add_argument("--method", "-m", default="simple", choices=["simple", "speechbrain"])
    parser.add_argument("--output", "-o", default=None)
    args = parser.parse_args()

    files = find_audio_files(Path(args.input).expanduser())
    if not files:
        print("no audio files found")
        sys.exit(1)

    out_dir = Path(args.output).expanduser() if args.output else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{len(files)} file(s) | method: {args.method} | speakers: {args.speakers}\n")
    for f in files:
        run(f, args.method, args.speakers, out_dir)


if __name__ == "__main__":
    main()
