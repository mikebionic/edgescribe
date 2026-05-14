# I Stopped Uploading My Audio to the Cloud. Here's What I Built Instead.

In March I hit the free tier limit on 11 Labs. When I started looking for alternatives, something bothered me more than the paywall: I had no idea where my recordings were stored. I could not delete them.

This is how every cloud transcription service works. You upload audio, it gets processed on their servers, and what happens after that is buried in terms of service nobody reads. TurboScribe retains audio for up to 30 days. ElevenLabs' terms include language about using content to improve their services.

For casual use, that's a tolerable trade-off. For anything sensitive — legal, medical, journalistic — it's not.

The technology to transcribe audio locally has existed since OpenAI released Whisper in 2022. What was missing was a way to use it without fighting CUDA dependencies and Python environment hell.

That is what I built.

## How It Works

Edgescribe is a FastAPI application serving a static HTML/JS frontend. Upload a file in the browser, get a transcript back. The processing pipeline:

```
audio file → FFmpeg (16kHz WAV) → Silero VAD (strip silence) → faster-whisper → .txt + .srt
```

The core engine in `core/engine.py`:

```python
def transcribe(audio_path, model_name="large-v3-turbo", language=None, on_progress=None):
    model = get_model(model_name)
    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
    )
    segments = []
    for s in segments_iter:
        segments.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        if on_progress:
            on_progress(s.end, len(segments))
    return segments, info.language
```

The model is `faster-whisper` by SYSTRAN — a CTranslate2 reimplementation of Whisper with INT8 quantization. 2-4x faster on CPU, same accuracy. The `large-v3-turbo` variant is 1.5 GB on disk, ~6 GB in RAM.

The web interface is vanilla HTML/JS — no React, no framework. File upload via FormData, job polling via `setInterval`, progress bar with smooth interpolation. Multi-file batch processing, voice recording with waveform visualization, editable results.

The API is FastAPI with a `ThreadPoolExecutor` for background transcription jobs:

```python
@app.post("/v1/transcribe")
async def submit(file: UploadFile, language: str = "auto", model: str = "large-v3-turbo"):
    # save to temp file, submit to executor, return job_id
    _executor.submit(_run, job_id, tmp.name, language, model, timestamps, speakers)
    return {"job_id": job_id, "status": "queued"}
```

Speaker diarization uses ECAPA-TDNN embeddings + agglomerative clustering. Two methods available: `simple-diarizer` (more accurate) and SpeechBrain (faster). No API keys.

## Performance

On AMD Ryzen 7 PRO (CPU only, 14 GB RAM):

| Audio length | Model | Time | Speed |
|---|---|---|---|
| 10 min | large-v3-turbo | ~5 min | 2x realtime |
| 1 hour | large-v3-turbo | ~30 min | 2x |
| 1 hour | medium | ~15 min | 4x |

Not instant. Cloud services with GPUs return results faster. But for async workflows — queue files, come back later — 2x realtime is fine.

## Running It

```bash
git clone https://github.com/mikebionic/edgescribe.git
cd edgescribe
make setup    # venv + deps + model download (~1.5 GB)
make serve    # http://localhost:8000
```

CLI for batch processing:

```bash
python transcribe.py -i meeting.mp3
python transcribe.py -i ~/recordings/ -l en
python diarize.py -i interview.mp3 -s 2
```

## Deploying on Your Own Server

Run edgescribe on a VPS, put it behind Nginx with HTTPS. The result is functionally identical to TurboScribe — except the server is yours.

Server requirements (personal use):

```
CPU:     2+ vCPU (Intel Xeon / AMD EPYC)
RAM:     16 GB (model needs ~6 GB)
Disk:    40 GB SSD
OS:      Ubuntu 22.04 LTS
Cost:    Hetzner CPX41 ~€35/month
```

Deployment:

```bash
apt update && apt install -y docker.io docker-compose ffmpeg
docker compose up -d
```

Nginx config:

```nginx
server {
    listen 443 ssl;
    server_name transcribe.yourdomain.com;

    client_max_body_size 500M;

    location / {
        proxy_pass http://localhost:8000;
        proxy_read_timeout 3600;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
certbot --nginx -d transcribe.yourdomain.com
```

The `proxy_read_timeout` matters — transcription requests take minutes, and the default 60s timeout will kill them.

API key protection:

```bash
python api.py --api-key YOUR_SECRET
# or: export EDGESCRIBE_API_KEY=YOUR_SECRET
```

## Why This Matters

The argument isn't about paranoia. It's about data hygiene. If you work in a field where confidentiality matters, uploading recordings to a third-party service is a decision with liability implications.

Consumer hardware can now run state-of-the-art speech recognition offline at accuracy levels matching paid services. The gap is mostly latency, not quality. For transcription — an inherently async task — that gap barely matters.

---

*Edgescribe is open source: github.com/mikebionic/edgescribe*

*Stack: faster-whisper, FastAPI, SpeechBrain, Silero VAD, FFmpeg. Python 3.9+, no GPU required.*
