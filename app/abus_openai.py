import json
import os
import re
import time

import gradio as gr
import pysubs2
import requests
from pydub import AudioSegment
from pydub import effects

from app.abus_audio import AbusAudio
from app.abus_config import (
    get_openai_api_key,
    get_openai_translate_model,
    get_openai_tts_model,
    openai_api_available,
)
from app.abus_ffmpeg import ffmpeg_get_duration, ffmpeg_to_stereo
from app.abus_path import (
    cmd_delete_file,
    path_add_postfix,
    path_change_ext,
    path_dubbing_folder,
    path_new_filename,
    path_tts_segments_folder,
)
from app.abus_subtitle import get_txt, write_file
from app.abus_text import AbusText

import structlog
logger = structlog.get_logger()


OPENAI_BASE_URL = "https://api.openai.com/v1"


def _headers(content_type="application/json"):
    headers = {"Authorization": f"Bearer {get_openai_api_key()}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _raise_for_openai_error(response):
    if response.ok:
        return
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message") or response.text
    except Exception:
        message = response.text
    raise RuntimeError(f"OpenAI API error ({response.status_code}): {message}")


def _language_code(language_name):
    if not language_name or language_name == "Automatic Detection":
        return None
    mapping = {
        "english": "en",
        "turkish": "tr",
        "korean": "ko",
        "japanese": "ja",
        "chinese": "zh",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "italian": "it",
        "portuguese": "pt",
        "arabic": "ar",
        "russian": "ru",
        "hindi": "hi",
    }
    return mapping.get(language_name.lower())


def _srt_timestamp(seconds):
    ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _segments_to_srt(segments):
    blocks = []
    for index, segment in enumerate(segments, start=1):
        text = (segment.get("text") or segment.get("transcript") or "").strip()
        if not text:
            continue
        start = float(segment.get("start", 0) or 0)
        end = float(segment.get("end", start + 2.5) or start + 2.5)
        blocks.append(
            f"{len(blocks) + 1}\n"
            f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)


def _text_to_single_srt(text, duration):
    text = (text or "").strip()
    if not text:
        return ""
    duration = max(float(duration or 0), 2.0)
    sentences = AbusText.split_into_sentences(text, True) or [text]
    per = duration / max(len(sentences), 1)
    segments = []
    for index, sentence in enumerate(sentences):
        start = index * per
        end = duration if index == len(sentences) - 1 else (index + 1) * per
        segments.append({"start": start, "end": end, "text": sentence})
    return _segments_to_srt(segments)


class OpenAITranscribeInference:
    transcribe_models = [
        "gpt-4o-transcribe-diarize",
        "gpt-4o-transcribe",
        "gpt-4o-mini-transcribe",
        "whisper-1",
    ]

    @staticmethod
    def available_models():
        return OpenAITranscribeInference.transcribe_models

    @staticmethod
    def available_langs():
        return [
            "Automatic Detection",
            "english",
            "turkish",
            "korean",
            "japanese",
            "chinese",
            "spanish",
            "french",
            "german",
            "italian",
            "portuguese",
        ]

    def transcribe_file(self, input_path: str, params, highlight_words=False, progress=None) -> list:
        if not openai_api_available():
            raise ValueError("OPENAI_API_KEY is not set. Add it to .env, then restart the app.")

        model = params.model_size if params.model_size in self.transcribe_models else "gpt-4o-transcribe-diarize"
        language = _language_code(params.lang)

        if progress is not None:
            progress(0, desc="OpenAI transcription...")

        if model == "whisper-1":
            srt_text = self._request_whisper_srt(input_path, language)
        elif model == "gpt-4o-transcribe-diarize":
            srt_text = self._request_diarized_srt(input_path, language)
        else:
            text = self._request_plain_text(input_path, model, language)
            srt_text = _text_to_single_srt(text, ffmpeg_get_duration(input_path))

        return self._write_outputs(input_path, srt_text)

    def _request_whisper_srt(self, input_path, language):
        data = {"model": "whisper-1", "response_format": "srt"}
        if language:
            data["language"] = language
        with open(input_path, "rb") as audio_file:
            response = requests.post(
                f"{OPENAI_BASE_URL}/audio/transcriptions",
                headers=_headers(content_type=None),
                files={"file": audio_file},
                data=data,
                timeout=900,
            )
        _raise_for_openai_error(response)
        return response.text

    def _request_diarized_srt(self, input_path, language):
        data = {
            "model": "gpt-4o-transcribe-diarize",
            "response_format": "diarized_json",
            "chunking_strategy": "auto",
        }
        if language:
            data["language"] = language
        with open(input_path, "rb") as audio_file:
            response = requests.post(
                f"{OPENAI_BASE_URL}/audio/transcriptions",
                headers=_headers(content_type=None),
                files={"file": audio_file},
                data=data,
                timeout=900,
            )
        _raise_for_openai_error(response)
        payload = response.json()
        segments = payload.get("segments") or payload.get("chunks") or []
        if segments:
            return _segments_to_srt(segments)
        return _text_to_single_srt(payload.get("text", ""), ffmpeg_get_duration(input_path))

    def _request_plain_text(self, input_path, model, language):
        data = {"model": model, "response_format": "json"}
        if language:
            data["language"] = language
        with open(input_path, "rb") as audio_file:
            response = requests.post(
                f"{OPENAI_BASE_URL}/audio/transcriptions",
                headers=_headers(content_type=None),
                files={"file": audio_file},
                data=data,
                timeout=900,
            )
        _raise_for_openai_error(response)
        return response.json().get("text", "")

    def _write_outputs(self, input_path, srt_text):
        subtitles = []
        srt_path = path_change_ext(input_path, ".srt")
        write_file(srt_text, srt_path)
        subtitles.append(srt_path)

        try:
            subs = pysubs2.load(srt_path, encoding="utf-8")
            vtt_path = path_change_ext(input_path, ".vtt")
            ass_path = path_change_ext(input_path, ".ass")
            subs.save(vtt_path)
            subs.save(ass_path)
            subtitles.insert(0, vtt_path)
            subtitles.insert(1, ass_path)
        except Exception as exc:
            logger.warning(f"[abus_openai.py] Could not derive VTT/ASS: {exc}")

        txt_path = path_change_ext(input_path, ".txt")
        try:
            subs = pysubs2.load(srt_path, encoding="utf-8")
            text = "\n".join(event.plaintext for event in subs if event.plaintext.strip())
        except Exception:
            text = re.sub(r"\d+\n\d\d:\d\d:.*\n", "", srt_text)
        write_file(text, txt_path)
        subtitles.append(txt_path)
        return subtitles


class OpenAITranslator:
    def __init__(self):
        from app.abus_translate_deep import DeepTranslator

        self.fallback = DeepTranslator()

    def get_languages(self) -> list:
        return self.fallback.get_languages()

    def get_language_code(self, language_name) -> str:
        return self.fallback.get_language_code(language_name)

    def translate_text(self, source_lang: str, target_lang: str, text: str, progress=gr.Progress()) -> str:
        if not openai_api_available():
            return self.fallback.translate_text(source_lang, target_lang, text, progress)
        return self._responses_translate(source_lang, target_lang, text, preserve_srt=False)

    def translate_file(self, source_lang: str, target_lang: str, subtitle_file_path: str, output_file_path: str, progress=gr.Progress()):
        if not openai_api_available():
            return self.fallback.translate_file(source_lang, target_lang, subtitle_file_path, output_file_path, progress)

        subs = pysubs2.load(subtitle_file_path, encoding="utf-8")
        translated_events = []
        chunk_size = 35
        for start in progress.tqdm(range(0, len(subs), chunk_size), desc="OpenAI translate..."):
            chunk = pysubs2.SSAFile()
            chunk.events = subs.events[start:start + chunk_size]
            srt_text = chunk.to_string("srt")
            translated_srt = self._responses_translate(source_lang, target_lang, srt_text, preserve_srt=True)
            translated_chunk = pysubs2.SSAFile.from_string(translated_srt)
            translated_events.extend(translated_chunk.events)

        output_subs = pysubs2.SSAFile()
        output_subs.events = translated_events
        output_subs.save(output_file_path)

    def _responses_translate(self, source_lang, target_lang, text, preserve_srt):
        if preserve_srt:
            instructions = (
                f"Translate subtitle text from {source_lang} to {target_lang}. "
                "Return valid SRT only. Preserve numbering and timestamps exactly. "
                "Translate only dialogue text. Keep names, code terms, and product names natural."
            )
        else:
            instructions = (
                f"Translate from {source_lang} to {target_lang}. "
                "Return only the translation. Keep the meaning natural, concise, and suitable for dubbing."
            )

        response = requests.post(
            f"{OPENAI_BASE_URL}/responses",
            headers=_headers(),
            json={
                "model": get_openai_translate_model(),
                "input": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": text},
                ],
            },
            timeout=180,
        )
        _raise_for_openai_error(response)
        payload = response.json()
        output_text = payload.get("output_text")
        if output_text:
            return output_text.strip()

        parts = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in ("output_text", "text"):
                    parts.append(content.get("text", ""))
        return "\n".join(parts).strip()


