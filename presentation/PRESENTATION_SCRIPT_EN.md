# edgescribe: Edge Audio Intelligence

> Local by Default. Cloud When You Need It.

**Format:** 20 min + 5 min Q&A
**Audience:** developers, AI/IoT enthusiasts

---

## SLIDE 1 — TITLE

```
edgescribe
Edge Audio Intelligence
Local by Default. Cloud When You Need It.

python · faster-whisper · fastapi · ffmpeg · speechbrain
```

**SPEAKER NOTES:**
How many of you have uploaded voice messages or meeting recordings to a cloud service? 11 Labs, TurboScribe, Otter.ai. They work well. But today I want to talk about what happens to those files after upload — and why I decided to build my own tool.

---

## SLIDE 2 — THE PROBLEM

```
What happens when you upload audio to the cloud:

  Your file  ──────▶  Someone else's server

                       ? storage duration
                       ? model training
                       ? who has access
                       ? retention period

  TurboScribe: "We may retain your audio for up to 30 days"
  ElevenLabs: "...to improve our Services"
```

**SPEAKER NOTES:**
When you upload audio to any cloud service, you hand it over. For meetings, medical consultations, business conversations — this is unacceptable. Data should not leave a controlled environment.

---

## SLIDE 3 — THE ALTERNATIVE

```
OpenAI Whisper (2022) — open source transcription model

  Your file  ──────▶  YOUR computer

                       Internet: not needed
                       API keys: none
                       Subscription: none

Modern CPUs (i5/Ryzen 5) can handle this.
```

**SPEAKER NOTES:**
OpenAI released Whisper in 2022. Since then, optimized versions appeared — faster-whisper uses INT8 quantization and runs 2-4x faster on CPU at the same accuracy. The technology exists. What was missing was a simple way to use it.

---

## SLIDE 4 — WHAT IS EDGESCRIBE

```
edgescribe = local audio/video transcription

Three interfaces:

  1. Web UI — FastAPI + static HTML/JS
     make serve → http://localhost:8000
     Upload files, record voice, multi-file batch

  2. CLI — command line
     python transcribe.py -i meeting.mp3
     Batch processing, scriptable

  3. REST API — for integration
     POST /v1/transcribe → job_id → poll for result
     Home Assistant, n8n, any script

Input:   MP3, WAV, FLAC, M4A, OGG, MP4, MKV, MOV...
Output:  .txt + .srt (subtitles with timestamps)
```

---

## SLIDE 5 — ARCHITECTURE: HOW THE CODE WORKS

```
Project structure:

  api.py              ← FastAPI routes, serves static/
  core/
    engine.py         ← Whisper model cache + transcription
    diarize.py        ← Speaker detection (2 methods)
    format.py         ← Timestamps, segment grouping
    audio.py          ← FFmpeg utilities
  static/
    index.html        ← Web UI (vanilla JS)
    app.js            ← Upload, polling, progress bar
  transcribe.py       ← CLI wrapper
  diarize.py          ← CLI wrapper
```

**SPEAKER NOTES:**
Clean separation: `core/` contains all business logic with no web dependencies. `api.py` is just HTTP routes. CLI tools are thin wrappers. Frontend is vanilla HTML/JS — no React, no build step.

---

## SLIDE 6 — CODE: HOW AUDIO GETS PROCESSED

```python
# core/engine.py — the transcription engine

_cache = {}

def get_model(model_name):
    if model_name not in _cache:
        from faster_whisper import WhisperModel
        _cache[model_name] = WhisperModel(
            model_name, device="cpu",
            compute_type="int8", cpu_threads=8
        )
    return _cache[model_name]

def transcribe(audio_path, model_name="large-v3-turbo",
               language=None, on_progress=None):
    model = get_model(model_name)
    segments_iter, info = model.transcribe(
        audio_path, language=language,
        vad_filter=True,                      # ← Silero VAD
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
    )
    segments = []
    for s in segments_iter:                    # ← streaming
        segments.append({
            "start": s.start, "end": s.end,
            "text": s.text.strip()
        })
        if on_progress:
            on_progress(s.end, len(segments))  # ← live progress
    return segments, info.language
```

**SPEAKER NOTES:**
Key points: lazy model loading (cached after first load), INT8 quantization for CPU speed, VAD built into faster-whisper, streaming segment processing with progress callback. The `on_progress` callback feeds the progress bar in the web UI.

---

## SLIDE 7 — CODE: HOW THE API HANDLES JOBS

```python
# api.py — async job processing

from concurrent.futures import ThreadPoolExecutor
_executor = ThreadPoolExecutor(max_workers=2)

@app.post("/v1/transcribe")
async def submit(file: UploadFile, language="auto",
                 model="large-v3-turbo", speakers=0):
    tmp = save_to_temp(file)
    job_id = uuid4()
    JOBS[job_id] = {"status": "queued", ...}
    _executor.submit(_run, job_id, tmp, ...)  # background
    return {"job_id": job_id}

# Client polls GET /v1/jobs/{job_id}
# Response includes: status, progress %, speed, ETA
```

```javascript
// static/app.js — frontend polling with smooth progress

pollTimer = setInterval(async () => {
  const job = await fetch(`/v1/jobs/${jobId}`).then(r => r.json());
  if (job.status === "processing") {
    targetPct = job.progress;  // smooth interpolation
  } else if (job.status === "done") {
    showResult(job);
    playChime();  // synthesized C-E-G chord
  }
}, 1000);
```

