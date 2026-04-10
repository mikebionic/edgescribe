#!/usr/bin/env python3
"""
GUI для локальной транскрипции аудио/видео.
Запуск: python transcribe_gui.py
Откроется в браузере: http://localhost:7860

Всё локально. Ничего не отправляется в интернет.
"""

import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import warnings
warnings.filterwarnings("ignore")

import time
import tempfile
import subprocess
import zipfile
from pathlib import Path

import gradio as gr


# ═══════════════════════════════════════
# Предзагрузка модели при старте
# ═══════════════════════════════════════

print("Загрузка модели Whisper large-v3-turbo в RAM...")
t0 = time.time()

from faster_whisper import WhisperModel
WHISPER_MODELS = {}
DEFAULT_MODEL = "large-v3-turbo"
WHISPER_MODELS[DEFAULT_MODEL] = WhisperModel(DEFAULT_MODEL, device="cpu", compute_type="int8", cpu_threads=16)

print(f"Модель загружена за {time.time() - t0:.1f}с. GUI готов к работе.")


def get_whisper_model(model_name: str):
    if model_name not in WHISPER_MODELS:
        print(f"Загрузка модели {model_name}...")
        WHISPER_MODELS[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=16)
    return WHISPER_MODELS[model_name]


# ═══════════════════════════════════════
# Утилиты
# ═══════════════════════════════════════

def get_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def convert_to_wav(audio_path: str) -> str:
    """Конвертирует аудио в WAV через ffmpeg (нужно для simple_diarizer)."""
    wav_path = audio_path.rsplit(".", 1)[0] + "_converted.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
        capture_output=True, timeout=300,
    )
    if Path(wav_path).exists():
        return wav_path
    return ""


def fmt_ts(sec: float) -> str:
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    return f"[{h:02d}:{m:02d}:{s:02d}]"

def fmt_srt(sec: float) -> str:
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def fmt_duration(sec: float) -> str:
    if sec < 60:
        return f"{sec:.0f}с"
    m, s = divmod(int(sec), 60)
    if m < 60:
        return f"{m}м {s:02d}с"
    h, m = divmod(m, 60)
    return f"{h}ч {m:02d}м"


def group_by_interval(segments, interval):
    if not segments or interval <= 0:
        return segments
    grouped, texts = [], []
    win_start, win_end = 0.0, interval
    for seg in segments:
        while seg["start"] >= win_end:
            if texts:
                grouped.append({"start": win_start, "end": win_end, "text": " ".join(texts)})
                texts = []
            win_start, win_end = win_end, win_end + interval
        texts.append(seg["text"])
    if texts:
        grouped.append({"start": win_start, "end": segments[-1].get("end", win_end), "text": " ".join(texts)})
    return grouped


def merge_segments_into_paragraphs(segments, diar_labels, max_gap=1.5, max_len=300):
    """Склеивает короткие сегменты в абзацы по спикеру и паузам."""
    if not segments:
        return segments

    def get_speaker(seg):
        if not diar_labels:
            return ""
        mid_key = int(((seg["start"] + seg["end"]) / 2) * 10)
        return diar_labels.get(mid_key, "")

    merged = []
    current = {
        "start": segments[0]["start"],
        "end": segments[0]["end"],
        "text": segments[0]["text"],
        "speaker": get_speaker(segments[0]),
    }

    for seg in segments[1:]:
        sp = get_speaker(seg)
        gap = seg["start"] - current["end"]
        same_speaker = (sp == current["speaker"]) or not diar_labels

        if same_speaker and gap < max_gap and len(current["text"]) < max_len:
            current["end"] = seg["end"]
            current["text"] += " " + seg["text"]
        else:
            merged.append(current)
            current = {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "speaker": sp,
            }

    merged.append(current)
    return merged


# ═══════════════════════════════════════
# Обработка с yield (streaming progress)
# ═══════════════════════════════════════

