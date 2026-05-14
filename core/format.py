from __future__ import annotations


def fmt_ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"


def fmt_srt(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def group_by_interval(segments: list[dict], interval: float) -> list[dict]:
    if not segments or interval <= 0:
        return segments
    groups: list[dict] = []
    current = {**segments[0]}
    for seg in segments[1:]:
        if seg["start"] - current["start"] >= interval:
            groups.append(current)
            current = {**seg}
        else:
            current["end"] = seg["end"]
            current["text"] += " " + seg["text"]
    groups.append(current)
    return groups


def merge_segments(
    segments: list[dict],
    diar_labels: dict[int, str],
    max_gap: float = 1.5,
    max_len: int = 300,
) -> list[dict]:
    if not segments:
        return segments

    def speaker_at(seg: dict) -> str:
        if not diar_labels:
            return ""
        mid_key = int(((seg["start"] + seg["end"]) / 2) * 10)
        return diar_labels.get(mid_key, "")

    merged: list[dict] = []
    current = {**segments[0], "speaker": speaker_at(segments[0])}

    for seg in segments[1:]:
        sp = speaker_at(seg)
        gap = seg["start"] - current["end"]
        same_speaker = (sp == current["speaker"]) or not diar_labels
        if same_speaker and gap < max_gap and len(current["text"]) < max_len:
            current["end"] = seg["end"]
            current["text"] += " " + seg["text"]
        else:
            merged.append(current)
            current = {**seg, "speaker": sp}

    merged.append(current)
    return merged
