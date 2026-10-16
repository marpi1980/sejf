"""Otwarte pliki: osobisty sejf i profile klientów.

Osobisty sejf (chroniony hasłem głównym) przechowuje pęk haseł do profili klientów.
Każdy profil to osobny zaszyfrowany plik ``.sejfklient`` z własnym hasłem, który można
przekazać innej osobie albo trzymać we wspólnym folderze.

Ta warstwa nie zależy od interfejsu, więc da się ją testować bez okien.
"""
from __future__ import annotations

import base64
import hmac
import os
import threading
from dataclasses import dataclass, field

from . import crypto, storage, totp
from .vault import (merge, new_profile, new_vault, normalize_profile, normalize_vault, now_iso)

MIN_PASSWORD = 8
PROFILE_EXT = ".sejfklient"
ME = "me"  # identyfikator źródła „Moje hasła”


class PasswordChanged(crypto.VaultError):
    """Ktoś zmienił hasło pliku na innym komputerze; zapamiętany klucz już nie pasuje."""


class VaultFile:
    """Jeden zaszyfrowany plik na dysku z bezpiecznym zapisem i łączeniem zmian."""

    def __init__(self, kind: str, path: str, data: dict, key: bytes, salt: bytes, iterations: int, mtime: int | None):
        self.kind, self.path, self.data = kind, path, data
        self.key, self.salt, self.iterations, self.mtime = key, salt, iterations, mtime
        self.dirty = False
        self.lock = threading.RLock()

    # --- tworzenie i otwieranie ------------------------------------------------------------
    @classmethod
    def create(cls, kind: str, path: str, data: dict, password: str) -> "VaultFile":
        salt = crypto.new_salt()
        f = cls(kind, path, data, crypto.derive_key(password, salt), salt, crypto.ITERATIONS, None)
        f.save(force=True)
        return f

    @classmethod
    def open(cls, kind: str, path: str, password: str | None = None, key: bytes | None = None,
             salt: bytes | None = None) -> "VaultFile":
        """Otwiera plik hasłem albo zapamiętanym kluczem (gdy sól się zgadza)."""
        text, mtime = storage.read_text(path)
        env = crypto.parse_envelope(text, kind)
        if key is not None and salt == env.salt:
            use = key
        elif password is not None:
            use = crypto.derive_key(password, env.salt, env.iterations)
        else:
            raise PasswordChanged("Hasło do pliku zostało zmienione.")
        raw = crypto.decrypt(env, use)
        f = cls(kind, path, cls._normalize(kind, raw), use, env.salt, env.iterations, mtime)
        if kind == "vault" and not raw.get("uid"):
            f.dirty = True  # starszy plik: nadajemy mu stały identyfikator przy najbliższym zapisie
        return f

    @staticmethod
    def _normalize(kind: str, data: dict) -> dict:
        return normalize_vault(data) if kind == "vault" else normalize_profile(data)

    @property
    def file_name(self) -> str:
        return os.path.basename(self.path)

    # --- zapis ----------------------------------------------------------------------------
    def sealed(self) -> str:
        return crypto.seal(self.data, self.key, self.salt, self.iterations, self.kind)

    def touch(self) -> None:
        self.data["modified"] = now_iso()
        self.dirty = True

    def _read_remote(self) -> tuple[dict, int] | None:
        """Wersja z dysku, jeśli zmieniła się od ostatniego odczytu; None, gdy się nie zmieniła."""
        m = storage.mtime_of(self.path)
        if m is None or m == self.mtime:
            return None
        text, m = storage.read_text(self.path)
        env = crypto.parse_envelope(text, self.kind)
        if env.salt != self.salt or env.iterations != self.iterations:
            raise PasswordChanged("Hasło do pliku zmieniono na innym komputerze.")
        return self._normalize(self.kind, crypto.decrypt(env, self.key)), m

    def save(self, force: bool = False) -> str:
        """Zapisuje plik. Gdy w międzyczasie zmienił się na innym komputerze, łączy obie wersje.

        Zwraca "saved" albo "merged". Rzuca PasswordChanged, gdy hasło zmieniono gdzie indziej.
        """
        with self.lock:
            result = "saved"
            if not force:
                remote = self._read_remote()
                if remote is not None:
                    self.data = merge(remote[0], self.data)
                    result = "merged"
            self.mtime = storage.write_atomic(self.path, self.sealed())
            self.dirty = False
            return result

    def check_external(self) -> str:
        """Wczytuje zmiany zrobione na innym komputerze.

        Zwraca "none", "reloaded", "merged" (zmiany tu i tam, połączone i zapisane), "missing"
        albo "password" (hasło zmieniono gdzie indziej).
        """
        with self.lock:
            if storage.mtime_of(self.path) is None:
                return "missing"
            try:
                remote = self._read_remote()
            except PasswordChanged:
                return "password"
            except (OSError, crypto.VaultError, ValueError):
                return "none"  # plik w trakcie synchronizacji; spróbujemy później
            if remote is None:
                return "none"
            data, m = remote
            if self.dirty:
                self.data = merge(data, self.data)
                self.mtime = storage.write_atomic(self.path, self.sealed())
                self.dirty = False
                return "merged"
            self.data, self.mtime = data, m
            return "reloaded"

    def rekey(self, new_password: str) -> None:
        with self.lock:
            salt = crypto.new_salt()
            self.key = crypto.derive_key(new_password, salt)
            self.salt, self.iterations = salt, crypto.ITERATIONS
            self.touch()
            self.save(force=True)

    def verify_password(self, password: str) -> bool:
        return hmac.compare_digest(crypto.derive_key(password, self.salt, self.iterations), self.key)


