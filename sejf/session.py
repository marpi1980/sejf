"""Otwarty sejf: odblokowanie, zapis, wykrywanie zmian z innych urządzeń.

Ta warstwa nie zależy od interfejsu, więc da się ją testować bez okien.
"""
from __future__ import annotations

import hmac
import os

from . import crypto, storage
from .vault import new_vault, normalize_vault, now_iso

MIN_PASSWORD = 8


class Session:
    def __init__(self) -> None:
        self.data: dict | None = None
        self.key: bytes | None = None
        self.salt: bytes | None = None
        self.iterations = crypto.ITERATIONS
        self.path: str | None = None
        self.mtime: int | None = None
        self.dirty = False

    @property
    def unlocked(self) -> bool:
        return self.data is not None

    @property
    def file_name(self) -> str:
        return os.path.basename(self.path) if self.path else ""

    # --- otwieranie -------------------------------------------------------
    @staticmethod
    def check_new_password(pw: str, repeat: str) -> str | None:
        if len(pw) < MIN_PASSWORD:
            return f"Hasło główne musi mieć co najmniej {MIN_PASSWORD} znaków."
        if pw != repeat:
            return "Hasła się różnią. Wpisz to samo hasło w obu polach."
        return None

    def create(self, path: str, password: str) -> None:
        salt = crypto.new_salt()
        self.salt, self.iterations = salt, crypto.ITERATIONS
        self.key = crypto.derive_key(password, salt, self.iterations)
        self.data = new_vault()
        self.path, self.mtime = path, None
        self.save(force=True)

    def unlock(self, path: str, password: str) -> None:
        text, mtime = storage.read_text(path)
        env = crypto.parse_envelope(text)
        key = crypto.derive_key(password, env.salt, env.iterations)
        data = normalize_vault(crypto.decrypt(env, key))
        self.data, self.key, self.salt, self.iterations = data, key, env.salt, env.iterations
        self.path, self.mtime, self.dirty = path, mtime, False

    def lock(self) -> None:
        self.data = None
        self.key = None
        self.dirty = False

    # --- zapis ------------------------------------------------------------
    def sealed(self) -> str:
        assert self.data is not None and self.key is not None and self.salt is not None
        return crypto.seal(self.data, self.key, self.salt, self.iterations)

    def mark_changed(self) -> None:
        assert self.data is not None
        self.data["modified"] = now_iso()
        self.dirty = True

    def save(self, force: bool = False) -> str:
        """Zapisuje sejf. Zwraca "saved" albo "conflict", gdy plik zmienił się na innym urządzeniu."""
        assert self.path
        if not force and self.mtime is not None and storage.mtime_of(self.path) not in (None, self.mtime):
            return "conflict"
        self.mtime = storage.write_atomic(self.path, self.sealed())
        self.dirty = False
        return "saved"

    def write_backup(self, path: str) -> None:
        storage.write_atomic(path, self.sealed())

    def check_external(self) -> str:
        """Sprawdza, czy plik zmienił się poza programem (np. synchronizacja z telefonu).

        Zwraca: "none", "reloaded" (wczytano zmiany), "conflict" (zmiany tu i tam),
        "relock" (zmieniono hasło główne na innym urządzeniu) albo "missing".
        """
        if not self.unlocked or not self.path:
            return "none"
        m = storage.mtime_of(self.path)
        if m is None:
            return "missing"
        if m == self.mtime:
            return "none"
        if self.dirty:
            return "conflict"
        try:
            text, m = storage.read_text(self.path)
            env = crypto.parse_envelope(text)
        except (OSError, crypto.VaultError):
            return "none"  # plik jest w trakcie synchronizacji; sprawdzimy później
        if env.salt != self.salt or env.iterations != self.iterations:
            self.lock()
            return "relock"
        try:
            self.data = normalize_vault(crypto.decrypt(env, self.key))
        except crypto.WrongPassword:
            self.lock()
            return "relock"
        self.mtime = m
        return "reloaded"

    def reload_from_file(self) -> None:
        """Porzuca zmiany w pamięci i wczytuje wersję z pliku tym samym kluczem."""
        text, m = storage.read_text(self.path)
        env = crypto.parse_envelope(text)
        if env.salt != self.salt or env.iterations != self.iterations:
            raise crypto.WrongPassword("Hasło główne zmieniono na innym urządzeniu.")
        self.data = normalize_vault(crypto.decrypt(env, self.key))
        self.mtime, self.dirty = m, False

    # --- hasło główne -----------------------------------------------------
    def verify_password(self, password: str) -> bool:
        return hmac.compare_digest(crypto.derive_key(password, self.salt, self.iterations), self.key)

    def change_password(self, current: str, new: str) -> None:
        if not self.verify_password(current):
            raise crypto.WrongPassword("Obecne hasło główne jest nieprawidłowe.")
        salt = crypto.new_salt()
        self.key = crypto.derive_key(new, salt, crypto.ITERATIONS)
        self.salt, self.iterations = salt, crypto.ITERATIONS
        self.mark_changed()
        self.save(force=True)