**SPEAKER NOTES:**
File upload via FormData, background processing in ThreadPoolExecutor, client polls every second. Progress interpolation on frontend for smooth bar movement. Completion chime via Web Audio API.

---

## SLIDE 8 — CODE: SPEAKER DIARIZATION

```python
# core/diarize.py — who is speaking when

def diarize(audio_path, num_speakers, method="simple"):
    if method == "simple":
        # ECAPA-TDNN embeddings → clustering
        from simple_diarizer.diarizer import Diarizer
        diar = Diarizer(embed_model="ecapa")
        segments = diar.diarize(wav_path, num_speakers=num_speakers)
        return [{"start": s["start"], "end": s["end"],
                 "speaker": f"SPEAKER_{s['label']:02d}"} ...]
    else:
        # SpeechBrain encoder → agglomerative clustering
        from speechbrain.inference.speaker import EncoderClassifier
        # chunk audio → extract embeddings → cluster
        labels = AgglomerativeClustering(n_clusters=num_speakers)
                     .fit_predict(embeddings)
```

```
Output:
[00:00:05] SPEAKER_00: So tell me about the timeline.
[00:00:12] SPEAKER_01: We were looking at Q3.
[00:00:21] SPEAKER_00: What caused the shift?
```

**SPEAKER NOTES:**
Two methods, both fully local. No API keys. ECAPA-TDNN extracts voice embeddings — a numerical fingerprint of each speaker's voice. Agglomerative clustering groups similar embeddings. Works reliably with 2-3 speakers, degrades with 5+.

---

## SLIDE 9 — PERFORMANCE

```
Test: AMD Ryzen 7 PRO, 14 GB RAM, CPU only

  Audio length    Time          Speed
  10 min          ~5 min        2x realtime
  30 min          ~15 min       2x
  1 hour          ~30 min       2x

  Model           Size     Speed     Quality
  large-v3-turbo  1.5 GB   2x RT    Excellent ← default
  large-v3        3 GB     1x RT    Best
  medium          1.5 GB   4x RT    Good
  small           500 MB   7x RT    OK
  base            150 MB   15x RT   Basic

  RAM usage: ~6 GB (model) + headroom
  CPU load: 85-95% all cores
```

---

## SLIDE 10 — DEPLOYMENT: SERVER REQUIREMENTS

```
Personal use (1-3 users):

  CPU:     2+ vCPU (Xeon / EPYC)
  RAM:     16 GB (model ~6 GB + headroom)
  Disk:    40 GB SSD
  OS:      Ubuntu 22.04 LTS

  Hetzner CPX41: €35/month
  AWS t3.xlarge:  ~$120/month

  Throughput:
  - 2-3 concurrent jobs
  - ~3 hours of audio per hour of processing

Small team (5-20 users):

  CPU:     4-8 vCPU
  RAM:     32-64 GB
  Disk:    200 GB NVMe

  Hetzner AX51: ~€60/month
  AWS t3.2xlarge: ~$200/month
```

---

## SLIDE 11 — DEPLOYMENT: DOCKER + NGINX

```dockerfile
# Dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "api.py", "--host", "0.0.0.0"]
```

```yaml
# docker-compose.yml
services:
  edgescribe:
    build: .
    ports: ["8000:8000"]
    volumes:
      - model-cache:/root/.cache/huggingface
    restart: unless-stopped
volumes:
  model-cache:
```

```nginx
# /etc/nginx/sites-available/edgescribe
server {
    listen 443 ssl;
    server_name transcribe.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/.../fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;

    client_max_body_size 500M;  # large audio files

    location / {
        proxy_pass http://localhost:8000;
        proxy_read_timeout 3600;  # transcription takes minutes
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# Setup
apt update && apt install -y docker.io docker-compose nginx certbot
docker compose up -d
certbot --nginx -d transcribe.yourdomain.com

# API key protection
python api.py --api-key YOUR_SECRET
# or: export EDGESCRIBE_API_KEY=YOUR_SECRET
```

**SPEAKER NOTES:**
Key nginx details: `client_max_body_size 500M` for large files, `proxy_read_timeout 3600` because transcription takes minutes not seconds. Certbot from Let's Encrypt for free SSL. API key via `--api-key` flag or env var.

---

## SLIDE 12 — VISION: LOCAL AI STACK

```
  Microphone / audio file
      |
      v
  edgescribe (transcription)
      |
      +--▶  Home Assistant (automation)
      |       "I'm exhausted" → lights, music, climate
      |
      +--▶  Local LLM (Ollama / llama.cpp)
      |       analysis → notes, tasks, summaries
      |
      +--▶  Nextcloud / NAS (storage)

  Internet: not needed at any step.
```

**SPEAKER NOTES:**
Transcription is just the first layer. Add a REST API and any service can send audio and get text back. Home Assistant sends a voice clip, gets a transcript. Ollama analyzes intent. All local, no subscriptions.

---

## SLIDE 13 — LINKS AND Q&A

```
edgescribe
  github.com/mikebionic/edgescribe

Stack:
  faster-whisper   github.com/SYSTRAN/faster-whisper
  FastAPI          fastapi.tiangolo.com
  SpeechBrain      speechbrain.github.io
  Silero VAD       github.com/snakers4/silero-vad
  FFmpeg           ffmpeg.org

Questions?
```
