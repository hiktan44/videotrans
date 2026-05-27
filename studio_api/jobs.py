import asyncio
import json
import os
import shutil
import subprocess
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

import pysubs2
import edge_tts
from deep_translator import GoogleTranslator
from pydub import AudioSegment, effects

from app.abus_asr_parameters import WhisperParameters
from app.abus_downloader import YoutubeDownloader
from app.abus_ffmpeg import ffmpeg_codec_type, ffmpeg_extract_audio
from app.abus_openai import OpenAITranscribeInference, OpenAITTS
from app.abus_zai import ZAITranscribeInference, ZAITranslator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOBS_ROOT = PROJECT_ROOT / "workspace" / "studio_jobs"
JOBS_ROOT.mkdir(parents=True, exist_ok=True)


class JobStore:
    def __init__(self, root: Path = JOBS_ROOT):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def create(self, kind: str, params: Dict) -> Dict:
        job_id = uuid.uuid4().hex
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "progress": 0.0,
            "message": "Queued",
            "params": params,
            "outputs": {},
            "error": None,
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        self.save(job)
        return job

    def get(self, job_id: str) -> Optional[Dict]:
        path = self._job_file(job_id)
        if not path.exists():
            return None
        with self._lock:
            content = path.read_text(encoding="utf-8")
        return json.loads(content)

    def save(self, job: Dict) -> None:
        job["updated_at"] = self._now()
        path = self._job_file(job["id"])
        tmp_path = path.with_suffix(".json.tmp")
        with self._lock:
            tmp_path.write_text(
                json.dumps(job, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp_path, path)

    def update(self, job_id: str, **changes) -> Dict:
        job = self.get(job_id)
        if not job:
            raise KeyError(job_id)
        job.update(changes)
        self.save(job)
        return job

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def output_path(self, job_id: str, filename: str) -> Path:
        path = (self.job_dir(job_id) / filename).resolve()
        if not str(path).startswith(str(self.job_dir(job_id).resolve())):
            raise ValueError("Invalid file path")
        return path

    def _job_file(self, job_id: str) -> Path:
        return self.root / job_id / "job.json"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


store = JobStore()
executor = ThreadPoolExecutor(max_workers=int(os.getenv("VOICE_PRO_API_WORKERS", "1")))


def enqueue(kind: str, params: Dict, fn: Callable[[Dict, Callable[[float, str], None]], Dict]) -> Dict:
    job = store.create(kind, params)

    def report(progress: float, message: str) -> None:
        store.update(job["id"], progress=max(0.0, min(1.0, progress)), message=message)

    def runner() -> None:
        store.update(job["id"], status="running", progress=0.02, message="Starting")
        try:
            outputs = fn(job, report)
            store.update(job["id"], status="completed", progress=1.0, message="Completed", outputs=outputs)
        except Exception as exc:
            store.update(
                job["id"],
                status="failed",
                error=str(exc),
                message="Failed",
                outputs={"traceback": traceback.format_exc()},
            )

    executor.submit(runner)
    return job


def copy_upload(job_id: str, source_path: str, original_name: str) -> Path:
    suffix = Path(original_name).suffix or Path(source_path).suffix or ".bin"
    target = store.job_dir(job_id) / f"input{suffix}"
    shutil.copyfile(source_path, target)
    return target


def prepare_audio(input_path: Path, audio_format: str = "mp3", force_convert: bool = True, mono: bool = False) -> Path:
    has_audio, has_video = ffmpeg_codec_type(str(input_path))
    if not has_audio:
        raise ValueError("Uploaded file has no audio stream")
    if not has_video and not force_convert:
        return input_path
    if input_path.suffix.lower() == f".{audio_format}" and not has_video and not mono:
        return input_path
    audio_path = input_path.with_name(f"{input_path.stem}_audio.{audio_format}")
    if mono:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "128k",
            str(audio_path),
            "-nostdin",
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return audio_path
    ffmpeg_extract_audio(str(input_path), str(audio_path), audio_format)
    return audio_path


def transcribe_job(job: Dict, report: Callable[[float, str], None]) -> Dict:
    params = job["params"]
    job_id = job["id"]
    input_path_value = params.get("input_path")
    if input_path_value:
        input_path = Path(input_path_value)
    else:
        youtube_url = params.get("youtube_url")
        if not youtube_url:
            raise ValueError("No input file or URL was provided")
        report(0.06, "Downloading media")
        input_path = Path(
            YoutubeDownloader().yt_download(
                youtube_url,
                str(store.job_dir(job_id)),
                params.get("video_quality", "good"),
            )
        )
        params["input_path"] = str(input_path)
        store.save(job)

    provider = params.get("provider", "openai")
    audio_format = "mp3" if provider in ("openai", "zai") else params.get("audio_format", "mp3")
    report(0.10, "Extracting audio")
    audio_path = prepare_audio(input_path, audio_format, force_convert=True, mono=(provider == "zai"))

    report(0.22, "Transcribing")
    whisper_params = WhisperParameters(
        model_size=params.get("model", "gpt-4o-transcribe-diarize"),
        lang=params.get("language", "Automatic Detection"),
        compute_type=params.get("compute_type", "int8"),
    )
    if provider == "zai":
        subtitles = ZAITranscribeInference().transcribe_file(str(audio_path), whisper_params)
    else:
        subtitles = OpenAITranscribeInference().transcribe_file(str(audio_path), whisper_params)

    report(0.85, "Collecting outputs")
    outputs = {}
    outputs["media"] = f"/api/jobs/{job_id}/files/{input_path.name}"
    outputs["audio"] = f"/api/jobs/{job_id}/files/{audio_path.name}"
    for path in subtitles:
        source = Path(path)
        target = store.job_dir(job_id) / source.name
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        outputs[source.suffix.lstrip(".") or source.name] = f"/api/jobs/{job_id}/files/{target.name}"

    return outputs


def translate_job(job: Dict, report: Callable[[float, str], None]) -> Dict:
    params = job["params"]
    job_id = job["id"]
    source_text = params.get("source_text") or ""
    if not source_text.strip():
        raise ValueError("No subtitle text was provided for translation")

    source_lang = params.get("source_language", "Automatic Detection")
    target_lang = params.get("target_language", "Turkish")
    provider = params.get("provider", "auto")

    report(0.10, "Preparing subtitles")
    subtitle_path = store.job_dir(job_id) / "source.srt"
    subtitle_path.write_text(source_text, encoding="utf-8")
    output_path = store.job_dir(job_id) / "translated.srt"

    report(0.25, "Translating")
    fallback_reason = None
    provider_used = provider

    def run_translator(selected_provider: str) -> None:
        if selected_provider == "zai":
            ZAITranslator().translate_file(source_lang, target_lang, str(subtitle_path), str(output_path))
        elif selected_provider == "azure" and _azure_text_api_working():
            _translate_subtitles_with_google(source_lang, target_lang, subtitle_path, output_path)
        else:
            _translate_subtitles_with_google(source_lang, target_lang, subtitle_path, output_path)

    try:
        if provider == "auto":
            provider_used = "zai"
            run_translator("zai")
        else:
            run_translator(provider)
    except Exception as exc:
        if provider in ("auto", "zai"):
            fallback_reason = str(exc)
            provider_used = "deep"
            report(0.55, "Z.AI timed out; falling back to Deep Translator")
            run_translator("deep")
        else:
            raise

    report(0.90, "Collecting outputs")
    translated_text = output_path.read_text(encoding="utf-8")
    txt_path = store.job_dir(job_id) / "translated.txt"
    txt_path.write_text(translated_text, encoding="utf-8")
    vtt_path = store.job_dir(job_id) / "translated.vtt"
    try:
        pysubs2.load(str(output_path), encoding="utf-8").save(str(vtt_path))
    except Exception:
        vtt_path = None
    outputs = {
        "srt": f"/api/jobs/{job_id}/files/{output_path.name}",
        "txt": f"/api/jobs/{job_id}/files/{txt_path.name}",
        "provider": provider_used,
    }
    if vtt_path:
        outputs["vtt"] = f"/api/jobs/{job_id}/files/{vtt_path.name}"
    if fallback_reason:
        outputs["warning"] = f"Z.AI failed, Deep Translator was used instead: {fallback_reason}"
    return outputs


def dubbing_job(job: Dict, report: Callable[[float, str], None]) -> Dict:
    params = job["params"]
    job_id = job["id"]
    subtitle_text = params.get("subtitle_text") or ""
    if not subtitle_text.strip():
        raise ValueError("No translated subtitle text was provided for dubbing")

    provider = params.get("provider", "edge")
    audio_format = params.get("audio_format", "mp3")
    voice_name = params.get("voice_name") or ("tr-TR-EmelNeural" if provider == "edge" else "marin")
    speed = float(params.get("speed", 1.0) or 1.0)

    report(0.08, "Preparing Turkish subtitle script")
    subtitle_path = store.job_dir(job_id) / "dub_script.srt"
    subtitle_path.write_text(subtitle_text, encoding="utf-8")
    try:
        pysubs2.load(str(subtitle_path), encoding="utf-8")
    except Exception as exc:
        raise ValueError(f"Translated subtitles are not valid SRT: {exc}") from exc

    audio_path = store.job_dir(job_id) / f"dubbed_audio.{audio_format}"
    report(0.18, "Generating dubbed voice")
    if provider == "openai":
        OpenAITTS().srt_to_voice(
            str(subtitle_path),
            str(audio_path),
            voice_name,
            speed_factor=speed,
            audio_format=audio_format,
            instructions=params.get("instructions") or "Natural, clear Turkish dubbing voice.",
            progress=_ProgressAdapter(report, 0.18, 0.76),
        )
    else:
        _edge_srt_to_voice(str(subtitle_path), str(audio_path), voice_name, speed, audio_format, report)

    outputs = {
        "audio": f"/api/jobs/{job_id}/files/{audio_path.name}",
        "srt": f"/api/jobs/{job_id}/files/{subtitle_path.name}",
        "provider": provider,
        "voice": voice_name,
    }

    media_path = _resolve_media_path(params.get("media_job_id"), params.get("media_href"))
    if media_path and media_path.exists():
        report(0.82, "Muxing dubbed video")
        video_path = store.job_dir(job_id) / "dubbed_video.mp4"
        _mux_dubbed_video(media_path, audio_path, subtitle_path, video_path)
        outputs["video"] = f"/api/jobs/{job_id}/files/{video_path.name}"

    report(0.95, "Collecting dubbing outputs")
    return outputs


def _resolve_media_path(media_job_id: Optional[str], media_href: Optional[str]) -> Optional[Path]:
    if media_job_id:
        media_job = store.get(media_job_id)
        if media_job:
            href = (media_job.get("outputs") or {}).get("media")
            if href:
                filename = href.rstrip("/").split("/")[-1]
                return store.output_path(media_job_id, filename)
            input_path = media_job.get("params", {}).get("input_path")
            if input_path:
                return Path(input_path)
    if media_href and "/api/jobs/" in media_href:
        parts = media_href.split("/api/jobs/", 1)[1].split("/")
        if len(parts) >= 3:
            return store.output_path(parts[0], parts[-1])
    return None


def _edge_srt_to_voice(
    subtitle_file: str,
    output_file: str,
    voice_name: str,
    speed_factor: float,
    audio_format: str,
    report: Callable[[float, str], None],
) -> None:
    subs = pysubs2.load(subtitle_file, encoding="utf-8")
    total_duration = max((line.end for line in subs), default=0)
    combined_audio = AudioSegment.silent(duration=total_duration)
    segments_folder = Path(subtitle_file).with_suffix("")
    segments_folder = segments_folder.parent / f"{segments_folder.name}_edge_segments"
    segments_folder.mkdir(parents=True, exist_ok=True)

    total = max(len(subs), 1)
    for index, line in enumerate(subs, start=1):
        report(0.18 + (index - 1) / total * 0.58, f"Generating voice {index}/{total}")
        text = line.plaintext.strip()
        if not text:
            continue
        segment_path = segments_folder / f"tts_{index:05}.{audio_format}"
        if not _edge_request_tts(text, segment_path, voice_name, speed_factor):
            continue
        segment = AudioSegment.from_file(segment_path)
        segment = _fit_segment_to_window(segment, max(1, line.end - line.start))
        combined_audio = combined_audio.overlay(segment, position=line.start)

    combined_audio.export(output_file, format=audio_format)


def _edge_request_tts(text: str, output_path: Path, voice_name: str, speed_factor: float) -> bool:
    rate_percent = int(round((speed_factor - 1.0) * 100))
    rate = f"{rate_percent:+d}%"

    async def save() -> None:
        communicate = edge_tts.Communicate(text, voice_name, rate=rate)
        await communicate.save(str(output_path))

    try:
        asyncio.run(save())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(save())
        finally:
            loop.close()
    return output_path.exists() and output_path.stat().st_size > 0


def _azure_text_api_working() -> bool:
    return bool(
        os.getenv("AZURE_TRANSLATOR_KEY")
        and os.getenv("AZURE_TRANSLATOR_ENDPOINT")
        and os.getenv("AZURE_TRANSLATOR_REGION")
    )


def _fit_segment_to_window(segment: AudioSegment, window_ms: int) -> AudioSegment:
    if len(segment) <= window_ms:
        return segment
    ratio = min(max(len(segment) / window_ms, 1.01), 2.0)
    try:
        segment = effects.speedup(segment, playback_speed=ratio, chunk_size=50, crossfade=10)
    except Exception:
        pass
    return segment[:window_ms]


def _mux_dubbed_video(media_path: Path, audio_path: Path, subtitle_path: Path, output_path: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(media_path),
        "-i",
        str(audio_path),
        "-i",
        str(subtitle_path),
        "-map",
        "0:v:0?",
        "-map",
        "1:a:0",
        "-map",
        "2:0?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=tur",
        "-shortest",
        str(output_path),
        "-nostdin",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


class _ProgressAdapter:
    def __init__(self, report: Callable[[float, str], None], start: float, end: float):
        self.report = report
        self.start = start
        self.end = end

    def tqdm(self, iterable, desc: str = ""):
        items = list(iterable)
        total = max(len(items), 1)
        for index, item in enumerate(items, start=1):
            self.report(self.start + (index - 1) / total * (self.end - self.start), desc)
            yield item


def _translate_subtitles_with_google(source_lang: str, target_lang: str, input_path: Path, output_path: Path) -> None:
    subs = pysubs2.load(str(input_path), encoding="utf-8")
    source_code = "auto" if source_lang == "Automatic Detection" else _google_language_code(source_lang)
    target_code = _google_language_code(target_lang)
    translator = GoogleTranslator(source=source_code, target=target_code)

    previous_text = ""
    previous_repeats = 0
    for event in subs.events:
        if not event.text:
            continue
        text = event.plaintext
        normalized = " ".join(text.lower().split())
        if normalized == previous_text:
            previous_repeats += 1
            if previous_repeats >= 2:
                event.text = ""
                continue
        else:
            previous_text = normalized
            previous_repeats = 0

        translated = translator.translate(text)
        if translated:
            event.text = translated

    subs.events = [event for event in subs.events if event.text.strip()]
    subs.save(str(output_path))


def _google_language_code(language_name: str) -> str:
    languages = GoogleTranslator().get_supported_languages(as_dict=True)
    search_name = (language_name or "").lower()
    for key, value in languages.items():
        if key.lower() == search_name:
            return value
    return "en"
