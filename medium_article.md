# I Stopped Uploading My Audio to the Cloud for Transcription services like Elevenlabs and Whispflow. Here's What I Built Instead.

In March I hit the free tier limit on 11 Labs. This is not a dramatic event - it happens to everyone who actually uses a product - but the moment I started looking for alternatives, I found something that bothered me more than the paywall.

I had been using 11 Labs to transcribe voice messages, lecture recordings, and meeting notes. The quality was genuinely good: fast, accurate, handles background noise reasonably well. When the limit came up, I moved to TurboScribe, which offered three free files per day, up to thirty minutes each. I noticed pretty quickly that opening an incognito tab reset the counter. So I uploaded a few test recordings, got the transcripts, and closed the incognito window.

And then it hit me: I had no idea where those files went. I could not delete them. I did not even know which server they were sitting on. Those happened to be harmless test recordings, but the question stayed with me - what if they had been a client call? A medical consultation? Something confidential?

This is not a TurboScribe-specific problem. It is how every cloud transcription service works by design. TurboScribe's privacy policy states they may retain your audio for up to thirty days. ElevenLabs' terms include language about using content to improve their services. These are not hidden clauses - they are just things people scroll past.

For most casual use, this is a tolerable trade-off. For anything sensitive - legal, medical, journalistic, commercial - it is not.

The question I kept coming back to was: does the transcription actually need to happen on their servers? Is there a technical reason the audio has to leave my machine?

The answer is that there is no technical reason at all. OpenAI released Whisper as open source in 2022, and the model quality is on par with what the commercial services offer - because many of them are running Whisper or a derivative under the hood anyway. What was missing was a way to actually use it without spending an afternoon fighting CUDA dependencies and Python environment hell.

So I built one.

## The Stack

The core of the project is faster-whisper, a reimplementation of OpenAI's Whisper by SYSTRAN. The key difference from the original is INT8 quantisation: the model weights are stored in a lower-precision format, which reduces memory usage and speeds up inference on CPU by roughly two to four times without any meaningful loss in transcription accuracy. The large-v3-turbo model weighs about 1.5 gigabytes on disk and uses around six gigabytes of RAM at runtime. It is the sweet spot between quality and speed.

Before audio reaches Whisper, it goes through FFmpeg for format conversion. Whisper expects 16kHz mono WAV. In practice, your files will be MP3 voice messages, M4A recordings from your phone, MP4 exports from Zoom - FFmpeg normalises all of that in seconds. This is what makes the tool actually useful rather than just a demo: you do not have to think about format compatibility.

The third significant component is Silero VAD, a neural network for Voice Activity Detection. Whisper has a known tendency to hallucinate - to "transcribe" words from silence. Running VAD before transcription eliminates most of that, and as a side effect, it significantly reduces processing time on recordings with long quiet stretches.

For speaker identification, the tool uses SpeechBrain with ECAPA-TDNN voice embeddings and agglomerative clustering. The result is a transcript with speaker labels: who said what, with timestamps. This runs entirely locally.

## How I Structured the Code

I went through a few iterations before landing on something I was happy with. The first version was a single monolithic file - everything crammed together. It worked, but it was a nightmare to maintain.

The version I ended up with separates concerns properly. The business logic lives in a `core/` package: `engine.py` handles model loading and transcription, `diarize.py` handles speaker detection, `format.py` handles timestamps and segment grouping, `audio.py` wraps FFmpeg. None of these modules know anything about HTTP or the web interface.

The transcription engine looks like this:

```python
# core/engine.py
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

A few things worth noting. The model is loaded lazily - it only gets pulled into memory when somebody actually requests a transcription, not when the server starts. That matters because the model takes six gigabytes of RAM and several seconds to load, so you do not want that happening at import time. The `on_progress` callback is how the web interface gets live progress updates: every time Whisper finishes a segment, the callback fires with the current timestamp and segment count, which the API then exposes to the frontend.

The web layer is a FastAPI application. When a file comes in, it gets written to a temp file and submitted to a `ThreadPoolExecutor` for background processing. The client gets back a job ID immediately and polls for status:

```python
# api.py
_executor = ThreadPoolExecutor(max_workers=2)

@app.post("/v1/transcribe")
async def submit(file: UploadFile, language="auto", model="large-v3-turbo"):
    tmp = save_to_temp(file)
    job_id = str(uuid4())
    JOBS[job_id] = {"status": "queued", ...}
    _executor.submit(_run, job_id, tmp.name, language, model, ...)
    return {"job_id": job_id, "status": "queued"}
