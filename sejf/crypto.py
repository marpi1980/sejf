"""Szyfrowanie pliku sejfu.

Format jest zgodny z wersją przeglądarkową Sejfu (web/), więc ten sam plik
otwiera się w programie na Windows i w przeglądarce na telefonie.

Klucz: PBKDF2-HMAC-SHA256 z hasła głównego (Unicode NFC), 600 000 iteracji,
losowa 16-bajtowa sól. Dane: AES-256-GCM, losowy 12-bajtowy IV przy każdym
zapisie, dane dodatkowe (AAD) ``sejf-vault/1``.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import unicodedata
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FORMAT = "sejf-vault"
VERSION = 1
ITERATIONS = 600_000
AAD = b"sejf-vault/1"
SALT_BYTES = 16
IV_BYTES = 12


class VaultError(Exception):
    """Plik nie jest poprawnym plikiem sejfu."""


class WrongPassword(VaultError):
    """Hasło główne nie pasuje do pliku (albo plik został zmieniony)."""


@dataclass(frozen=True)
class Envelope:
    salt: bytes
    iterations: int
    iv: bytes
    data: bytes


def derive_key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    pw = unicodedata.normalize("NFC", password).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", pw, salt, iterations, 32)


def new_salt() -> bytes:
    return os.urandom(SALT_BYTES)


def parse_envelope(text: str) -> Envelope:
    not_vault = VaultError("To nie jest plik sejfu. Wybierz plik utworzony w programie Sejf.")
    try:
        o = json.loads(text)
    except (ValueError, TypeError):
        raise not_vault from None
    if not isinstance(o, dict) or o.get("format") != FORMAT:
        raise not_vault
    if int(o.get("version", 0)) > VERSION:
        raise VaultError("Ten plik pochodzi z nowszej wersji programu Sejf. Zaktualizuj program.")
    try:
        iterations = int(o["kdf"]["iterations"])
        env = Envelope(
            salt=base64.b64decode(o["kdf"]["salt"], validate=True),
            iterations=iterations,
            iv=base64.b64decode(o["cipher"]["iv"], validate=True),
            data=base64.b64decode(o["data"], validate=True),
        )
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise VaultError("Plik sejfu jest uszkodzony.") from None
    if not (100_000 <= iterations <= 10_000_000) or len(env.iv) != IV_BYTES or len(env.data) < 16:
        raise VaultError("Plik sejfu jest uszkodzony.")
    return env


def decrypt(env: Envelope, key: bytes) -> dict:
    try:
        plain = AESGCM(key).decrypt(env.iv, env.data, AAD)
    except InvalidTag:
        raise WrongPassword("Nieprawidłowe hasło główne.") from None
    return json.loads(plain.decode("utf-8"))


def seal(data: dict, key: bytes, salt: bytes, iterations: int = ITERATIONS) -> str:
    iv = os.urandom(IV_BYTES)
    plain = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct = AESGCM(key).encrypt(iv, plain, AAD)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return json.dumps(
        {
            "format": FORMAT,
            "version": VERSION,
            "app": "Sejf",
            "kdf": {"name": "PBKDF2-SHA256", "iterations": iterations, "salt": b64(salt)},
            "cipher": {"name": "AES-256-GCM", "iv": b64(iv)},
            "data": b64(ct),
        },
        indent=1,
    )
