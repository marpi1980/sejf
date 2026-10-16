"""Szyfrowanie plików: osobistego sejfu i profili klientów.

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

VERSION = 1
ITERATIONS = 600_000
# rodzaj pliku → (znacznik formatu, dane dodatkowe AAD)
KINDS = {
    "vault": ("sejf-vault", b"sejf-vault/1"),      # osobisty sejf
    "profile": ("sejf-profile", b"sejf-profile/1"),  # profil klienta
}
FORMAT, AAD = KINDS["vault"]
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
    kind: str = "vault"


def derive_key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    pw = unicodedata.normalize("NFC", password).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", pw, salt, iterations, 32)


def new_salt() -> bytes:
    return os.urandom(SALT_BYTES)


NOT_FILE = {
    "vault": "To nie jest plik sejfu. Wybierz plik utworzony w programie Sejf.",
    "profile": "To nie jest plik profilu klienta. Wybierz plik .sejfklient utworzony w programie Sejf.",
    None: "To nie jest plik programu Sejf.",
}


def parse_envelope(text: str, kind: str | None = "vault") -> Envelope:
    """Odczytuje nagłówek pliku. ``kind`` wymusza rodzaj pliku (None = dowolny)."""
    not_vault = VaultError(NOT_FILE[kind])
    try:
        o = json.loads(text)
    except (ValueError, TypeError):
        raise not_vault from None
    found = next((k for k, (fmt, _) in KINDS.items() if isinstance(o, dict) and o.get("format") == fmt), None)
    if found is None or (kind is not None and found != kind):
        if found == "profile" and kind == "vault":
            raise VaultError("To jest plik profilu klienta, nie osobisty sejf. Otwórz swój plik sejfu, "
                             "a profil dodaj potem w programie.")
        if found == "vault" and kind == "profile":
            raise VaultError("To jest plik osobistego sejfu, nie profil klienta.")
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
            kind=found,
        )
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise VaultError("Plik sejfu jest uszkodzony.") from None
    if not (100_000 <= iterations <= 10_000_000) or len(env.iv) != IV_BYTES or len(env.data) < 16:
        raise VaultError("Plik sejfu jest uszkodzony.")
    return env


def decrypt(env: Envelope, key: bytes) -> dict:
    try:
        plain = AESGCM(key).decrypt(env.iv, env.data, KINDS[env.kind][1])
    except InvalidTag:
        raise WrongPassword("Nieprawidłowe hasło główne." if env.kind == "vault" else
                            "Nieprawidłowe hasło profilu.") from None
    return json.loads(plain.decode("utf-8"))


def seal(data: dict, key: bytes, salt: bytes, iterations: int = ITERATIONS, kind: str = "vault") -> str:
    fmt, aad = KINDS[kind]
    iv = os.urandom(IV_BYTES)
    plain = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct = AESGCM(key).encrypt(iv, plain, aad)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return json.dumps(
        {
            "format": fmt,
            "version": VERSION,
            "app": "Sejf",
            "kdf": {"name": "PBKDF2-SHA256", "iterations": iterations, "salt": b64(salt)},
            "cipher": {"name": "AES-256-GCM", "iv": b64(iv)},
            "data": b64(ct),
        },
        indent=1,
    )
