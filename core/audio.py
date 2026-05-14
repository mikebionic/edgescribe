from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

AUDIO_EXTENSIONS = (
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".oga", ".wma", ".aac",
    ".opus", ".webm", ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".m4v",
    ".ts", ".mts",
)


def get_duration(path: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def convert_to_wav(audio_path: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", tmp.name],
        capture_output=True, timeout=300,
    )
    out = Path(tmp.name)
    return tmp.name if out.exists() and out.stat().st_size > 0 else ""


def find_audio_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in AUDIO_EXTENSIONS else []
    if input_path.is_dir():
        return sorted(f for ext in AUDIO_EXTENSIONS for f in input_path.glob(f"*{ext}"))
    return []