```

The frontend is plain HTML, CSS, and JavaScript - no React, no build step. A file drop zone, some select fields for language and model, a progress bar that smoothly interpolates between backend updates, and an editable text area for the result. You can record audio directly from your microphone as well, with a live waveform visualisation. When transcription finishes, a synthesised chime plays - a small touch, but it is surprisingly useful when you have queued up several files and walked away.

The whole thing mounts as a static directory on the FastAPI app:

```python
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

API routes are registered before the static mount, so `/v1/transcribe` and `/v1/jobs/{id}` are handled by FastAPI whilst everything else falls through to `index.html`.

I also kept the command-line tools as thin wrappers over the same `core/` package. If you prefer working in the terminal:

```bash
python transcribe.py -i meeting.mp3
python transcribe.py -i ~/recordings/ -l en
python diarize.py -i interview.mp3 -s 2
```

## What It Actually Performs Like

On an AMD Ryzen 7 PRO with 14 gigabytes of RAM - a mid-range machine - the large-v3-turbo model processes audio at roughly two times real time. A ten-minute recording takes about five minutes. An hour-long meeting takes about thirty minutes.

This is not instant. Cloud services with GPU backends return results in seconds. If you need sub-minute turnaround, local CPU transcription will not match that.

But for the actual use cases that matter - transcribing yesterday's meeting, processing a batch of interview recordings, converting voice messages to text - two times real time is perfectly workable. You queue the files, do something else, and come back to finished transcripts.

If you need speed over accuracy, the smaller models are an option. The medium model runs at roughly four times real time. The small model at seven times. For English-language content with clear audio, medium will often give you results close to large-v3-turbo at significantly higher speed.

## Deploying on Your Own Server

Local transcription covers the laptop use case. But what if you want to transcribe from your phone? Or share access with a small team whilst keeping data off third-party infrastructure?

The concept is straightforward: you run edgescribe on a VPS you control, put it behind Nginx with HTTPS, and add an API key. The result is functionally identical to TurboScribe - you open a URL in your browser, upload a file, get a transcript - except the server is yours, the data stays on your infrastructure, and there are no usage limits.

For a single user or small household, a Hetzner CPX41 (8 vCPU, 16 GB RAM, around thirty-five euros per month) is the comfortable setup. The 16 GB RAM figure is important: the model needs about six gigabytes, and you want headroom for the OS and concurrent requests.

The Dockerfile is straightforward:

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "api.py", "--host", "0.0.0.0"]
```

```bash
docker compose up -d
```

For HTTPS and domain access, the Nginx configuration needs two things that are not immediately obvious if you have not done this before. First, `client_max_body_size` needs to be large enough for audio files - I set it to 500 megabytes. Second, `proxy_read_timeout` needs to be much longer than the default sixty seconds, because transcription requests take minutes, not milliseconds. Without this, Nginx will kill the connection before the transcription finishes.

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

Let's Encrypt via Certbot provides a free TLS certificate. For access control, the API accepts an `--api-key` flag or reads from the `EDGESCRIBE_API_KEY` environment variable. Every request then requires an `X-API-Key` header.

What you end up with is your own transcription endpoint, reachable from anywhere, using only your infrastructure. You know exactly where the data is. You can delete it. You control the retention policy. If the service shuts down, your transcription capability does not disappear with it.

## Why This Matters

The argument for keeping audio on your own machine is not primarily about paranoia towards tech companies. It is about professional responsibility and basic data hygiene.

If you work in a field where confidentiality matters - legal, medical, financial, journalistic - uploading sensitive recordings to a third-party service is not a neutral choice. It is a decision with liability implications that most people make by default because the SaaS option is frictionless and the local option requires setup.

We are at a point where consumer hardware is genuinely capable of running state-of-the-art speech recognition offline, at accuracy levels that match what the paid services offer. The gap between local and cloud is mostly about latency, not quality. For transcription - an inherently asynchronous task - the latency gap matters less than people assume.

Your voice recordings contain conversations you had in confidence. The question of where those recordings are processed and stored is worth at least as much attention as the question of whether the transcript is accurate.

With the right setup, you do not have to choose between quality and control. You can have both.

---

*Edgescribe is open source. The repository is at github.com/mikebionic/edgescribe.*

*Stack: faster-whisper (SYSTRAN), FastAPI, SpeechBrain, Silero VAD, FFmpeg. Runs on Python 3.9+, Linux / macOS / Windows (WSL2), no GPU required.*