@dataclass
class Profile:
    """Profil klienta na liście w programie. ``file`` jest None, gdy nie udało się go otworzyć."""
    id: str
    meta: dict                       # wpis w pęku haseł osobistego sejfu
    path: str
    file: VaultFile | None = None
    error: str = ""                  # "", "loading", "missing", "password", "corrupt"
    message: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.file.data["name"] if self.file else self.meta.get("name") or "Klient"

    @property
    def data(self) -> dict | None:
        return self.file.data if self.file else None


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str | None) -> bytes | None:
    try:
        return base64.b64decode(s) if s else None
    except (ValueError, TypeError):
        return None


class Session:
    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg if cfg is not None else {}
        self.main: VaultFile | None = None
        self.profiles: dict[str, Profile] = {}

    # --- osobisty sejf --------------------------------------------------------------------
    @property
    def unlocked(self) -> bool:
        return self.main is not None

    @property
    def data(self) -> dict | None:
        return self.main.data if self.main else None

    @property
    def path(self) -> str | None:
        return self.main.path if self.main else None

    @property
    def file_name(self) -> str:
        return self.main.file_name if self.main else ""

    @property
    def dirty(self) -> bool:
        return bool(self.main and self.main.dirty)

    @staticmethod
    def check_new_password(pw: str, repeat: str) -> str | None:
        if len(pw) < MIN_PASSWORD:
            return f"Hasło musi mieć co najmniej {MIN_PASSWORD} znaków."
        if pw != repeat:
            return "Hasła się różnią. Wpisz to samo hasło w obu polach."
        return None

    def create(self, path: str, password: str) -> None:
        self.main = VaultFile.create("vault", path, new_vault(), password)
        self.profiles = {}

    def unlock(self, path: str, password: str) -> None:
        self.main = VaultFile.open("vault", path, password)
        if self.main.dirty:
            self.main.save()
        self._load_profile_list()

    def lock(self) -> None:
        self.main = None
        self.profiles = {}

    def mark_changed(self, sid: str = ME) -> None:
        f = self.source(sid)
        if f:
            f.touch()

    def save(self, force: bool = False) -> str:
        return self.main.save(force=force)

    def check_external(self) -> str:
        r = self.main.check_external()
        if r in ("reloaded", "merged"):
            self._load_profile_list(keep_open=True)
        return r

    def verify_password(self, password: str) -> bool:
        return self.main.verify_password(password)

    def change_password(self, current: str, new: str) -> None:
        if not self.verify_password(current):
            raise crypto.WrongPassword("Obecne hasło główne jest nieprawidłowe.")
        self.main.rekey(new)

    def write_backup(self, path: str) -> None:
        storage.write_atomic(path, self.main.sealed())

    # --- weryfikacja dwuetapowa ----------------------------------------------------------
    @property
    def totp(self) -> dict | None:
        return (self.data.get("security") or {}).get("totp") if self.data else None

    def totp_due(self) -> bool:
        rec = (self.cfg.get("devices") or {}).get(self.data["uid"])
        return totp.is_due(self.totp, rec, self.main.key, self.data["uid"])

    def totp_check(self, code: str) -> bool:
        """Sprawdza kod z aplikacji albo kod zapasowy; po sukcesie zapamiętuje ten komputer."""
        t = self.totp
        if not t:
            return True
        ok = totp.verify(t["secret"], code)
        if not ok and any(ch.isalpha() for ch in code or ""):
            ok = totp.use_recovery(t, code)
            if ok:
                self._touch_security()
                self.main.save()
        if ok:
            self.cfg.setdefault("devices", {})[self.data["uid"]] = totp.new_record(self.main.key, self.data["uid"], t["secret"])
        return ok

    def _touch_security(self) -> None:
        self.data.setdefault("security", {})["updated"] = now_iso()
        self.main.touch()

    def enable_totp(self, secret: str, period: int, codes: list[str]) -> None:
        self.data.setdefault("security", {})["totp"] = totp.new_config(secret, period, codes)
        self._touch_security()
        self.main.save()
        self.cfg.setdefault("devices", {})[self.data["uid"]] = totp.new_record(self.main.key, self.data["uid"], secret)

    def set_totp_period(self, period: int) -> None:
        if self.totp:
            self.totp["period"] = int(period)
            self._touch_security()

    def disable_totp(self) -> None:
        self.data.setdefault("security", {}).pop("totp", None)
        self._touch_security()
        self.main.save()

    def recovery_left(self) -> int:
        return len((self.totp or {}).get("recovery") or [])

    # --- profile klientów ------------------------------------------------------------------
    def _keyring(self) -> list[dict]:
        return self.data.setdefault("profiles", [])

    def _meta(self, pid: str) -> dict | None:
        return next((m for m in self._keyring() if m.get("id") == pid), None)

    def profile_path(self, meta: dict) -> str:
        """Ścieżka może być inna na każdym komputerze (np. inna litera Dysku Google)."""
        return (self.cfg.get("paths") or {}).get(meta["id"]) or meta.get("path") or ""

    def _load_profile_list(self, keep_open: bool = False) -> None:
        old = self.profiles
        self.profiles = {}
        for meta in sorted(self._keyring(), key=lambda m: (m.get("name") or "").lower()):
            prev = old.get(meta["id"]) if keep_open else None
            if prev and prev.file and prev.file.path == self.profile_path(meta):
                prev.meta = meta
                self.profiles[meta["id"]] = prev
            else:
                self.profiles[meta["id"]] = Profile(meta["id"], meta, self.profile_path(meta), error="loading")

    def open_profiles(self, only: list[str] | None = None) -> None:
        """Otwiera profile zapamiętanymi hasłami. Wolne (wyprowadzanie klucza), więc wołane w tle."""
        for p in list(self.profiles.values()):
            if (only is not None and p.id not in only) or p.file is not None:
                continue
            self._open_profile(p)

    def _open_profile(self, p: Profile) -> None:
        meta = p.meta
        try:
            f = VaultFile.open("profile", p.path, password=meta.get("password"), key=_unb64(meta.get("key")),
                               salt=_unb64(meta.get("salt")))
        except FileNotFoundError:
            p.error, p.message = "missing", "Nie znaleziono pliku profilu. Mógł zostać przeniesiony albo usunięty."
            return
        except (PasswordChanged, crypto.WrongPassword):
            p.error, p.message = "password", "Hasło do tego profilu zostało zmienione. Wpisz nowe hasło."
            return
        except crypto.VaultError as e:
            p.error, p.message = "corrupt", str(e)
            return
        except OSError as e:
            p.error, p.message = "missing", f"Nie udało się otworzyć pliku: {e.strerror or e}"
            return
        p.file, p.error, p.message = f, "", ""
        changed = False
        if f.data.get("id") and f.data["id"] != meta["id"]:
            pass  # plik ma inny identyfikator (np. kopia); zostawiamy wpis w pęku bez zmian
        if meta.get("salt") != _b64(f.salt) or meta.get("key") != _b64(f.key):
            meta.update(salt=_b64(f.salt), key=_b64(f.key))
            changed = True
        if meta.get("name") != f.data["name"]:
            meta["name"] = f.data["name"]
            changed = True
        if changed:
            meta["updated"] = now_iso()
            self.main.touch()

    def _remember(self, f: VaultFile, password: str) -> Profile:
        pid = f.data["id"]
        meta = self._meta(pid)
        if meta is None:
            meta = {"id": pid}
            self._keyring().append(meta)
        meta.update(name=f.data["name"], path=f.path, password=password, salt=_b64(f.salt), key=_b64(f.key),
                    updated=now_iso())
        self.data.get("deleted", {}).pop(pid, None)
        self.cfg.setdefault("paths", {}).pop(pid, None)
        p = Profile(pid, meta, f.path, file=f)
        self.profiles[pid] = p
        self.profiles = dict(sorted(self.profiles.items(), key=lambda kv: kv[1].name.lower()))
        self.main.touch()
        self.main.save()
        return p

    def create_profile(self, path: str, name: str, password: str, info: dict | None = None) -> Profile:
        if os.path.exists(path):
            raise FileExistsError("Plik o tej nazwie już istnieje. Wybierz inną nazwę.")
        f = VaultFile.create("profile", path, new_profile(name, info), password)
        return self._remember(f, password)

    def add_profile(self, path: str, password: str) -> Profile:
        """Dodaje istniejący profil (np. otrzymany od współpracownika)."""
        f = VaultFile.open("profile", path, password=password)
        return self._remember(f, password)

    def relink_profile(self, pid: str, path: str | None = None, password: str | None = None) -> Profile:
        """Wskazuje nowe położenie pliku albo nowe hasło profilu."""
        p = self.profiles[pid]
        new_path = path or p.path
        f = VaultFile.open("profile", new_path, password=password if password is not None else p.meta.get("password"),
                           key=None if password is not None else _unb64(p.meta.get("key")),
                           salt=None if password is not None else _unb64(p.meta.get("salt")))
        if f.data.get("id") != pid:
            raise crypto.VaultError("To jest plik innego profilu klienta.")
        meta = p.meta
        if password is not None:
            meta["password"] = password
        meta.update(salt=_b64(f.salt), key=_b64(f.key), name=f.data["name"], updated=now_iso())
        if path:
            meta["path"] = path
            self.cfg.setdefault("paths", {})[pid] = path
        p.file, p.path, p.error, p.message = f, new_path, "", ""
        self.main.touch()
        self.main.save()
        return p

    def forget_profile(self, pid: str) -> None:
        """Usuwa profil z programu. Plik profilu zostaje na dysku."""
        self.data["profiles"] = [m for m in self._keyring() if m.get("id") != pid]
        self.data.setdefault("deleted", {})[pid] = now_iso()
        self.profiles.pop(pid, None)
        self.cfg.get("paths", {}).pop(pid, None)
        self.main.touch()
        self.main.save()

    def change_profile_password(self, pid: str, new_password: str) -> None:
        p = self.profiles[pid]
        p.file.rekey(new_password)
        p.meta.update(password=new_password, salt=_b64(p.file.salt), key=_b64(p.file.key), updated=now_iso())
        self.main.touch()
        self.main.save()

    def profile_password(self, pid: str) -> str:
        return self.profiles[pid].meta.get("password") or ""

    def update_profile_info(self, pid: str, name: str, info: dict) -> None:
        p = self.profiles[pid]
        p.file.data["name"] = name
        p.file.data["info"] = {**info, "updated": now_iso()}
        p.file.touch()
        p.meta["name"] = name
        p.meta["updated"] = now_iso()
        self.main.touch()

    def check_profiles(self) -> dict[str, str]:
        out = {}
        for p in self.profiles.values():
            if p.file:
                r = p.file.check_external()
                if r == "password":
                    p.file, p.error, p.message = None, "password", "Hasło do tego profilu zmieniono na innym komputerze. Wpisz nowe hasło."
                elif r == "missing":
                    p.error, p.message = "missing", "Nie znaleziono pliku profilu. Mógł zostać przeniesiony albo usunięty."
                elif p.error == "missing":
                    p.error, p.message = "", ""
                if p.file and p.data["name"] != p.meta.get("name"):
                    p.meta["name"] = p.data["name"]
                    self.main.touch()
                out[p.id] = r
        return out

    # --- wspólne dla wszystkich źródeł -------------------------------------------------------
    def source(self, sid: str) -> VaultFile | None:
        if sid == ME:
            return self.main
        p = self.profiles.get(sid)
        return p.file if p else None

    def source_name(self, sid: str) -> str:
        return "Moje hasła" if sid == ME else (self.profiles[sid].name if sid in self.profiles else "?")

    def open_sources(self) -> list[str]:
        return [ME] + [pid for pid, p in self.profiles.items() if p.file]

    def all_entries(self, sids: list[str] | None = None):
        for sid in sids or self.open_sources():
            f = self.source(sid)
            if f:
                for e in f.data["entries"]:
                    yield sid, e

    def find(self, sid: str, eid: str) -> dict | None:
        f = self.source(sid)
        return next((e for e in f.data["entries"] if e["id"] == eid), None) if f else None

    def move_entry(self, entry: dict, src: str, dst: str) -> None:
        from .vault import delete_entry
        if src == dst:
            return
        s, d = self.source(src), self.source(dst)
        delete_entry(s.data, entry["id"])
        entry["updated"] = now_iso()
        d.data["entries"].append(entry)
        d.data.get("deleted", {}).pop(entry["id"], None)
        if entry["category"] and entry["category"] not in d.data.setdefault("categories", []):
            d.data["categories"].append(entry["category"])
        s.touch()
        d.touch()
