# edgescribe: Edge Audio Intelligence

> Local by Default. Cloud When You Need It.

**Формат:** 20 мин + 5 мин Q&A
**Аудитория:** разработчики, AI/IoT энтузиасты

---

## SLIDE 1 — TITLE

```
edgescribe
Edge Audio Intelligence
Local by Default. Cloud When You Need It.

python · faster-whisper · fastapi · ffmpeg · speechbrain
```

**ЗАМЕТКИ:**
Кто из вас загружал голосовые сообщения или записи встреч в облачный сервис? 11 Labs, TurboScribe, Otter.ai. Они работают. Но сегодня я хочу поговорить о том, что происходит с файлами после загрузки — и почему я решил собрать свой инструмент.

---

## SLIDE 2 — ПРОБЛЕМА

```
Что происходит при загрузке аудио в облако:

  Ваш файл  ──────▶  Чужой сервер

                       ? срок хранения
                       ? обучение моделей
                       ? кто имеет доступ
                       ? политика удаления

  TurboScribe: "We may retain your audio for up to 30 days"
  ElevenLabs: "...to improve our Services"
```

**ЗАМЕТКИ:**
Загружая аудио в любой облачный сервис, вы отдаёте контроль. Для встреч, медицинских консультаций, бизнес-переговоров — это неприемлемо.

---

## SLIDE 3 — АЛЬТЕРНАТИВА

```
OpenAI Whisper (2022) — open source модель транскрипции

  Ваш файл  ──────▶  ВАШ компьютер

                       Интернет: не нужен
                       API ключи: нет
                       Подписки: нет

Современные CPU (i5/Ryzen 5) справляются.
```

---

## SLIDE 4 — ЧТО ТАКОЕ EDGESCRIBE

```
edgescribe = локальная транскрипция аудио/видео

Три интерфейса:

  1. Web UI — FastAPI + статичный HTML/JS
     make serve → http://localhost:8000
     Загрузка файлов, запись голоса, пакетная обработка

  2. CLI — командная строка
     python transcribe.py -i meeting.mp3
     Пакетная обработка, скрипты

  3. REST API — для интеграции
     POST /v1/transcribe → job_id → polling
     Home Assistant, n8n, любой скрипт

Вход:   MP3, WAV, FLAC, M4A, OGG, MP4, MKV, MOV...
Выход:  .txt + .srt (субтитры с таймкодами)
```

---

## SLIDE 5 — АРХИТЕКТУРА КОДА

```
Структура проекта:

  api.py              ← FastAPI роуты, отдаёт static/
  core/
    engine.py         ← Кэш моделей Whisper + транскрипция
    diarize.py        ← Определение спикеров (2 метода)
    format.py         ← Таймкоды, группировка сегментов
    audio.py          ← FFmpeg утилиты
  static/
    index.html        ← Web UI (vanilla JS)
    app.js            ← Upload, polling, progress bar
  transcribe.py       ← CLI обёртка
  diarize.py          ← CLI обёртка
```

**ЗАМЕТКИ:**
Чистое разделение: `core/` содержит всю бизнес-логику без веб-зависимостей. `api.py` — только HTTP роуты. CLI — тонкие обёртки. Фронтенд — vanilla HTML/JS, без React, без сборки.

---

## SLIDE 6 — КОД: КАК ОБРАБАТЫВАЕТСЯ АУДИО

```python
# core/engine.py — движок транскрипции

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

**ЗАМЕТКИ:**
Ленивая загрузка модели (кэшируется), INT8 квантизация для скорости на CPU, VAD встроен в faster-whisper, streaming обработка сегментов с progress callback.

---

## SLIDE 7 — КОД: КАК API ОБРАБАТЫВАЕТ ЗАДАЧИ

```python
# api.py — асинхронная обработка

from concurrent.futures import ThreadPoolExecutor
_executor = ThreadPoolExecutor(max_workers=2)

@app.post("/v1/transcribe")
async def submit(file: UploadFile, language="auto",
                 model="large-v3-turbo", speakers=0):
    tmp = save_to_temp(file)
    job_id = uuid4()
    JOBS[job_id] = {"status": "queued", ...}
    _executor.submit(_run, job_id, tmp, ...)
    return {"job_id": job_id}

# Клиент опрашивает GET /v1/jobs/{job_id}
# Ответ: status, progress %, speed, ETA
```

```javascript
// static/app.js — polling с плавным progress bar

