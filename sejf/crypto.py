"""Szyfrowanie plików: osobistego sejfu i profili klientów.

Osobisty sejf (wersja 2):
  klucz = Argon2id(hasło główne w Unicode NFC, losowa sól 16 B, 64 MiB, 2 przebiegi, 1 wątek)
  dane  = AES-256-GCM(klucz, losowy IV 12 B, AAD ``sejf-vault/1``)
Starsze pliki (wersja 1) mają klucz z PBKDF2-HMAC-SHA256 i są przenoszone na Argon2id
przy pierwszym odblokowaniu.

Profil klienta (wersja 2):
  dane są zaszyfrowane losowym kluczem profilu K (AES-256-GCM, AAD ``sejf-profile/2:`` + id klucza).
  K jest osobno „opakowany” dla każdej osoby z dostępem (X25519 + HKDF-SHA256 + AES-256-GCM)
  i opcjonalnie dla hasła profilu (Argon2id). Odebranie komuś dostępu = nowy klucz K.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import unicodedata
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = 2
ITERATIONS = 600_000  # PBKDF2 w plikach wersji 1 (tylko odczyt i przenoszenie)
ARGON = {"name": "argon2id", "m": 65536, "t": 2, "p": 1}  # m w KiB = 64 MiB
SALT_BYTES = 16
IV_BYTES = 12
KINDS = {
    "vault": ("sejf-vault", b"sejf-vault/1"),
    "profile": ("sejf-profile", b"sejf-profile/1"),
}
FORMAT, AAD = KINDS["vault"]
WRAP_AAD = b"sejf-wrap/2:"


class VaultError(Exception):
    """Plik nie jest poprawnym plikiem programu Sejf."""


class WrongPassword(VaultError):
    """Hasło nie pasuje do pliku (albo plik został zmieniony)."""


class NoAccess(VaultError):
    """Profil nie ma klucza dla tej osoby, a hasło nie zostało podane albo jest wyłączone."""


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def unb64(s: str) -> bytes:
    return base64.b64decode(s, validate=True)


# --- wyprowadzanie klucza z hasła ----------------------------------------------------------
def new_kdf() -> dict:
    return {**ARGON, "salt": b64(os.urandom(SALT_BYTES))}


def legacy_kdf(salt: bytes, iterations: int = ITERATIONS) -> dict:
    return {"name": "PBKDF2-SHA256", "iterations": iterations, "salt": b64(salt)}


def kdf_is_current(kdf: dict) -> bool:
    return kdf.get("name") == "argon2id" and int(kdf.get("m", 0)) >= ARGON["m"] and int(kdf.get("t", 0)) >= ARGON["t"]


def _pw(password: str) -> bytes:
    return unicodedata.normalize("NFC", password).encode("utf-8")


def derive(password: str, kdf: dict) -> bytes:
    salt = unb64(kdf["salt"])
    if kdf.get("name") == "argon2id":
        return Argon2id(salt=salt, length=32, iterations=int(kdf["t"]), lanes=int(kdf["p"]),
                        memory_cost=int(kdf["m"])).derive(_pw(password))
    return hashlib.pbkdf2_hmac("sha256", _pw(password), salt, int(kdf["iterations"]), 32)


def derive_key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    """PBKDF2 (pliki w wersji 1)."""
    return derive(password, legacy_kdf(salt, iterations))


def new_salt() -> bytes:
    return os.urandom(SALT_BYTES)


def _check_kdf(k: dict) -> dict:
    if not isinstance(k, dict) or "salt" not in k:
        raise ValueError
    unb64(k["salt"])
    if k.get("name") == "argon2id":
        m, t, p = int(k["m"]), int(k["t"]), int(k["p"])
        if not (8192 <= m <= 4_194_304 and 1 <= t <= 20 and 1 <= p <= 16):
            raise ValueError
        return {"name": "argon2id", "m": m, "t": t, "p": p, "salt": k["salt"]}
    it = int(k["iterations"])
    if not 100_000 <= it <= 10_000_000:
        raise ValueError
    return {"name": "PBKDF2-SHA256", "iterations": it, "salt": k["salt"]}


# --- nagłówek pliku ------------------------------------------------------------------------
@dataclass(frozen=True)
class Envelope:
    kind: str
    version: int
    iv: bytes
    data: bytes
    kdf: dict | None = None          # sejf i profil w wersji 1
    keyid: bytes | None = None       # profil w wersji 2
    recipients: list = field(default_factory=list)

    @property
    def salt(self) -> bytes | None:
        return unb64(self.kdf["salt"]) if self.kdf else None

    @property
    def iterations(self) -> int | None:
        return int(self.kdf.get("iterations", 0)) if self.kdf else None


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
    try:
        version = int(o.get("version", 1))
    except (TypeError, ValueError):
        raise VaultError("Plik jest uszkodzony.") from None
    if version > VERSION:
        raise VaultError("Ten plik pochodzi z nowszej wersji programu Sejf. Zaktualizuj program.")
    try:
        iv = unb64(o["cipher"]["iv"])
        data = unb64(o["data"])
        if found == "profile" and version >= 2:
            keys = o["keys"]
            recips = [r for r in keys["recipients"] if isinstance(r, dict) and r.get("kid")]
            env = Envelope(found, version, iv, data, keyid=unb64(keys["keyid"]), recipients=recips)
        else:
            env = Envelope(found, version, iv, data, kdf=_check_kdf(o["kdf"]))
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise VaultError("Plik jest uszkodzony.") from None
    if len(env.iv) != IV_BYTES or len(env.data) < 16:
        raise VaultError("Plik jest uszkodzony.")
    return env


def _aad(env_kind: str, version: int, keyid: bytes | None) -> bytes:
    if env_kind == "profile" and version >= 2:
        return b"sejf-profile/2:" + keyid
    return KINDS[env_kind][1]


def decrypt(env: Envelope, key: bytes) -> dict:
    try:
        plain = AESGCM(key).decrypt(env.iv, env.data, _aad(env.kind, env.version, env.keyid))
    except InvalidTag:
        raise WrongPassword("Nieprawidłowe hasło główne." if env.kind == "vault" else
                            "Nieprawidłowe hasło profilu.") from None
    return json.loads(plain.decode("utf-8"))


def _dump(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def seal(data: dict, key: bytes, salt_or_kdf, iterations: int = ITERATIONS, kind: str = "vault") -> str:
    """Szyfruje sejf (albo profil w wersji 1). ``salt_or_kdf``: słownik parametrów albo sama sól PBKDF2."""
    kdf = salt_or_kdf if isinstance(salt_or_kdf, dict) else legacy_kdf(salt_or_kdf, iterations)
    version = 2 if kdf.get("name") == "argon2id" else 1
    iv = os.urandom(IV_BYTES)
    ct = AESGCM(key).encrypt(iv, _dump(data), KINDS[kind][1])
    return json.dumps({"format": KINDS[kind][0], "version": version, "app": "Sejf", "kdf": kdf,
                       "cipher": {"name": "AES-256-GCM", "iv": b64(iv)}, "data": b64(ct)}, indent=1)


def seal_profile(data: dict, key: bytes, keyid: bytes, recipients: list[dict]) -> str:
    if not recipients:
        raise VaultError("Profil musi mieć co najmniej jedną osobę albo hasło dostępu.")
    iv = os.urandom(IV_BYTES)
    ct = AESGCM(key).encrypt(iv, _dump(data), b"sejf-profile/2:" + keyid)
    return json.dumps({"format": "sejf-profile", "version": 2, "app": "Sejf",
                       "keys": {"keyid": b64(keyid), "recipients": recipients},
                       "cipher": {"name": "AES-256-GCM", "iv": b64(iv)}, "data": b64(ct)}, indent=1)


def new_profile_key() -> tuple[bytes, bytes]:
    return os.urandom(32), os.urandom(16)


# --- tożsamość osoby i opakowywanie klucza profilu -------------------------------------
def kid_of(pub: bytes) -> str:
    return hashlib.sha256(b"sejf-id:" + pub).hexdigest()[:16]


def fingerprint(kid: str) -> str:
    return " ".join(kid[i:i + 4].upper() for i in range(0, len(kid), 4))


def new_identity(name: str) -> dict:
    priv = X25519PrivateKey.generate()
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
    raw_priv = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {"kid": kid_of(raw_pub), "name": name, "pub": b64(raw_pub), "priv": b64(raw_priv)}


def identity_code(identity: dict) -> str:
    """Kod, który osoba przekazuje właścicielowi profilu, żeby ten dodał ją do profilu."""
    name = base64.urlsafe_b64encode(identity["name"].encode("utf-8")).decode().rstrip("=")
    pub = base64.urlsafe_b64encode(unb64(identity["pub"])).decode().rstrip("=")
    check = hashlib.sha256(f"{pub}.{name}".encode()).hexdigest()[:6]
    return f"SEJF1.{pub}.{name}.{check}"


def parse_identity_code(code: str) -> dict:
    bad = VaultError("To nie jest poprawny kod osoby. Skopiuj cały kod z okna „Mój kod” u tej osoby.")
    parts = "".join((code or "").split()).split(".")
    if len(parts) != 4 or parts[0] != "SEJF1":
        raise bad
    _, pub, name, check = parts
    if hashlib.sha256(f"{pub}.{name}".encode()).hexdigest()[:6] != check:
        raise bad
    try:
        raw_pub = base64.urlsafe_b64decode(pub + "=" * (-len(pub) % 4))
        nm = base64.urlsafe_b64decode(name + "=" * (-len(name) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise bad from None
    if len(raw_pub) != 32:
        raise bad
    return {"kid": kid_of(raw_pub), "name": nm.strip() or "Bez nazwy", "pub": b64(raw_pub)}


def _wrap_key(shared: bytes, keyid: bytes, epk: bytes, pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=keyid, info=b"sejf-wrap/2" + epk + pub).derive(shared)


def wrap_for(key: bytes, keyid: bytes, pub_b64: str) -> dict:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    pub = unb64(pub_b64)
    eph = X25519PrivateKey.generate()
    epk = eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    wk = _wrap_key(eph.exchange(X25519PublicKey.from_public_bytes(pub)), keyid, epk, pub)
    iv = os.urandom(IV_BYTES)
    return {"kid": kid_of(pub), "epk": b64(epk), "iv": b64(iv),
            "wk": b64(AESGCM(wk).encrypt(iv, key, WRAP_AAD + keyid))}


def unwrap_identity(env: Envelope, identity: dict) -> bytes | None:
    rec = next((r for r in env.recipients if r.get("kid") == identity["kid"]), None)
    if rec is None:
        return None
    try:
        priv = X25519PrivateKey.from_private_bytes(unb64(identity["priv"]))
        epk = unb64(rec["epk"])
        wk = _wrap_key(priv.exchange(X25519PublicKey.from_public_bytes(epk)), env.keyid, epk, unb64(identity["pub"]))
        return AESGCM(wk).decrypt(unb64(rec["iv"]), unb64(rec["wk"]), WRAP_AAD + env.keyid)
    except (InvalidTag, KeyError, ValueError, binascii.Error):
        return None


def wrap_password(key: bytes, keyid: bytes, password: str) -> dict:
    kdf = new_kdf()
    iv = os.urandom(IV_BYTES)
    return {"kid": "password", "kdf": kdf, "iv": b64(iv),
            "wk": b64(AESGCM(derive(password, kdf)).encrypt(iv, key, WRAP_AAD + keyid))}


def has_password(env: Envelope) -> bool:
    return any(r.get("kid") == "password" for r in env.recipients)


def unwrap_password(env: Envelope, password: str) -> bytes:
    rec = next((r for r in env.recipients if r.get("kid") == "password"), None)
    if rec is None:
        raise NoAccess("Dostęp do tego profilu hasłem jest wyłączony. Poproś osobę z dostępem, żeby dodała Cię "
                       "do profilu Twoim kodem.")
    try:
        kdf = _check_kdf(rec["kdf"])
        return AESGCM(derive(password, kdf)).decrypt(unb64(rec["iv"]), unb64(rec["wk"]), WRAP_AAD + env.keyid)
    except InvalidTag:
        raise WrongPassword("Nieprawidłowe hasło profilu.") from None
    except (KeyError, ValueError, binascii.Error):
        raise VaultError("Plik jest uszkodzony.") from None
