from core.format import fmt_ts, fmt_srt, group_by_interval, merge_segments


def test_fmt_ts_zero():
    assert fmt_ts(0) == "[00:00:00]"


def test_fmt_ts_hours():
    assert fmt_ts(3661) == "[01:01:01]"


def test_fmt_srt_milliseconds():
    assert fmt_srt(1.5) == "00:00:01,500"


def test_group_by_interval_empty():
    assert group_by_interval([], 10) == []


def test_group_by_interval_groups():
    segs = [
        {"start": 0, "end": 3, "text": "hello"},
        {"start": 3, "end": 6, "text": "world"},
        {"start": 11, "end": 14, "text": "new group"},
    ]
    result = group_by_interval(segs, 10)
    assert len(result) == 2
    assert result[0]["text"] == "hello world"
    assert result[1]["text"] == "new group"


def test_merge_segments_no_diarization():
    segs = [
        {"start": 0, "end": 2, "text": "hello"},
        {"start": 2.1, "end": 4, "text": "world"},
    ]
    result = merge_segments(segs, {})
    assert len(result) == 1
    assert result[0]["text"] == "hello world"


def test_merge_segments_speaker_split():
    segs = [
        {"start": 0, "end": 2, "text": "hello"},
        {"start": 2.1, "end": 4, "text": "world"},
    ]
    # seg1 mid = (0+2)/2 * 10 = 10, seg2 mid = (2.1+4)/2 * 10 = 30
    labels = {10: "SPEAKER_00", 30: "SPEAKER_01"}
    result = merge_segments(segs, labels)
    assert len(result) == 2
    assert result[0]["speaker"] == "SPEAKER_00"
    assert result[1]["speaker"] == "SPEAKER_01"
