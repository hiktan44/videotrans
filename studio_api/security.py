"""Studio API girdi doğrulamaları ve basit süreç içi hız sınırlayıcı.

Ağır bağımlılık içermez; tek başına test edilebilir.
"""

import ipaddress
import os
import re
import socket
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, Optional
from urllib.parse import urlsplit


JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
UPLOAD_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")

ALLOWED_AUDIO_FORMATS = frozenset({"mp3", "wav", "flac", "ogg", "m4a", "aac", "opus"})

# İş klasöründe olup indirilmemesi gereken dosyalar (iç durum ve sırlar).
PRIVATE_JOB_FILES = frozenset({"job.json", "youtube_cookies.txt"})

# .env.example içindeki herkese açık yer tutucu; canlıda kullanılırsa oturum imzası taklit edilebilir.
PLACEHOLDER_SESSION_SECRETS = frozenset({"change_this_long_random_secret"})


def is_valid_job_id(job_id: Optional[str]) -> bool:
    return bool(job_id) and bool(JOB_ID_RE.fullmatch(job_id))


def safe_upload_suffix(filename: Optional[str], default: str = ".bin") -> str:
    """Yüklenen dosya adından yalnızca güvenli bir uzantı (ör. ``.mp4``) alır."""
    suffix = Path(filename or "").suffix
    return suffix if UPLOAD_SUFFIX_RE.fullmatch(suffix) else default


def is_private_job_file(filename: str) -> bool:
    return filename in PRIVATE_JOB_FILES or filename.endswith(".tmp")


def max_upload_bytes() -> int:
    try:
        megabytes = int(os.getenv("VIDEOTRANS_MAX_UPLOAD_MB", "2048"))
    except ValueError:
        megabytes = 2048
    return max(1, megabytes) * 1024 * 1024


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


def normalize_media_url(url: str) -> str:
    """Şemasız girişi (``youtube.com/watch?v=...``) ``https://`` ile tamamlar."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url.lstrip("/")
    return url


def validate_media_url(url: str) -> Optional[str]:
    """Medya URL'si geçerliyse None, değilse kullanıcıya gösterilecek hata metnini döndürür.

    Yalnız http/https kabul edilir ve sunucu adı yerel/özel ağ adresine çözülmemelidir (SSRF).
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "Invalid media URL"
    if parts.scheme.lower() not in ("http", "https"):
        return "Only http and https media URLs are supported"
    host = parts.hostname
    if not host:
        return "Invalid media URL"
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError:
        return "Invalid media URL"
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return "Media URL host could not be resolved"
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_is_public_address(address) for address in addresses):
        return "Media URL must point to a public internet address"
    return None


class FailureLimiter:
    """Pencere içindeki başarısız deneme sayısını anahtar başına (ör. IP) ve toplamda sınırlar."""

    def __init__(self, per_key: int, total: int, window_seconds: float):
        self.per_key = per_key
        self.total = total
        self.window = window_seconds
        self._lock = threading.Lock()
        self._by_key: Dict[str, Deque[float]] = {}
        self._all: Deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        while self._all and self._all[0] <= cutoff:
            self._all.popleft()
        for key in list(self._by_key):
            entries = self._by_key[key]
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if not entries:
                del self._by_key[key]

    def retry_after(self, key: str) -> int:
        """Engelliyse kalan saniye, değilse 0."""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            entries = self._by_key.get(key)
            if entries and len(entries) >= self.per_key:
                return max(1, int(entries[0] + self.window - now) + 1)
            if len(self._all) >= self.total:
                return max(1, int(self._all[0] + self.window - now) + 1)
            return 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._by_key.setdefault(key, deque()).append(now)
            self._all.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._by_key.pop(key, None)
