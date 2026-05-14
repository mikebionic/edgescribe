#!/usr/bin/env python3
import argparse
import os
import time
import uuid
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
import uvicorn

from core.audio import get_duration
from core.engine import transcribe
from core.diarize import diarize, build_label_map
from core.format import fmt_ts, fmt_srt, group_by_interval, merge_segments

JOBS: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)
_api_key: str | None = None

app = FastAPI(title="edgescribe", version="1.0.0")


def _require_key(x_api_key: str | None = Header(default=None)):
    if _api_key and x_api_key != _api_key:
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")


def _update(job_id, **kw):
    JOBS[job_id].update(kw)


def _run(job_id: str, audio_path: str, language: str, model: str,
         timestamps: str, speakers: int):
    try:
        _update(job_id, status="processing", started_at=time.time(),
                stage="loading_model", progress=0)
        t0 = time.time()
        duration = get_duration(audio_path)

        from core.engine import get_model
        get_model(model)
        _update(job_id, stage="transcribing", progress=0)

        def on_progress(current_sec, seg_count):
            if duration > 0:
                pct = min(int(current_sec / duration * 100), 99)
            else:
                pct = min(seg_count, 99)
            elapsed = time.time() - t0
            speed = current_sec / elapsed if elapsed > 0 else 0
            eta = (duration - current_sec) / speed if speed > 0 and duration > 0 else 0
            _update(job_id, progress=pct, speed=round(speed, 1), eta=round(eta))

        lang = None if language == "auto" else language
        segments, detected = transcribe(audio_path, model, lang, on_progress=on_progress)

        if timestamps.isdigit():
            segments = group_by_interval(segments, float(timestamps))

        diar_labels = {}
        if speakers >= 2:
            _update(job_id, stage="diarizing", progress=0)
            try:
                diar_segs = diarize(audio_path, speakers)
                diar_labels = build_label_map(diar_segs)
            except Exception:
                pass

        if diar_labels:
            segments = merge_segments(segments, diar_labels)

        _update(job_id, stage="formatting", progress=95)

        txt_lines, srt_lines = [], []
        for i, seg in enumerate(segments, 1):
            s, e, text = seg["start"], seg["end"], seg["text"]
            sp = f"{seg.get('speaker', '')}: " if seg.get("speaker") else ""
            txt_lines.append(
                f"{sp}{text}" if timestamps == "none" else f"{fmt_ts(s)} {sp}{text}"
            )
            srt_lines.append(f"{i}\n{fmt_srt(s)} --> {fmt_srt(e)}\n{sp}{text}\n")

        _update(job_id,
                status="done", finished_at=time.time(),
                language_detected=detected, segments_count=len(segments),
                stage="done", progress=100,
                result={"txt": "\n".join(txt_lines), "srt": "\n".join(srt_lines)})
    except Exception as e:
        _update(job_id, status="failed", finished_at=time.time(), error=str(e))
    finally:
        Path(audio_path).unlink(missing_ok=True)


@app.get("/v1/health")
def health():
    return {
        "status": "ok",
        "jobs_total": len(JOBS),
        "jobs_active": sum(1 for j in JOBS.values() if j["status"] in ("queued", "processing")),
    }


@app.post("/v1/transcribe", dependencies=[Depends(_require_key)])
async def submit(
    file: UploadFile = File(...),
    language: str = Form(default="auto"),
    model: str = Form(default="large-v3-turbo"),
    timestamps: str = Form(default="auto"),
    speakers: int = Form(default=0),
):
    suffix = Path(file.filename).suffix if file.filename else ".audio"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(await file.read())
    tmp.close()

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": time.time(),
        "filename": file.filename,
        "language": language,
        "model": model,
        "timestamps": timestamps,
        "speakers": speakers,
    }
    _executor.submit(_run, job_id, tmp.name, language, model, timestamps, speakers)
    return {"job_id": job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(_require_key)])
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/v1/jobs/{job_id}/download/{fmt}", dependencies=[Depends(_require_key)])
def download(job_id: str, fmt: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Job not complete")
    if fmt not in ("txt", "srt"):
        raise HTTPException(status_code=400, detail="Format must be txt or srt")
    content = job["result"][fmt]
    stem = Path(job.get("filename", "transcript")).stem
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.{fmt}"'},
    )


@app.delete("/v1/jobs/{job_id}", dependencies=[Depends(_require_key)])
def delete_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    if JOBS[job_id]["status"] in ("queued", "processing"):
        raise HTTPException(status_code=409, detail="Cannot delete a running job")
    del JOBS[job_id]
    return {"deleted": True}


@app.get("/v1/jobs", dependencies=[Depends(_require_key)])
def list_jobs():
    return [{k: v for k, v in job.items() if k != "result"} for job in JOBS.values()]


static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    _api_key = args.api_key or os.environ.get("EDGESCRIBE_API_KEY")
    _executor = ThreadPoolExecutor(max_workers=args.workers)

    print(f"edgescribe listening on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
