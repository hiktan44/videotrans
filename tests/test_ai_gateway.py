import os
import tempfile
import unittest

import requests

from app import ai_gateway

TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
SPEECH_URL = "https://api.openai.com/v1/audio/speech"
GW_ENV = {
    "AI_GATEWAY_URL": "https://ai.example.test/",
    "AI_GATEWAY_URL_YEDEK": "https://yedek.example.test",
    "AI_GATEWAY_KEY": "sk-gw",
}


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


class FakeSession:
    """requests.post yerine: her çağrıyı kaydeder, sıradaki yanıtı ya da hatayı döner."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, url, headers=None, files=None, data=None, json=None, timeout=None):
        sent = None
        if files:
            name, handle = files["file"]
            sent = (name, handle.read())
        self.calls.append({"url": url, "auth": headers["Authorization"], "data": data, "json": json, "file": sent})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class RouteTests(unittest.TestCase):
    def test_without_gateway_only_direct_route(self):
        self.assertEqual(
            ai_gateway.routes(TRANSCRIBE_URL, "k", model="whisper-1", env={}),
            [ai_gateway.Route("dogrudan", TRANSCRIBE_URL, "k")],
        )

    def test_order_gateway_backup_direct(self):
        found = ai_gateway.routes(TRANSCRIBE_URL, "k", model="whisper-1", env=GW_ENV)
        self.assertEqual([r.name for r in found], ["gecit", "gecit-yedek", "dogrudan"])
        self.assertEqual(found[0].url, "https://ai.example.test/v1/audio/transcriptions")
        self.assertEqual(found[0].model_suffix, "-videotrans")

    def test_model_allowlist_keeps_others_direct(self):
        env = {**GW_ENV, "AI_GATEWAY_MODELS": "whisper-1,gpt-4o-mini-tts"}
        self.assertEqual(len(ai_gateway.routes(TRANSCRIBE_URL, "k", model="whisper-1", env=env)), 3)
        self.assertEqual(
            [r.name for r in ai_gateway.routes(TRANSCRIBE_URL, "k", model="gpt-4o-transcribe-diarize", env=env)],
            ["dogrudan"],
        )

    def test_provider_switch_and_foreign_hosts_stay_direct(self):
        env = {**GW_ENV, "AI_GATEWAY_PROVIDERS": "gemini"}
        self.assertEqual(len(ai_gateway.routes(TRANSCRIBE_URL, "k", model="whisper-1", env=env)), 1)
        self.assertEqual(
            len(ai_gateway.routes("https://api.z.ai/api/paas/v4/audio/transcriptions", "k", model="x", env=GW_ENV)), 1
        )

    def test_status_hides_url_and_key(self):
        text = str(ai_gateway.status(GW_ENV))
        self.assertNotIn("example.test", text)
        self.assertNotIn("sk-gw", text)
        self.assertTrue(ai_gateway.status(GW_ENV)["gecit"])


class PostTests(unittest.TestCase):
    def setUp(self):
        handle, self.audio = tempfile.mkstemp(suffix=".mp3")
        os.write(handle, b"ID3-ses-verisi")
        os.close(handle)
        self.addCleanup(os.remove, self.audio)

    def test_transcription_goes_to_gateway_alias_with_virtual_key(self):
        session = FakeSession(FakeResponse(200))
        data = {"model": "whisper-1", "response_format": "srt"}
        ai_gateway.post(TRANSCRIBE_URL, api_key="sk-app", file_path=self.audio, data=data, env=GW_ENV, session=session)
        call = session.calls[0]
        self.assertEqual(call["url"], "https://ai.example.test/v1/audio/transcriptions")
        self.assertEqual(call["auth"], "Bearer sk-gw")
        self.assertEqual(call["data"]["model"], "whisper-1-videotrans")
        self.assertEqual(call["file"], (os.path.basename(self.audio), b"ID3-ses-verisi"))
        self.assertEqual(data["model"], "whisper-1")  # çağıranın sözlüğü değişmez

    def test_failover_resends_file_intact_and_direct_keeps_own_key(self):
        session = FakeSession(requests.exceptions.ConnectionError("kapalı"), FakeResponse(502), FakeResponse(200))
        response = ai_gateway.post(
            TRANSCRIBE_URL, api_key="sk-app", file_path=self.audio, data={"model": "whisper-1"}, env=GW_ENV, session=session
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([c["url"].split("/")[2] for c in session.calls], ["ai.example.test", "yedek.example.test", "api.openai.com"])
        self.assertTrue(all(c["file"][1] == b"ID3-ses-verisi" for c in session.calls))
        self.assertEqual((session.calls[-1]["auth"], session.calls[-1]["data"]["model"]), ("Bearer sk-app", "whisper-1"))

    def test_400_is_returned_not_retried(self):
        session = FakeSession(FakeResponse(400))
        response = ai_gateway.post(SPEECH_URL, api_key="sk-app", json={"model": "gpt-4o-mini-tts"}, env=GW_ENV, session=session)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(session.calls), 1)

    def test_read_timeout_is_not_retried(self):
        session = FakeSession(requests.exceptions.ReadTimeout("yavaş"))
        with self.assertRaises(requests.exceptions.ReadTimeout):
            ai_gateway.post(TRANSCRIBE_URL, api_key="sk-app", file_path=self.audio, data={"model": "whisper-1"}, env=GW_ENV, session=session)
        self.assertEqual(len(session.calls), 1)

    def test_speech_json_alias(self):
        session = FakeSession(FakeResponse(200, b"mp3"))
        payload = {"model": "gpt-4o-mini-tts", "voice": "marin", "input": "Merhaba"}
        response = ai_gateway.post(SPEECH_URL, api_key="sk-app", json=payload, env=GW_ENV, session=session)
        self.assertEqual(response.content, b"mp3")
        self.assertEqual(session.calls[0]["json"]["model"], "gpt-4o-mini-tts-videotrans")
        self.assertEqual(session.calls[0]["json"]["voice"], "marin")


if __name__ == "__main__":
    unittest.main()
