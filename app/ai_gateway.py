"""Merkezi AI geçidi (kendi LiteLLM sunucumuz) güzergâhları.

AI_GATEWAY_URL + AI_GATEWAY_KEY tanımlıysa OpenAI istekleri aynı gövdeyle önce geçide, düşerse
AI_GATEWAY_URL_YEDEK'e, en son doğrudan OpenAI'ye gider:

* ``https://api.openai.com/v1/audio/transcriptions`` → ``<geçit>/v1/audio/transcriptions``
* ``https://api.openai.com/v1/audio/speech`` → ``<geçit>/v1/audio/speech``

Model adı geçitteki takma ada çevrilir (``whisper-1`` → ``whisper-1-videotrans``); takma adlar
uygulamanın kendi OpenAI anahtarını taşır, faturalama değişmez. AI_GATEWAY_MODELS (virgüllü) doluysa
yalnız o modeller geçide gider (ör. geçitten geçemeyen diarize çıkarılabilir). Z.ai (ASR + agents
çeviri) OpenAI-uyumlu olmadığı için geçit dışıdır.

Geçiş kuralı: bağlantı hatası ve 401/403/404/429/5xx sonraki güzergâha geçer; 400/422 istek
hatasıdır, tekrarlanmaz. Okuma zaman aşımı (uzun transkripsiyon) yeniden denenmez, hata olarak
yükselir — aksi hâlde 900 sn'lik bekleme üç güzergâhta katlanırdı.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

import requests
import structlog

logger = structlog.get_logger()

OPENAI_ORIGIN = "https://api.openai.com/v1"
DEFAULT_SUFFIX = "-videotrans"


@dataclass(frozen=True)
class Route:
    name: str  # "gecit" | "gecit-yedek" | "dogrudan"
    url: str
    api_key: str
    model_suffix: str = ""


def _clean(value: Optional[str]) -> str:
    return (value or "").strip().strip("\"'").strip()


def _gateway_bases(env: Mapping[str, str]) -> list:
    bases = []
    for name, key in (("gecit", "AI_GATEWAY_URL"), ("gecit-yedek", "AI_GATEWAY_URL_YEDEK")):
        base = _clean(env.get(key)).rstrip("/")
        if base.startswith("https://") and all(base != existing for _, existing in bases):
            bases.append((name, base))
    return bases


def enabled_providers(env: Mapping[str, str]) -> set:
    """AI_GATEWAY_PROVIDERS (virgüllü); boşsa openai. Şimdilik yalnız openai desteklenir."""
    raw = _clean(env.get("AI_GATEWAY_PROVIDERS"))
    values = {item.strip().lower() for item in raw.split(",")} if raw else {"openai"}
    return values & {"openai"}


def enabled_models(env: Mapping[str, str]) -> Optional[set]:
    """AI_GATEWAY_MODELS boşsa None (hepsi geçide gider)."""
    raw = _clean(env.get("AI_GATEWAY_MODELS"))
    return {item.strip() for item in raw.split(",") if item.strip()} if raw else None


def configured(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return bool(_clean(env.get("AI_GATEWAY_KEY")) and _gateway_bases(env))


def status(env: Optional[Mapping[str, str]] = None) -> dict:
    """/health için: adres ve anahtar vermeden geçit durumu."""
    env = os.environ if env is None else env
    models = enabled_models(env)
    return {
        "gecit": configured(env),
        "yedek": len(_gateway_bases(env)) > 1,
        "saglayicilar": sorted(enabled_providers(env)) if configured(env) else [],
        "modeller": sorted(models) if models else "hepsi",
    }


def routes(url: str, api_key: str, *, provider: str = "openai", model: str = "", env=None) -> list:
    """Bir istek için sıralı güzergâhlar; sonuncusu her zaman doğrudan sağlayıcıdır."""
    env = os.environ if env is None else env
    found = []
    key = _clean(env.get("AI_GATEWAY_KEY"))
    models = enabled_models(env)
    if (
        key
        and provider in enabled_providers(env)
        and url.startswith(OPENAI_ORIGIN + "/")
        and (models is None or model in models)
    ):
        suffix = _clean(env.get("AI_GATEWAY_MODEL_SUFFIX")) or DEFAULT_SUFFIX
        for name, base in _gateway_bases(env):
            found.append(Route(name, f"{base}/v1{url[len(OPENAI_ORIGIN):]}", key, suffix))
    found.append(Route("dogrudan", url, api_key))
    return found


def gateway_model(model: str, suffix: str) -> str:
    """Model adını geçit takma adına çevirir (zaten çevrilmişse dokunmaz)."""
    if not suffix or not model or model.endswith(suffix):
        return model
    return f"{model}{suffix}"


def should_fail_over(status_code: int) -> bool:
    return not (200 <= status_code < 300 or status_code in (400, 422))


def post(
    url: str,
    *,
    api_key: str,
    headers: Optional[dict] = None,
    json: Optional[dict] = None,
    data: Optional[dict] = None,
    file_path: Optional[str] = None,
    timeout: float = 180,
    provider: str = "openai",
    env=None,
    session=requests,
) -> requests.Response:
    """Güzergâhları sırayla dener. Çağıranın sözlükleri değişmez; dosya her denemede baştan açılır."""
    body = json if json is not None else (data or {})
    model = body.get("model", "")
    found = routes(url, api_key, provider=provider, model=model, env=env)
    for index, route in enumerate(found):
        last = index == len(found) - 1
        request_headers = dict(headers or {})
        request_headers["Authorization"] = f"Bearer {route.api_key}"
        payload = dict(body)
        if model:
            payload["model"] = gateway_model(model, route.model_suffix)
        try:
            if file_path:
                with open(file_path, "rb") as handle:
                    response = session.post(
                        route.url,
                        headers=request_headers,
                        files={"file": (os.path.basename(file_path), handle)},
                        data=payload,
                        timeout=timeout,
                    )
            elif json is not None:
                response = session.post(route.url, headers=request_headers, json=payload, timeout=timeout)
            else:
                response = session.post(route.url, headers=request_headers, data=payload, timeout=timeout)
        except requests.exceptions.ConnectionError as exc:
            if last:
                raise
            logger.warning(f"AI geçidi {route.name} bağlantı hatası, sonraki güzergâh: {type(exc).__name__}")
            continue
        if last or not should_fail_over(response.status_code):
            return response
        logger.warning(f"AI geçidi {route.name} {response.status_code}, sonraki güzergâh")
    raise RuntimeError("AI güzergâhı bulunamadı")  # pragma: no cover - doğrudan güzergâh her zaman var
