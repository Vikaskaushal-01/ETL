"""
Security primitives shared across the API: password hashing, signed session
tokens, filesystem path confinement and outbound URL (SSRF) validation.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from typing import Optional
from urllib.parse import urlparse

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DEFAULT_ADMIN_EMAIL = "admin@controlai.net"
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", str(12 * 3600)))
PBKDF2_ITERATIONS = 200_000


def is_production() -> bool:
    return os.getenv("ENV", "development").lower() == "production"


def _load_secret_key() -> bytes:
    """SECRET_KEY env var, else a random key persisted in the project root so sessions survive restarts."""
    env_key = os.getenv("SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")
    key_path = os.path.join(PROJECT_ROOT, ".secret_key")
    try:
        if os.path.exists(key_path):
            with open(key_path, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key.encode("utf-8")
        key = secrets.token_hex(32)
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(key)
        return key.encode("utf-8")
    except OSError:
        return secrets.token_hex(32).encode("utf-8")


SECRET_KEY = _load_secret_key()


# --- Passwords -------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def is_password_hashed(stored: str) -> bool:
    return bool(stored) and stored.startswith("pbkdf2_sha256$")


def verify_password(password: str, stored: str) -> bool:
    """Verifies against a PBKDF2 hash; also accepts legacy plaintext rows so they can be upgraded on login."""
    if not stored:
        return False
    if not is_password_hashed(stored):
        return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))
    try:
        _, iterations, salt, expected = stored.split("$", 3)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


# --- Session tokens --------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_token(email: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    payload = _b64(json.dumps({"sub": email, "exp": int(time.time()) + ttl}).encode("utf-8"))
    sig = _b64(hmac.new(SECRET_KEY, payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: Optional[str]) -> Optional[str]:
    """Returns the email encoded in a valid, unexpired token, else None."""
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(SECRET_KEY, payload.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("exp", 0) < time.time():
        return None
    return data.get("sub")


# --- Filesystem confinement ------------------------------------------------

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ \-()]+")
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def sanitize_filename(filename: Optional[str], default: str = "dataset") -> str:
    """Strips directory components and unsafe characters from a user supplied filename."""
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = _SAFE_NAME_RE.sub("_", name).strip(" .")
    return name[:200] or default


def is_valid_batch_id(batch_id: Optional[str]) -> bool:
    return bool(batch_id) and bool(BATCH_ID_RE.match(batch_id))


def is_within(path: str, base: str) -> bool:
    """True when `path` resolves inside directory `base` (no prefix-matching tricks)."""
    try:
        path_abs = os.path.normcase(os.path.realpath(path))
        base_abs = os.path.normcase(os.path.realpath(base))
        return os.path.commonpath([path_abs, base_abs]) == base_abs
    except ValueError:
        return False


# --- Outbound URL validation (SSRF) ---------------------------------------

def validate_public_url(url: str) -> str:
    """Rejects non-HTTP(S) URLs and hosts that resolve to private, loopback or link-local addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only absolute http(s) URLs are allowed.")
    if os.getenv("ALLOW_PRIVATE_URLS", "false").lower() == "true":
        return url
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise ValueError(f"Could not resolve host '{parsed.hostname}'.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("URLs pointing to private or internal network addresses are not allowed.")
    return url


# --- API keys ---------------------------------------------------------------

API_KEY_PREFIX = "cai_"


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