pollTimer = setInterval(async () => {
  const job = await fetch(`/v1/jobs/${jobId}`).then(r => r.json());
  if (job.status === "processing") {
    targetPct = job.progress;  // плавная интерполяция
  } else if (job.status === "done") {
    showResult(job);
    playChime();  // синтезированный C-E-G аккорд
  }
}, 1000);
```

---

## SLIDE 8 — КОД: ДИАРИЗАЦИЯ СПИКЕРОВ

```python
# core/diarize.py — кто говорит когда

def diarize(audio_path, num_speakers, method="simple"):
    if method == "simple":
        # ECAPA-TDNN embeddings → кластеризация
        from simple_diarizer.diarizer import Diarizer
        diar = Diarizer(embed_model="ecapa")
        segments = diar.diarize(wav_path, num_speakers=num_speakers)
    else:
        # SpeechBrain encoder → agglomerative clustering
        from speechbrain.inference.speaker import EncoderClassifier
        # chunks → embeddings → clustering
        labels = AgglomerativeClustering(n_clusters=num_speakers)
                     .fit_predict(embeddings)
```

```
Выход:
[00:00:05] SPEAKER_00: Расскажите про сроки.
[00:00:12] SPEAKER_01: Мы смотрели на Q3.
[00:00:21] SPEAKER_00: Что вызвало сдвиг?
```

---

## SLIDE 9 — ПРОИЗВОДИТЕЛЬНОСТЬ

```
Тест: AMD Ryzen 7 PRO, 14 GB RAM, только CPU

  Длина аудио     Время         Скорость
  10 мин          ~5 мин        2x realtime
  30 мин          ~15 мин       2x
  1 час           ~30 мин       2x

  Модель           Размер   Скорость   Качество
  large-v3-turbo   1.5 GB   2x RT     Отличное ← default
  large-v3         3 GB     1x RT     Лучшее
  medium           1.5 GB   4x RT     Хорошее
  small            500 MB   7x RT     Нормальное
  base             150 MB   15x RT    Базовое

  RAM: ~6 GB (модель) + запас
  CPU: 85-95% все ядра
```

---

## SLIDE 10 — ДЕПЛОЙ: ТРЕБОВАНИЯ К СЕРВЕРУ

```
Личное использование (1-3 пользователя):

  CPU:     2+ vCPU (Xeon / EPYC)
  RAM:     16 GB (модель ~6 GB + запас)
  Диск:    40 GB SSD
  ОС:      Ubuntu 22.04 LTS

  Hetzner CPX41: €35/мес
  AWS t3.xlarge:  ~$120/мес

Команда (5-20 пользователей):

  CPU:     4-8 vCPU
  RAM:     32-64 GB
  Диск:    200 GB NVMe
```

---

## SLIDE 11 — ДЕПЛОЙ: DOCKER + NGINX

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

```nginx
server {
    listen 443 ssl;
    server_name transcribe.yourdomain.com;

    client_max_body_size 500M;  # большие аудио файлы

    location / {
        proxy_pass http://localhost:8000;
        proxy_read_timeout 3600;  # транскрипция занимает минуты
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
certbot --nginx -d transcribe.yourdomain.com
python api.py --api-key YOUR_SECRET
```

**ЗАМЕТКИ:**
`client_max_body_size 500M` для больших файлов. `proxy_read_timeout 3600` потому что транскрипция занимает минуты, а дефолтный таймаут nginx — 60 секунд. Certbot для бесплатного SSL.

---

## SLIDE 12 — ВИДЕНИЕ: ЛОКАЛЬНЫЙ AI СТЕК

```
  Микрофон / аудио файл
      |
      v
  edgescribe (транскрипция)
      |
      +--▶  Home Assistant (автоматизация)
      +--▶  Ollama / llama.cpp (анализ текста)
      +--▶  Nextcloud / NAS (хранение)

  Интернет: не нужен ни на одном шаге.
```

---

## SLIDE 13 — ССЫЛКИ И Q&A

```
edgescribe
  github.com/mikebionic/edgescribe

Стек:
  faster-whisper   github.com/SYSTRAN/faster-whisper
  FastAPI          fastapi.tiangolo.com
  SpeechBrain      speechbrain.github.io
  Silero VAD       github.com/snakers4/silero-vad
  FFmpeg           ffmpeg.org

Вопросы?
```
