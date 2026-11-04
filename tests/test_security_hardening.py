"""Studio API güvenlik sertleştirme testleri (komut enjeksiyonu, yol gezinme, SSRF, giriş sınırı)."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from studio_api import security
from studio_api.security import FailureLimiter


def _fake_getaddrinfo(address):
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    return fake


class SecurityHelperTests(unittest.TestCase):
    def test_job_id_format(self):
        self.assertTrue(security.is_valid_job_id("0123456789abcdef0123456789abcdef"))
        for bad in ("", None, "..", ".", "../x", "0123456789ABCDEF0123456789ABCDEF", "a" * 31, "a" * 33):
            self.assertFalse(security.is_valid_job_id(bad), bad)

    def test_upload_suffix(self):
        self.assertEqual(security.safe_upload_suffix("film.mp4"), ".mp4")
        self.assertEqual(security.safe_upload_suffix("FILM.MOV"), ".MOV")
        self.assertEqual(security.safe_upload_suffix('x.mp4"; id #'), ".bin")
        self.assertEqual(security.safe_upload_suffix("x.$(touch pwned)"), ".bin")
        self.assertEqual(security.safe_upload_suffix("noext"), ".bin")
        self.assertEqual(security.safe_upload_suffix(None), ".bin")

    def test_private_job_files(self):
        for name in ("job.json", "youtube_cookies.txt", "job.json.tmp"):
            self.assertTrue(security.is_private_job_file(name))
        self.assertFalse(security.is_private_job_file("translated.srt"))

    def test_media_url_scheme_and_private_hosts(self):
        self.assertIsNotNone(security.validate_media_url("file:///etc/passwd"))
        self.assertIsNotNone(security.validate_media_url("ftp://example.com/a.mp4"))
        self.assertIsNotNone(security.validate_media_url("--exec=id"))
        for address in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "100.64.0.1", "::1", "::ffff:127.0.0.1", "fd00::1", "0.0.0.0"):
            with mock.patch("socket.getaddrinfo", _fake_getaddrinfo(address)):
                self.assertIsNotNone(security.validate_media_url("https://media.example.com/v"), address)
        with mock.patch("socket.getaddrinfo", _fake_getaddrinfo("142.250.185.78")):
            self.assertIsNone(security.validate_media_url("https://www.youtube.com/watch?v=abc"))
        self.assertIsNotNone(security.validate_media_url("http://127.0.0.1:8787/health"))

    def test_media_url_normalization(self):
        self.assertEqual(security.normalize_media_url(" youtube.com/watch?v=x "), "https://youtube.com/watch?v=x")
        self.assertEqual(security.normalize_media_url("https://youtu.be/x"), "https://youtu.be/x")

    def test_failure_limiter(self):
        limiter = FailureLimiter(per_key=3, total=5, window_seconds=60)
        for _ in range(3):
            self.assertEqual(limiter.retry_after("a"), 0)
            limiter.record_failure("a")
        self.assertGreater(limiter.retry_after("a"), 0)
        self.assertEqual(limiter.retry_after("b"), 0)
        limiter.record_failure("b")
        limiter.record_failure("c")
        self.assertGreater(limiter.retry_after("d"), 0)  # toplam sınır
        limiter.reset("a")


class FfmpegNoShellTests(unittest.TestCase):
    def test_helpers_do_not_use_shell(self):
        from app import abus_ffmpeg

        workdir = tempfile.mkdtemp()
        try:
            marker = Path(workdir) / "PWNED"
            evil_input = os.path.join(workdir, f'in$(touch {marker}).mp3')
            evil_output = os.path.join(workdir, f'out`touch {marker}`.mp3')
            calls = []

            def fake_run(args, **kwargs):
                calls.append((args, kwargs))
                return mock.Mock(returncode=0)

            with mock.patch.object(abus_ffmpeg.subprocess, "run", side_effect=fake_run), \
                    mock.patch.object(abus_ffmpeg.os, "system", side_effect=AssertionError("os.system used")):
                abus_ffmpeg.ffmpeg_extract_audio(evil_input, evil_output, "mp3")
                abus_ffmpeg.ffmpeg_extract_audio(evil_input, evil_output, "wav")
                abus_ffmpeg.ffmpeg_to_stereo(evil_input, evil_output)
                abus_ffmpeg.ffmpeg_replace_audio(evil_input, evil_input, evil_output)
                abus_ffmpeg.ffmpeg_convert_audio(evil_input, evil_output, "flac")
                abus_ffmpeg.ffmpeg_mix_audio(evil_input, evil_input, evil_output, 0.0, -3.0, "mp3")
                abus_ffmpeg.ffmpeg_volume_control(evil_input, evil_output, 2.0)
                abus_ffmpeg.ffmpeg_trim_seconds(evil_input, evil_output, 1.5)

            self.assertEqual(len(calls), 8)
            for args, kwargs in calls:
                self.assertIsInstance(args, list)
                self.assertFalse(kwargs.get("shell"))
                self.assertEqual(args[0], "ffmpeg")
                self.assertIn(evil_input, args)
            extract_args = calls[0][0]
            self.assertEqual(extract_args, ["ffmpeg", "-y", "-i", evil_input, "-vn", "-f", "mp3", "-qscale:a", "0", "-ar", "48000", "-ac", "2", evil_output, "-nostdin"])
            self.assertIn("volume=2.0dB", calls[6][0])

            if shutil.which("ffmpeg"):
                abus_ffmpeg.ffmpeg_extract_audio(evil_input, evil_output, "mp3")
            self.assertFalse(marker.exists())
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


class StudioApiSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        cls.password = secrets.token_hex(12)
        cls.env = mock.patch.dict(
            os.environ,
            {"VIDEOTRANS_APP_PASSWORD": cls.password, "VIDEOTRANS_SECURE_COOKIE": "0", "VIDEOTRANS_SESSION_SECRET": ""},
        )
        cls.env.start()
        from studio_api import jobs, main

        cls.main = main
        cls.jobs = jobs
        cls.tmp_root = Path(tempfile.mkdtemp())
        cls.original_root = jobs.store.root
        jobs.store.root = cls.tmp_root
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.jobs.store.root = cls.original_root
        shutil.rmtree(cls.tmp_root, ignore_errors=True)
        cls.env.stop()

    def setUp(self):
        self.main.LOGIN_LIMITER = FailureLimiter(per_key=10, total=100, window_seconds=900)
        self.client.cookies.clear()

    def _login(self):
        response = self.client.post("/api/auth/login", data={"password": self.password})
        self.assertEqual(response.status_code, 200)

    def test_security_headers_kept(self):
        response = self.client.get("/health")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        unauth = self.client.post("/api/jobs/translate", data={"source_text": "x"})
        self.assertEqual(unauth.status_code, 401)
        self.assertEqual(unauth.headers["x-frame-options"], "DENY")

    def test_job_endpoints_reject_unauthenticated_before_body(self):
        response = self.client.post("/api/jobs/transcribe", files={"file": ("a.mp3", b"x" * 1024)})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Login required"})

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.post("/api/auth/login", data={"password": "wrong"}).status_code, 401)
        blocked = self.client.post("/api/auth/login", data={"password": self.password})
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("retry-after", blocked.headers)

    def test_login_non_ascii_password_is_401(self):
        self.assertEqual(self.client.post("/api/auth/login", data={"password": "şifreğ"}).status_code, 401)

    def test_placeholder_session_secret_not_used(self):
        body = base64.urlsafe_b64encode(json.dumps({"sub": "videotrans", "exp": int(time.time()) + 600}).encode()).decode()
        forged = f"{body}.{hmac.new(b'change_this_long_random_secret', body.encode(), hashlib.sha256).hexdigest()}"
        with mock.patch.dict(os.environ, {"VIDEOTRANS_SESSION_SECRET": "change_this_long_random_secret"}):
            self.client.cookies.set(self.main.AUTH_COOKIE, forged)
            self.assertFalse(self.client.get("/api/auth/session").json()["authenticated"])

    def test_private_files_and_traversal(self):
        self._login()
        job = self.jobs.store.create("translate", {"source_text": "gizli"})
        job_dir = self.jobs.store.job_dir(job["id"])
        (job_dir / "translated.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nMerhaba\n", encoding="utf-8")
        (job_dir / "youtube_cookies.txt").write_text("cookie", encoding="utf-8")
        self.jobs.store.update(job["id"], status="failed", outputs={"traceback": "Traceback /app/x.py", "srt": f"/api/jobs/{job['id']}/files/translated.srt"})

        ok = self.client.get(f"/api/jobs/{job['id']}/files/translated.srt")
        self.assertEqual(ok.status_code, 200)
        for name in ("job.json", "youtube_cookies.txt", "%2e%2e", "%2e"):
            self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/files/{name}").status_code, 404, name)
        self.assertEqual(self.client.get("/api/jobs/not-a-job/files/translated.srt").status_code, 404)

        public = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertNotIn("traceback", public["outputs"])
        self.assertEqual(public["params"]["source_text"], "[redacted]")
        self.assertIn("traceback", self.jobs.store.get(job["id"])["outputs"])

    def test_output_path_and_media_resolution(self):
        job = self.jobs.store.create("transcribe_upload", {})
        with self.assertRaises(ValueError):
            self.jobs.store.output_path("..", "job.json")
        with self.assertRaises(ValueError):
            self.jobs.store.output_path(job["id"], "..")
        self.assertIsNone(self.jobs._resolve_media_path("../../etc", None))
        self.assertIsNone(self.jobs._resolve_media_path(None, "/api/jobs/../files/x"))

    def test_copy_upload_suffix(self):
        job = self.jobs.store.create("transcribe_upload", {})
        source = self.tmp_root / "src.bin"
        source.write_bytes(b"data")
        target = self.jobs.copy_upload(job["id"], str(source), 'evil.mp4"; touch x #')
        self.assertEqual(target.name, "input.bin")
        target = self.jobs.copy_upload(job["id"], str(source), "video.webm")
        self.assertEqual(target.name, "input.webm")

    def test_transcribe_rejects_bad_url_and_format(self):
        self._login()
        for url in ("file:///etc/passwd", "http://127.0.0.1:8787/health", "http://169.254.169.254/latest/meta-data/"):
            response = self.client.post("/api/jobs/transcribe", data={"youtube_url": url})
            self.assertEqual(response.status_code, 400, url)
        response = self.client.post("/api/jobs/transcribe", data={"youtube_url": "https://www.youtube.com/watch?v=x", "audio_format": "mp3$(id)"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/jobs/dubbing", data={"subtitle_text": "x", "audio_format": "mp3;id"})
        self.assertEqual(response.status_code, 400)

    def test_upload_size_limit(self):
        self._login()
        with mock.patch.dict(os.environ, {"VIDEOTRANS_MAX_UPLOAD_MB": "1"}):
            response = self.client.post("/api/jobs/transcribe", files={"file": ("a.mp3", b"x" * (3 * 1024 * 1024))})
            self.assertEqual(response.status_code, 413)  # Content-Length ön denetimi
            before = set(self.tmp_root.iterdir())
            response = self.client.post("/api/jobs/transcribe", files={"file": ("a.mp3", b"x" * (1536 * 1024))})
            self.assertEqual(response.status_code, 413)  # parça parça okuma sınırı
            self.assertEqual(set(self.tmp_root.iterdir()), before)  # iş oluşturulmadı


if __name__ == "__main__":
    unittest.main()
