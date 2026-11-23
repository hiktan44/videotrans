import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import ai_gateway
from studio_api.jobs import copy_upload, dubbing_job, store, transcribe_job, translate_job
from studio_api.security import (
    ALLOWED_AUDIO_FORMATS,
    PLACEHOLDER_SESSION_SECRETS,
    FailureLimiter,
    is_private_job_file,
    max_upload_bytes,
    normalize_media_url,
    safe_upload_suffix,
    validate_media_url,
)


app = FastAPI(title="Voice-Pro Studio API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("VOICE_PRO_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


@app.middleware("http")
async def guard_job_requests(request: Request, call_next):
    # FastAPI çok parçalı gövdeyi Depends(require_auth) çalışmadan önce ayrıştırır; girişsiz
    # istekler büyük yüklemeyi diske yazdırmasın diye iş uçlarında oturum ve boyut erkenden denetlenir.
    if request.method == "POST" and request.url.path.startswith("/api/jobs/"):
        if not _verify_session(request.cookies.get(AUTH_COOKIE)):
            return JSONResponse({"detail": "Login required"}, status_code=401)
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > max_upload_bytes() + 1024 * 1024:
            return JSONResponse({"detail": "Upload is too large"}, status_code=413)
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response

AUTH_COOKIE = "videotrans_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7
REDACTED_JOB_PARAMS = {"input_path", "source_text", "subtitle_text"}
# Giriş denemesi sınırı: IP başına 10, toplamda 100 hatalı deneme / 15 dk (IP başlığı taklit edilebilir).
LOGIN_LIMITER = FailureLimiter(per_key=10, total=100, window_seconds=15 * 60)


def _public_job(job: dict) -> dict:
    public = dict(job)
    params = dict(public.get("params") or {})
    for key in REDACTED_JOB_PARAMS:
        if key in params:
            params[key] = "[redacted]"
    public["params"] = params
    # Yığın izi (iç yollar, kod) diskteki job.json'da kalır, istemciye gönderilmez.
    outputs = dict(public.get("outputs") or {})
    outputs.pop("traceback", None)
    public["outputs"] = outputs
    return public


def _app_password() -> str:
    return os.getenv("VIDEOTRANS_APP_PASSWORD", "")


def _session_secret() -> str:
    configured = os.getenv("VIDEOTRANS_SESSION_SECRET", "")
    if configured.strip() in PLACEHOLDER_SESSION_SECRETS:
        configured = ""
    return configured or _app_password() or "videotrans-dev"


def _auth_enabled() -> bool:
    return bool(_app_password())


def _sign_session(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    signature = hmac.new(_session_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _verify_session(token: str | None) -> bool:
    if not _auth_enabled():
        return True
    if not token or "." not in token:
        return False
    body, signature = token.rsplit(".", 1)
    expected = hmac.new(_session_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode()).decode())
    except Exception:
        return False
    return payload.get("sub") == "videotrans" and int(payload.get("exp", 0)) > int(time.time())


def require_auth(request: Request) -> None:
    if not _verify_session(request.cookies.get(AUTH_COOKIE)):
        raise HTTPException(status_code=401, detail="Login required")


@app.get("/health")
def health():
    return {"ok": True, "ai": ai_gateway.status()}


@app.get("/api/auth/session")
def auth_session(request: Request):
    return {"enabled": _auth_enabled(), "authenticated": _verify_session(request.cookies.get(AUTH_COOKIE))}


@app.post("/api/auth/login")
def auth_login(request: Request, response: Response, password: str = Form(...)):
    if not _auth_enabled():
        return {"enabled": False, "authenticated": True}
    client_key = request.client.host if request.client else "unknown"
    retry_after = LOGIN_LIMITER.retry_after(client_key)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    if not hmac.compare_digest(password.encode("utf-8"), _app_password().encode("utf-8")):
        LOGIN_LIMITER.record_failure(client_key)
        raise HTTPException(status_code=401, detail="Invalid password")
    LOGIN_LIMITER.reset(client_key)
    token = _sign_session({"sub": "videotrans", "exp": int(time.time()) + SESSION_MAX_AGE, "nonce": secrets.token_hex(8)})
    response.set_cookie(
        AUTH_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=os.getenv("VIDEOTRANS_SECURE_COOKIE", "1") != "0",
        samesite="lax",
    )
    return {"enabled": True, "authenticated": True}


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(AUTH_COOKIE)
    return {"authenticated": False}


@app.post("/api/jobs/transcribe")
async def create_transcribe_job(
    _: None = Depends(require_auth),
    file: UploadFile | None = File(None),
    youtube_url: str = Form(""),
    video_quality: str = Form("good"),
    provider: str = Form("openai"),
    model: str = Form("gpt-4o-transcribe-diarize"),
    language: str = Form("Automatic Detection"),
    audio_format: str = Form("mp3"),
):
    if not file and not youtube_url.strip():
        raise HTTPException(status_code=400, detail="Upload a file or enter a media URL")
    if audio_format not in ALLOWED_AUDIO_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported audio format")
    if not file:
        # SSRF: yalnız http/https ve herkese açık internet adresine çözülen sunucular.
        youtube_url = normalize_media_url(youtube_url)
        url_error = await run_in_threadpool(validate_media_url, youtube_url)
        if url_error:
            raise HTTPException(status_code=400, detail=url_error)

    tmp_path = None
    try:
        if file:
            # Yükleme belleğe alınmadan parça parça diske yazılır; üst sınır VIDEOTRANS_MAX_UPLOAD_MB.
            limit = max_upload_bytes()
            size = 0
            with tempfile.NamedTemporaryFile(delete=False, suffix=safe_upload_suffix(file.filename)) as tmp:
                tmp_path = tmp.name
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(status_code=413, detail="Upload is too large")
                    tmp.write(chunk)

        job = store.create(
            "transcribe_upload",
            {
                "filename": file.filename if file else None,
                "youtube_url": youtube_url.strip() or None,
                "video_quality": video_quality,
                "provider": provider,
                "model": model,
                "language": language,
                "audio_format": audio_format,
            },
        )

        if file:
            input_path = copy_upload(job["id"], tmp_path, file.filename or "upload.bin")
            job["params"]["input_path"] = str(input_path)
            store.save(job)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    store.update(job["id"], status="queued", message="Queued")
    from studio_api.jobs import executor

    def report(progress: float, message: str) -> None:
        store.update(job["id"], progress=progress, message=message)

    def runner() -> None:
        store.update(job["id"], status="running", progress=0.02, message="Starting")
        try:
            outputs = transcribe_job(store.get(job["id"]), report)
            store.update(job["id"], status="completed", progress=1.0, message="Completed", outputs=outputs)
        except Exception as exc:
            import traceback

            store.update(
                job["id"],
                status="failed",
                error=str(exc),
                message="Failed",
                outputs={"traceback": traceback.format_exc()},
            )

    executor.submit(runner)
    return _public_job(store.get(job["id"]))


@app.post("/api/jobs/translate")
async def create_translate_job(
    _: None = Depends(require_auth),
    source_text: str = Form(...),
    source_language: str = Form("Automatic Detection"),
    target_language: str = Form("Turkish"),
    provider: str = Form("auto"),
):
    job = store.create(
        "translate",
        {
            "source_language": source_language,
            "target_language": target_language,
            "provider": provider,
            "source_text": source_text,
        },
    )

    from studio_api.jobs import executor

    def report(progress: float, message: str) -> None:
        store.update(job["id"], progress=progress, message=message)

    def runner() -> None:
        store.update(job["id"], status="running", progress=0.02, message="Starting")
        try:
            outputs = translate_job(store.get(job["id"]), report)
            store.update(job["id"], status="completed", progress=1.0, message="Completed", outputs=outputs)
        except Exception as exc:
            import traceback

            store.update(
                job["id"],
                status="failed",
                error=str(exc),
                message="Failed",
                outputs={"traceback": traceback.format_exc()},
            )

    executor.submit(runner)
    return _public_job(store.get(job["id"]))


@app.post("/api/jobs/dubbing")
async def create_dubbing_job(
    _: None = Depends(require_auth),
    subtitle_text: str = Form(...),
    media_job_id: str = Form(""),
    media_href: str = Form(""),
    provider: str = Form("edge"),
    voice_name: str = Form("tr-TR-EmelNeural"),
    speed: float = Form(1.0),
    audio_format: str = Form("mp3"),
):
    if audio_format not in ALLOWED_AUDIO_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported audio format")
    job = store.create(
        "dubbing",
        {
            "subtitle_text": subtitle_text,
            "media_job_id": media_job_id or None,
            "media_href": media_href or None,
            "provider": provider,
            "voice_name": voice_name,
            "speed": speed,
            "audio_format": audio_format,
        },
    )

    from studio_api.jobs import executor

    def report(progress: float, message: str) -> None:
        store.update(job["id"], progress=progress, message=message)

    def runner() -> None:
        store.update(job["id"], status="running", progress=0.02, message="Starting")
        try:
            outputs = dubbing_job(store.get(job["id"]), report)
            store.update(job["id"], status="completed", progress=1.0, message="Completed", outputs=outputs)
        except Exception as exc:
            import traceback

            store.update(
                job["id"],
                status="failed",
                error=str(exc),
                message="Failed",
                outputs={"traceback": traceback.format_exc()},
            )

    executor.submit(runner)
    return _public_job(store.get(job["id"]))


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, _: None = Depends(require_auth)):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _ensure_media_outputs(job)
    return _public_job(job)


@app.get("/api/jobs/{job_id}/files/{filename}")
def get_job_file(job_id: str, filename: str, _: None = Depends(require_auth)):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # job.json (yığın izi, iç yollar) ve çerez dosyası gibi iç dosyalar sunulmaz.
    if is_private_job_file(filename):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        path = store.output_path(job_id, filename)
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


def _ensure_media_outputs(job):
    outputs = job.get("outputs") or {}
    if outputs.get("media"):
        return job

    input_path = job.get("params", {}).get("input_path")
    if input_path:
        path = Path(input_path)
        if path.exists():
            outputs["media"] = f"/api/jobs/{job['id']}/files/{path.name}"

    job_dir = store.job_dir(job["id"])
    for path in job_dir.iterdir() if job_dir.exists() else []:
        if path.suffix.lower() in {".mp3", ".wav", ".flac", ".m4a"} and path.name.endswith(f"_audio{path.suffix}"):
            outputs.setdefault("audio", f"/api/jobs/{job['id']}/files/{path.name}")

    if outputs != job.get("outputs"):
        job["outputs"] = outputs
        store.save(job)
    return job


WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
