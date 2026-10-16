"""Weryfikacja dwuetapowa kodami z aplikacji (Google Authenticator, Microsoft Authenticator, Authy…).

Kody TOTP według RFC 6238: HMAC-SHA1, 6 cyfr, co 30 sekund. Weryfikacja jest okresowa:
program pyta o kod na nowym komputerze i potem co wybraną liczbę dni.

Uwaga: to dodatkowa blokada w programie, a nie część szyfrowania. Plik sejfu nadal chroni
hasło główne. Kod nie wzmacnia szyfru, ale nie pozwala otworzyć programu komuś, kto zna
lub podejrzał hasło główne, a nie ma Twojego telefonu.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
STEP = 30
RECOVERY_COUNT = 8
PERIODS = [("Przy każdym odblokowaniu", 0), ("Raz dziennie", 1), ("Raz w tygodniu", 7), ("Raz na 2 tygodnie", 14),
           ("Raz na 30 dni", 30)]
DEFAULT_PERIOD = 7


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, t: float | None = None, digits: int = DIGITS, step: int = STEP, digest=hashlib.sha1) -> str:
    counter = int((time.time() if t is None else t) // step)
    mac = hmac.new(_key(secret), struct.pack(">Q", counter), digest).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(n).zfill(digits)


def verify(secret: str, code: str, t: float | None = None, window: int = 1) -> bool:
    """Sprawdza kod z tolerancją ±``window`` okresów (na różnicę zegarów telefonu i komputera)."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return False
    now = time.time() if t is None else t
    return any(hmac.compare_digest(code_at(secret, now + i * STEP), code) for i in range(-window, window + 1))


def otpauth_uri(secret: str, account: str, issuer: str = "Sejf") -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def group(secret: str) -> str:
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


# --- kody zapasowe -------------------------------------------------------------------------
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bez 0/O i 1/I


def new_recovery_codes(n: int = RECOVERY_COUNT) -> list[str]:
    return ["".join(secrets.choice(_ALPHABET) for _ in range(4)) + "-" + "".join(secrets.choice(_ALPHABET) for _ in range(4))
            for _ in range(n)]


def _norm_recovery(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def hash_recovery(code: str) -> str:
    return hashlib.sha256(("sejf-recovery:" + _norm_recovery(code)).encode()).hexdigest()


def use_recovery(cfg: dict, code: str) -> bool:
    """Sprawdza kod zapasowy i usuwa go z listy (każdy kod działa raz)."""
    h = hash_recovery(code)
    codes = cfg.get("recovery") or []
    for stored in codes:
        if hmac.compare_digest(stored, h):
            codes.remove(stored)
            return True
    return False


def new_config(secret: str, period_days: int, codes: list[str]) -> dict:
    return {"secret": secret, "period": int(period_days), "recovery": [hash_recovery(c) for c in codes],
            "enabled": int(time.time())}


# --- zapamiętanie urządzenia --------------------------------------------------------------
def device_mark(key: bytes, uid: str, secret: str, at: int) -> str:
    return hmac.new(key, f"sejf-2fa:{uid}:{secret}:{at}".encode(), hashlib.sha256).hexdigest()


def is_due(totp_cfg: dict | None, record: dict | None, key: bytes, uid: str, now: float | None = None) -> bool:
    """Czy trzeba teraz zapytać o kod? Tak: na nowym komputerze i po upływie wybranego okresu."""
    if not totp_cfg or not totp_cfg.get("secret"):
        return False
    period = int(totp_cfg.get("period", DEFAULT_PERIOD))
    if not record or period == 0:
        return True
    try:
        at = int(record["at"])
        ok = hmac.compare_digest(record["mac"], device_mark(key, uid, totp_cfg["secret"], at))
    except (KeyError, TypeError, ValueError):
        return True
    now = time.time() if now is None else now
    return not ok or now - at > period * 86400 or at > now + 300


def new_record(key: bytes, uid: str, secret: str, now: float | None = None) -> dict:
    at = int(time.time() if now is None else now)
    return {"at": at, "mac": device_mark(key, uid, secret, at)}
