import json
import os
from pathlib import Path

import pysubs2
import requests
from pydub import AudioSegment

from app.abus_config import get_zai_api_key, zai_api_available
from app.abus_ffmpeg import ffmpeg_get_duration
from app.abus_openai import _segments_to_srt, _text_to_single_srt
from app.abus_path import path_change_ext, path_translate_folder, path_new_filename, path_add_postfix
from app.abus_subtitle import write_file

import structlog
logger = structlog.get_logger()


ZAI_BASE_URL = "https://api.z.ai"


def _headers():
    return {"Authorization": f"Bearer {get_zai_api_key()}"}


def _raise_for_zai_error(response):
    if response.ok:
        return
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message") or payload.get("msg") or response.text
    except Exception:
        message = response.text
    raise RuntimeError(f"Z.AI API error ({response.status_code}): {message}")


def _language_code(language_name):
    if not language_name or language_name == "Automatic Detection":
        return "auto"
    mapping = {
        "english": "en",
        "turkish": "tr",
        "korean": "ko",
        "japanese": "ja",
        "chinese": "zh-CN",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "italian": "it",
        "portuguese": "pt",
        "arabic": "ar",
        "russian": "ru",
        "hindi": "hi",
    }
    return mapping.get(language_name.lower(), language_name)


class ZAITranscribeInference:
    transcribe_models = ["glm-asr-2512"]

    @staticmethod
    def available_models():
        return ZAITranscribeInference.transcribe_models

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

    def transcribe_file(self, input_path: str, params=None, highlight_words=False, progress=None) -> list:
        if not zai_api_available():
            raise ValueError("ZAI_API_KEY is not set. Add it to .env, then restart the app.")

        audio = AudioSegment.from_file(input_path)
        chunk_ms = 29_000
        chunks_dir = Path(input_path).with_suffix("")
        chunks_dir = chunks_dir.parent / f"{chunks_dir.name}_zai_chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        segments = []
        total = max(len(audio), 1)
        for index, start_ms in enumerate(range(0, len(audio), chunk_ms), start=1):
            end_ms = min(start_ms + chunk_ms, len(audio))
            chunk_path = chunks_dir / f"chunk_{index:05}.mp3"
            audio[start_ms:end_ms].export(chunk_path, format="mp3", bitrate="128k")
            if progress is not None:
                progress(start_ms / total, desc="Z.AI transcription...")
            text = self._request_text(str(chunk_path))
            if text:
                segments.append({
                    "start": start_ms / 1000.0,
                    "end": end_ms / 1000.0,
                    "text": text,
                })
            else:
                logger.warning(f"[abus_zai.py] Empty transcription for chunk {chunk_path}")

        srt_text = _segments_to_srt(segments)
        if not srt_text:
            raise RuntimeError("Z.AI returned empty transcription for all audio chunks.")
        return self._write_outputs(input_path, srt_text)

    def _request_text(self, chunk_path: str) -> str:
        with open(chunk_path, "rb") as audio_file:
            response = requests.post(
                f"{ZAI_BASE_URL}/api/paas/v4/audio/transcriptions",
                headers=_headers(),
                files={"file": audio_file},
                data={"model": "glm-asr-2512", "stream": "false"},
                timeout=180,
            )
        _raise_for_zai_error(response)
        payload = response.json()
        text = self._extract_transcription_text(payload)
        if not text:
            logger.warning(f"[abus_zai.py] Empty Z.AI ASR payload: {json.dumps(payload, ensure_ascii=False)[:2000]}")
        return text

    def _extract_transcription_text(self, payload) -> str:
        candidates = [
            payload.get("text"),
            payload.get("transcript"),
            payload.get("result"),
            payload.get("data", {}).get("text") if isinstance(payload.get("data"), dict) else None,
            payload.get("data", {}).get("transcript") if isinstance(payload.get("data"), dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        choices = payload.get("choices") or []
        for choice in choices:
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()

        return ""

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
            txt = "\n".join(event.plaintext for event in subs if event.plaintext.strip())
        except Exception as exc:
            logger.warning(f"[abus_zai.py] Could not derive VTT/ASS: {exc}")
            txt = srt_text

        txt_path = path_change_ext(input_path, ".txt")
        write_file(txt, txt_path)
        subtitles.append(txt_path)
        return subtitles


class ZAITranslator:
    def get_languages(self) -> list:
        return [
            "English", "Turkish", "Korean", "Japanese", "Chinese", "Spanish",
            "French", "German", "Italian", "Portuguese", "Arabic", "Russian",
        ]

    def get_language_code(self, language_name) -> str:
        return _language_code(language_name)

    def translate_text(self, source_lang: str, target_lang: str, text: str, progress=None) -> str:
        return self._translate(source_lang, target_lang, text)

    def translate_file(self, source_lang: str, target_lang: str, subtitle_file_path: str, output_file_path: str, progress=None):
        subs = pysubs2.load(subtitle_file_path, encoding="utf-8")
        chunk_size = 8
        translated_events = []
        for start in range(0, len(subs), chunk_size):
            chunk = pysubs2.SSAFile()
            chunk.events = subs.events[start:start + chunk_size]
            if progress is not None:
                progress(start / max(len(subs), 1), desc="Z.AI translation...")
            translated_srt = self._translate(source_lang, target_lang, chunk.to_string("srt"))
            translated_chunk = pysubs2.SSAFile.from_string(translated_srt)
            translated_events.extend(translated_chunk.events)
        output_subs = pysubs2.SSAFile()
        output_subs.events = translated_events
        output_subs.save(output_file_path)

    def _translate(self, source_lang, target_lang, text):
        if not zai_api_available():
            raise ValueError("ZAI_API_KEY is not set. Add it to .env, then restart the app.")
        response = requests.post(
            f"{ZAI_BASE_URL}/api/v1/agents",
            headers={**_headers(), "Content-Type": "application/json"},
            json={
                "agent_id": "general_translation",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": text}],
                    }
                ],
                "stream": False,
                "custom_variables": {
                    "source_lang": _language_code(source_lang),
                    "target_lang": _language_code(target_lang),
                    "strategy": "general",
                    "strategy_config": {
                        "general": {
                            "suggestion": "If this is SRT, preserve numbering and timestamps exactly. Translate only dialogue text."
                        }
                    },
                },
            },
            timeout=45,
        )
        _raise_for_zai_error(response)
        payload = _parse_zai_payload(response)
        choices = payload.get("choices") or []
        if not choices:
            return ""
        messages = choices[0].get("messages")
        if isinstance(messages, list) and messages:
            content = messages[0].get("content", {})
        elif isinstance(messages, dict):
            content = messages.get("content", {})
        else:
            content = choices[0].get("message", {}).get("content", {})
        if isinstance(content, dict):
            return (content.get("text") or "").strip()
        return str(content).strip()


def _parse_zai_payload(response):
    try:
        return response.json()
    except Exception:
        body = response.text.strip()
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                return json.loads(line)
            except Exception:
                continue
        try:
            payload, _ = json.JSONDecoder().raw_decode(body)
            return payload
        except Exception:
            logger.warning(f"[abus_zai.py] Could not parse Z.AI payload: {body[:1000]}")
            raise