def transcribe_batch(
    audio_files,
    model_name: str,
    language: str,
    timestamps: str,
    do_diarize: bool,
    num_speakers: int,
    diarize_method: str,
    output_dir: str,
):
    if not audio_files:
        yield "Загрузите аудио/видео файлы", "", "⏳ Ожидание файлов...", []
        return

    if isinstance(audio_files, str):
        paths = [audio_files]
    elif isinstance(audio_files, list):
        paths = [f if isinstance(f, str) else f.name for f in audio_files]
    else:
        paths = [audio_files.name if hasattr(audio_files, "name") else str(audio_files)]

    # Определяем директорию для сохранения
    save_dir = output_dir.strip() if output_dir and output_dir.strip() else ""
    if save_dir and not Path(save_dir).exists():
        try:
            Path(save_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            save_dir = ""

    total_files = len(paths)
    all_txt, all_srt = [], []
    out_files = []
    log_lines = []

    def log(msg):
        log_lines.append(msg)

    def status_text():
        return "\n".join(log_lines[-30:])

    log(f"📂 Файлов в очереди: {total_files}")
    if save_dir:
        log(f"📁 Сохранение в: {save_dir}")
    yield "", "", status_text(), []

    model = get_whisper_model(model_name)
    lang = None if language == "auto" else language

    for file_idx, audio_path in enumerate(paths):
        fname = Path(audio_path).name
        stem = Path(audio_path).stem
        t_file_start = time.time()

        duration = get_duration(audio_path)
        dur_str = f" ({fmt_duration(duration)})" if duration > 0 else ""

        log(f"\n{'─'*50}")
        log(f"📄 [{file_idx+1}/{total_files}] {fname}{dur_str}")
        log(f"   Модель: {model_name} | Язык: {language}")
        log(f"   ⏳ Транскрибирую...")
        yield "\n".join(all_txt) if all_txt else "", "\n".join(all_srt) if all_srt else "", status_text(), out_files

        segments_iter, info = model.transcribe(
            audio_path,
            language=lang,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            beam_size=5,
            word_timestamps=True,
        )

        detected_lang = info.language if hasattr(info, "language") else language
        raw_segments = []
        last_progress_update = 0

        for seg in segments_iter:
            raw_segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})

            if duration > 0 and seg.end - last_progress_update >= 10:
                pct = min(seg.end / duration * 100, 99)
                elapsed = time.time() - t_file_start
                speed = seg.end / elapsed if elapsed > 0 else 0
                eta = (duration - seg.end) / speed if speed > 0 else 0
                log_lines[-1] = f"   ⏳ Транскрибирую... {pct:.0f}% ({fmt_duration(seg.end)}/{fmt_duration(duration)}) | {speed:.1f}x | ETA {fmt_duration(eta)}"
                last_progress_update = seg.end
                yield "\n".join(all_txt) if all_txt else "", "\n".join(all_srt) if all_srt else "", status_text(), out_files

        t_transcribe = time.time() - t_file_start
        log_lines[-1] = f"   ✅ Транскрипция: {len(raw_segments)} сегментов за {fmt_duration(t_transcribe)} (язык: {detected_lang})"
        yield "\n".join(all_txt) if all_txt else "", "\n".join(all_srt) if all_srt else "", status_text(), out_files

        # Группировка по интервалу (если выбрано)
        if timestamps.isdigit():
            segments = group_by_interval(raw_segments, float(timestamps))
        else:
            segments = raw_segments

        # Диаризация
        diar_labels = {}
        if do_diarize and num_speakers >= 2:
            log(f"   ⏳ Диаризация ({diarize_method}, {num_speakers} спикеров)...")
            yield "\n".join(all_txt) if all_txt else "", "\n".join(all_srt) if all_srt else "", status_text(), out_files
            t_diar_start = time.time()

            # Конвертируем в WAV (simple_diarizer требует)
            wav_path = ""
            try:
                if diarize_method == "simple_diarizer":
                    log(f"   ⏳ Конвертация в WAV для диаризации...")
                    yield "\n".join(all_txt) if all_txt else "", "\n".join(all_srt) if all_srt else "", status_text(), out_files
                    wav_path = convert_to_wav(audio_path)
                    if not wav_path:
                        raise RuntimeError("ffmpeg не смог конвертировать файл в WAV")

                    from simple_diarizer.diarizer import Diarizer
                    diar = Diarizer(embed_model="ecapa")
                    diar_segs = diar.diarize(wav_path, num_speakers=num_speakers)
                    for ds in diar_segs:
                        for t in range(int(ds["start"] * 10), int(ds["end"] * 10)):
                            diar_labels[t] = f"SPEAKER_{ds['label']:02d}"
                else:
                    import torch, torchaudio, numpy as np
                    from speechbrain.inference.speaker import EncoderClassifier
                    from sklearn.cluster import AgglomerativeClustering
                    classifier = EncoderClassifier.from_hparams(
                        source="speechbrain/spkrec-ecapa-voxceleb",
                        run_opts={"device": "cpu"},
                    )
                    waveform, sr = torchaudio.load(audio_path)
                    if waveform.shape[0] > 1:
                        waveform = waveform.mean(dim=0, keepdim=True)
                    if sr != 16000:
                        waveform = torchaudio.functional.resample(waveform, sr, 16000)
                        sr = 16000
                    seg_samples = int(3.0 * sr)
                    embeddings, ts_list = [], []
                    for start in range(0, waveform.shape[1], seg_samples):
                        end = min(start + seg_samples, waveform.shape[1])
                        chunk = waveform[:, start:end]
                        if chunk.shape[1] < sr:
                            continue
                        emb = classifier.encode_batch(chunk).squeeze().detach().numpy()
                        embeddings.append(emb)
                        ts_list.append((start / sr, end / sr))
                    embeddings = np.array(embeddings)
                    labels = AgglomerativeClustering(n_clusters=num_speakers).fit_predict(embeddings)
                    for i, (s, e) in enumerate(ts_list):
                        for t in range(int(s * 10), int(e * 10)):
                            diar_labels[t] = f"SPEAKER_{labels[i]:02d}"

                t_diar = time.time() - t_diar_start
                log(f"   ✅ Диаризация завершена за {fmt_duration(t_diar)} ({len(set(diar_labels.values()))} спикеров)")
            except Exception as e:
                log(f"   ⚠️ Диаризация не удалась: {e}")
                log(f"   Продолжаю без определения спикеров")
            finally:
                if wav_path and Path(wav_path).exists():
                    try:
                        Path(wav_path).unlink()
                    except Exception:
                        pass

            yield "\n".join(all_txt) if all_txt else "", "\n".join(all_srt) if all_srt else "", status_text(), out_files

        # Склеиваем короткие сегменты в абзацы
        merged = merge_segments_into_paragraphs(segments, diar_labels)
        log(f"   📝 {len(segments)} сегментов -> {len(merged)} абзацев")

        # Формирование текста
        txt_lines, srt_lines = [], []
        for idx, seg in enumerate(merged, 1):
            text = seg["text"]
            start, end = seg["start"], seg["end"]
            speaker = seg.get("speaker", "")
            if speaker:
                speaker = f"{speaker}: "
            if timestamps == "none":
                txt_lines.append(f"{speaker}{text}")
            else:
                txt_lines.append(f"{fmt_ts(start)} {speaker}{text}")
            srt_lines.append(f"{idx}\n{fmt_srt(start)} --> {fmt_srt(end)}\n{speaker}{text}\n")

        txt_content = "\n".join(txt_lines)
        srt_content = "\n".join(srt_lines)

        # Сохранение
        if save_dir:
            (Path(save_dir) / f"{stem}.txt").write_text(txt_content, encoding="utf-8")
            (Path(save_dir) / f"{stem}.srt").write_text(srt_content, encoding="utf-8")
            log(f"   💾 Сохранено: {save_dir}/{stem}.txt / .srt")

        # Файлы для скачивания
        out_dir = tempfile.mkdtemp(prefix="transcribe_")
        txt_file = Path(out_dir) / f"{stem}.txt"
        srt_file = Path(out_dir) / f"{stem}.srt"
        txt_file.write_text(txt_content, encoding="utf-8")
        srt_file.write_text(srt_content, encoding="utf-8")
        out_files.extend([str(txt_file), str(srt_file)])

        total_time = time.time() - t_file_start
        header = f"{'='*60}\n{fname} (язык: {detected_lang}, абзацев: {len(merged)})\n{'='*60}"
        all_txt.append(f"{header}\n{txt_content}")
        all_srt.append(srt_content)

        log(f"   ⏱️ Общее время: {fmt_duration(total_time)}")
        yield "\n".join(all_txt), "\n".join(all_srt), status_text(), out_files

    # ZIP со всеми файлами
    if len(out_files) > 2:
        zip_dir = tempfile.mkdtemp(prefix="transcribe_zip_")
        zip_path = str(Path(zip_dir) / "transcripts.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for f in out_files:
                zf.write(f, Path(f).name)
        out_files.insert(0, zip_path)
        log(f"\n📦 ZIP со всеми файлами: transcripts.zip")

    log(f"\n{'═'*50}")
    log(f"✅ Готово! Обработано файлов: {total_files}")
    yield "\n".join(all_txt), "\n".join(all_srt), status_text(), out_files


# ═══════════════════════════════════════
# GUI
# ═══════════════════════════════════════

LANGUAGES = [
    ("Автоопределение", "auto"),
    ("Русский", "ru"),
    ("Английский", "en"),
    ("Туркменский", "tk"),
    ("Турецкий", "tr"),
    ("Немецкий", "de"),
    ("Французский", "fr"),
    ("Испанский", "es"),
    ("Китайский", "zh"),
    ("Японский", "ja"),
    ("Корейский", "ko"),
    ("Арабский", "ar"),
    ("Португальский", "pt"),
    ("Итальянский", "it"),
    ("Хинди", "hi"),
]

with gr.Blocks(
    title="Transcribe - Локальная транскрипция",
    theme=gr.themes.Ocean(),
    css="""
        .log-box textarea { font-family: monospace !important; font-size: 13px !important; line-height: 1.5 !important; }
        .main-btn { min-height: 56px !important; font-size: 18px !important; border-radius: 12px !important; }
    """,
) as app:

    gr.HTML(
        """
        <div style="text-align: center; padding: 16px 0 8px 0;">
            <h1 style="margin: 0; font-size: 28px;">Transcribe</h1>
            <p style="color: #888; margin: 4px 0 0 0; font-size: 15px;">
                Локальная транскрипция аудио и видео — полностью на вашем компьютере
            </p>
        </div>
        """
    )

    with gr.Row():
        with gr.Column(scale=1):
            audio_input = gr.File(
                label="Аудио / Видео файлы (можно несколько)",
                file_count="multiple",
                file_types=[
                    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus", ".webm",
                    ".mp4", ".mov", ".mkv", ".avi", ".wmv",
                ],
            )

            with gr.Accordion("Настройки", open=True):
                language = gr.Dropdown(
                    choices=LANGUAGES,
                    value="auto",
                    label="Язык",
                )
                model_name = gr.Dropdown(
                    choices=[
                        ("large-v3-turbo (рекомендуется)", "large-v3-turbo"),
                        ("large-v3 (макс. качество, медленно)", "large-v3"),
                        ("medium (быстрее)", "medium"),
                        ("small (ещё быстрее)", "small"),
                        ("base (самый быстрый)", "base"),
                    ],
                    value="large-v3-turbo",
                    label="Модель",
                )
                timestamps = gr.Dropdown(
                    choices=[
                        ("По фразам (авто)", "auto"),
                        ("Каждые 2 сек", "2"),
                        ("Каждые 5 сек", "5"),
                        ("Каждые 10 сек", "10"),
                        ("Каждые 30 сек", "30"),
                        ("Без таймкодов", "none"),
                    ],
                    value="auto",
                    label="Таймкоды",
                )
                output_dir = gr.Textbox(
                    label="Папка для сохранения (оставьте пустым = только скачивание)",
                    placeholder="e.g. ~/transcripts (leave empty for download only)",
                    value="",
                )

            with gr.Accordion("Определение спикеров", open=True):
                do_diarize = gr.Checkbox(
                    label="Определять спикеров",
                    value=True,
                )
                num_speakers = gr.Slider(
                    minimum=2, maximum=10, step=1, value=2,
                    label="Количество спикеров",
                )
                diarize_method = gr.Dropdown(
                    choices=[
                        ("simple_diarizer (точнее)", "simple_diarizer"),
                        ("SpeechBrain + sklearn (быстрее)", "speechbrain"),
                    ],
                    value="simple_diarizer",
                    label="Метод диаризации",
                )

            btn = gr.Button(
                "Транскрибировать",
                variant="primary",
                size="lg",
                elem_classes=["main-btn"],
            )

        with gr.Column(scale=2):
            stats = gr.Textbox(
                label="Лог",
                interactive=False,
                lines=14,
                max_lines=30,
                elem_classes=["log-box"],
                placeholder="Здесь будет лог транскрипции...",
            )

            with gr.Tabs():
                with gr.TabItem("Текст (.txt)"):
                    txt_output = gr.Textbox(
                        label="Транскрипция",
                        lines=25,
                        interactive=False,
                        buttons=["copy"],
                    )

                with gr.TabItem("Субтитры (.srt)"):
                    srt_output = gr.Textbox(
                        label="SRT",
                        lines=25,
                        interactive=False,
                        buttons=["copy"],
                    )

            file_download = gr.File(label="Скачать файлы (ZIP + отдельно)", file_count="multiple")

    btn.click(
        fn=transcribe_batch,
        inputs=[audio_input, model_name, language, timestamps, do_diarize, num_speakers, diarize_method, output_dir],
        outputs=[txt_output, srt_output, stats, file_download],
    )

    gr.HTML(
        """
        <div style="text-align: center; padding: 12px 0; color: #999; font-size: 12px; border-top: 1px solid #eee; margin-top: 16px;">
            MP3 · WAV · FLAC · M4A · OGG · AAC · MP4 · MOV · MKV · AVI · WebM
            <br>
            Модели хранятся локально · Работает офлайн · Спикеры без регистрации
        </div>
        """
    )


if __name__ == "__main__":
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True,
    )