class OpenAITTS:
    voices = ["marin", "cedar", "coral", "alloy", "ash", "ballad", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]

    @staticmethod
    def available_voices():
        return OpenAITTS.voices

    def request_tts(self, line: str, output_file: str, voice_name: str, semitones=0, speed_factor=1.0, volume_factor=0, audio_format="mp3", instructions=""):
        if not openai_api_available():
            raise ValueError("OPENAI_API_KEY is not set. Add it to .env, then restart the app.")

        output_voice_file = os.path.join(path_dubbing_folder(), path_new_filename(ext=f".{audio_format}"))
        line = AbusText.normalize_text(line)
        if not line:
            return False

        voice = voice_name if voice_name in self.voices else "marin"
        response = requests.post(
            f"{OPENAI_BASE_URL}/audio/speech",
            headers=_headers(),
            json={
                "model": get_openai_tts_model(),
                "voice": voice,
                "input": line[:4096],
                "instructions": instructions or "Natural, clear narration suitable for video dubbing.",
                "response_format": audio_format,
                "speed": float(speed_factor or 1.0),
            },
            timeout=180,
        )
        _raise_for_openai_error(response)
        with open(output_voice_file, "wb") as f:
            f.write(response.content)

        trimed_voice_file = path_add_postfix(output_voice_file, "_trimed")
        AbusAudio.trim_silence_file(output_voice_file, trimed_voice_file)
        ffmpeg_to_stereo(trimed_voice_file, output_file)

        cmd_delete_file(output_voice_file)
        cmd_delete_file(trimed_voice_file)
        return True

    def srt_to_voice(self, subtitle_file: str, output_file: str, voice_name: str, speed_factor=1.0, audio_format="mp3", instructions="", progress=gr.Progress()):
        segments_folder = path_tts_segments_folder(subtitle_file)
        subs = pysubs2.load(subtitle_file, encoding="utf-8")

        total_duration = max((line.end for line in subs), default=0)
        combined_audio = AudioSegment.silent(duration=total_duration)
        for i in progress.tqdm(range(len(subs)), desc="OpenAI TTS..."):
            line = subs[i]
            window_ms = max(1, line.end - line.start)
            tts_segment_file = os.path.join(segments_folder, f"openai_tts_{i + 1}.{audio_format}")
            ok = self.request_tts(line.text, tts_segment_file, voice_name, 0, speed_factor, 0, audio_format, instructions)
            if ok:
                segment = AudioSegment.from_file(tts_segment_file)
                segment = self._fit_segment_to_window(segment, window_ms)
                combined_audio = combined_audio.overlay(segment, position=line.start)

        combined_audio.export(output_file, format=audio_format)

    def _fit_segment_to_window(self, segment: AudioSegment, window_ms: int) -> AudioSegment:
        if len(segment) <= window_ms:
            return segment

        ratio = min(max(len(segment) / window_ms, 1.01), 2.0)
        try:
            segment = effects.speedup(segment, playback_speed=ratio, chunk_size=50, crossfade=10)
        except Exception as exc:
            logger.warning(f"[abus_openai.py] Could not speed up TTS segment: {exc}")

        return segment[:window_ms]

    def text_to_voice(self, text: str, output_file: str, voice_name: str, speed_factor=1.0, audio_format="mp3", instructions="", progress=gr.Progress()):
        segments_folder = path_tts_segments_folder(output_file)
        lines = AbusText.split_into_sentences(text, AbusText.has_punctuation_marks(text)) or [text]
        combined_audio = AudioSegment.empty()
        for i in progress.tqdm(range(len(lines)), desc="OpenAI TTS..."):
            segment_file = os.path.join(segments_folder, f"openai_tts_{i + 1:06}.{audio_format}")
            if self.request_tts(lines[i], segment_file, voice_name, 0, speed_factor, 0, audio_format, instructions):
                combined_audio += AudioSegment.from_file(segment_file)
        combined_audio.export(output_file, format=audio_format)

    def infer(self, text: str, output_file: str, voice_name: str, speed_factor=1.0, audio_format="mp3", instructions="", progress=gr.Progress()):
        if AbusText.is_subtitle_format(text):
            subs = pysubs2.SSAFile.from_string(text)
            subtitle_file = os.path.join(path_dubbing_folder(), path_new_filename(f".{subs.format}"))
            subs.save(subtitle_file)
            self.srt_to_voice(subtitle_file, output_file, voice_name, speed_factor, audio_format, instructions, progress)
        else:
            self.text_to_voice(text, output_file, voice_name, speed_factor, audio_format, instructions, progress)
