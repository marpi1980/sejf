"""Otwarte pliki: osobisty sejf i profile klientów.

Osobisty sejf (chroniony hasłem głównym) przechowuje Twoją tożsamość (parę kluczy X25519)
i listę profili klientów. Każdy profil to osobny zaszyfrowany plik ``.sejfklient``.
Dostęp do profilu mają osoby z listy „Osoby z dostępem” (każda własnym kluczem)
i, jeśli jest włączone, każdy, kto zna hasło profilu.

Ta warstwa nie zależy od interfejsu, więc da się ją testować bez okien.
"""
from __future__ import annotations

import getpass
import hmac
import os
import threading
from dataclasses import dataclass, field

from . import crypto, storage, totp
from .generator import strength
from .vault import (merge, new_id, new_profile, new_vault, normalize_profile, normalize_vault, now_iso)

MIN_PASSWORD = 10
MIN_PROFILE_PASSWORD = 12
PROFILE_EXT = ".sejfklient"
ME = "me"  # identyfikator źródła „Moje hasła”
LOG_LIMIT = 5000


class PasswordChanged(crypto.VaultError):
    """Hasło pliku zmieniono na innym komputerze albo odebrano dostęp; zapamiętany klucz nie pasuje."""


class VaultFile:
    """Jeden zaszyfrowany plik na dysku z bezpiecznym zapisem i łączeniem zmian.

    Sejf i profil w wersji 1: ``key`` wyprowadzony z hasła, parametry w ``kdf``.
    Profil w wersji 2: losowy klucz profilu ``key`` o identyfikatorze ``keyid``,
    opakowany dla osób z ``data["members"]`` i opcjonalnie dla hasła (``pw_rec``).
    """

    def __init__(self, kind: str, path: str, data: dict, key: bytes, mtime: int | None, *, kdf: dict | None = None,
                 keyid: bytes | None = None, pw_rec: dict | None = None, identity: dict | None = None,
                 password: str | None = None):
        self.kind, self.path, self.data, self.key, self.mtime = kind, path, data, key, mtime
        self.kdf, self.keyid, self.pw_rec = kdf, keyid, pw_rec
        self.identity, self.password = identity, password
        self.opened_by = ""
        self.rotated = False
        self.dirty = False
        self.lock = threading.RLock()

    @property
    def v2(self) -> bool:
        return self.keyid is not None

    # --- zgodność wstecz: sól i liczba iteracji dla plików w wersji 1 --------------------
    @property
    def salt(self) -> bytes | None:
        return crypto.unb64(self.kdf["salt"]) if self.kdf else None

    @property
    def iterations(self) -> int | None:
        return self.kdf.get("iterations") if self.kdf else None

    # --- tworzenie i otwieranie ------------------------------------------------------------
    @classmethod
    def create(cls, kind: str, path: str, data: dict, password: str) -> "VaultFile":
        """Osobisty sejf (lub profil w starym formacie – tylko w testach zgodności)."""
        kdf = crypto.new_kdf()
        f = cls(kind, path, data, crypto.derive(password, kdf), None, kdf=kdf)
        f.save(force=True)
        return f

    @classmethod
    def create_profile(cls, path: str, data: dict, identity: dict, password: str | None) -> "VaultFile":
        key, keyid = crypto.new_profile_key()
        f = cls("profile", path, data, key, None, keyid=keyid, identity=identity, password=password)
        if password:
            f.pw_rec = crypto.wrap_password(key, keyid, password)
        f.save(force=True)
        return f

    @classmethod
    def open(cls, kind: str, path: str, password: str | None = None, key: bytes | None = None,
             salt: bytes | None = None, identity: dict | None = None) -> "VaultFile":
        """Otwiera plik: kluczem osoby, hasłem albo zapamiętanym kluczem (stare profile)."""
        text, mtime = storage.read_text(path)
        env = crypto.parse_envelope(text, kind)
        if env.keyid is not None:
            k = crypto.unwrap_identity(env, identity) if identity else None
            how = "identity"
            if k is None:
                if password is None:
                    raise crypto.NoAccess("Nie masz jeszcze dostępu do tego profilu. Wpisz hasło profilu albo poproś "
                                          "osobę z dostępem, żeby dodała Cię Twoim kodem.")
                k = crypto.unwrap_password(env, password)
                how = "password"
            raw = crypto.decrypt(env, k)
            pw_rec = next((r for r in env.recipients if r.get("kid") == "password"), None)
            f = cls(kind, path, cls._normalize(kind, raw), k, mtime, keyid=env.keyid, pw_rec=pw_rec,
                    identity=identity, password=password)
            f.opened_by = how
            return f
        if key is not None and salt == env.salt:
            use = key
        elif password is not None:
            use = crypto.derive(password, env.kdf)
        else:
            raise PasswordChanged("Hasło do pliku zostało zmienione.")
        raw = crypto.decrypt(env, use)
        f = cls(kind, path, cls._normalize(kind, raw), use, mtime, kdf=env.kdf, identity=identity, password=password)
        f.opened_by = "password"
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
    def recipients(self) -> list[dict]:
        out, seen = [], set()
        for m in self.data.get("members") or []:
            if m.get("pub") and m["id"] not in seen:
                seen.add(m["id"])
                out.append(crypto.wrap_for(self.key, self.keyid, m["pub"]))
        if (self.data.get("access") or {}).get("password") and self.pw_rec:
            out.append(self.pw_rec)
        return out

    def sealed(self) -> str:
        if self.v2:
            return crypto.seal_profile(self.data, self.key, self.keyid, self.recipients())
        return crypto.seal(self.data, self.key, self.kdf, kind=self.kind)

    def touch(self) -> None:
        self.data["modified"] = now_iso()
        self.dirty = True

    def _read_remote(self):
        """Wersja z dysku, jeśli zmieniła się od ostatniego odczytu; None, gdy się nie zmieniła.

        Zwraca (dane, mtime, klucz, keyid, rekord hasła)."""
        m = storage.mtime_of(self.path)
        if m is None or m == self.mtime:
            return None
        text, m = storage.read_text(self.path)
        env = crypto.parse_envelope(text, self.kind)
        if not self.v2:
            if env.kdf != self.kdf:
                raise PasswordChanged("Hasło do pliku zmieniono na innym komputerze.")
            return self._normalize(self.kind, crypto.decrypt(env, self.key)), m, self.key, None, None
        if env.keyid is None:
            raise PasswordChanged("Plik profilu zapisano starszą wersją programu.")
        if env.keyid == self.keyid:
            k = self.key
        else:  # ktoś wymienił klucz profilu (np. odebrał komuś dostęp)
            k = crypto.unwrap_identity(env, self.identity) if self.identity else None
            if k is None and self.password:
                try:
                    k = crypto.unwrap_password(env, self.password)
                except crypto.VaultError:
                    k = None
            if k is None:
                raise PasswordChanged("Nie masz już dostępu do tego profilu.")
        pw_rec = next((r for r in env.recipients if r.get("kid") == "password"), None)
        return self._normalize(self.kind, crypto.decrypt(env, k)), m, k, env.keyid, pw_rec

    def _adopt(self, remote) -> None:
        data, _m, k, keyid, pw_rec = remote
        self.data = merge(data, self.data)
        if self.v2 and not self.rotated and keyid != self.keyid:
            self.key, self.keyid, self.pw_rec = k, keyid, pw_rec
        elif self.v2 and not self.rotated and pw_rec is not None:
            self.pw_rec = pw_rec

    def save(self, force: bool = False) -> str:
        """Zapisuje plik. Gdy w międzyczasie zmienił się na innym komputerze, łączy obie wersje.

        Zwraca "saved" albo "merged". Rzuca PasswordChanged, gdy hasło zmieniono gdzie indziej.
        """
        with self.lock:
            result = "saved"
            if not force:
                remote = self._read_remote()
                if remote is not None:
                    self._adopt(remote)
                    result = "merged"
            self.mtime = storage.write_atomic(self.path, self.sealed())
            self.dirty = False
            self.rotated = False
            return result

    def check_external(self) -> str:
        """Wczytuje zmiany zrobione na innym komputerze.

        Zwraca "none", "reloaded", "merged" (zmiany tu i tam, połączone i zapisane), "missing"
        albo "password" (hasło zmieniono gdzie indziej lub odebrano dostęp).
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
            if self.dirty or self.rotated:
                self._adopt(remote)
                self.mtime = storage.write_atomic(self.path, self.sealed())
                self.dirty = self.rotated = False
                return "merged"
            data, m, k, keyid, pw_rec = remote
            self.data, self.mtime = data, m
            if self.v2:
                self.key, self.keyid, self.pw_rec = k, keyid, pw_rec
            return "reloaded"

    def rekey(self, new_password: str) -> None:
        """Nowe hasło sejfu (i nowe parametry Argon2id)."""
        with self.lock:
            self.kdf = crypto.new_kdf()
            self.key = crypto.derive(new_password, self.kdf)
            self.touch()
            self.save(force=True)

    def rotate(self, password: str | None) -> None:
        """Nowy klucz profilu. Osoby z listy dostaną go automatycznie przy zapisie."""
        with self.lock:
            self.key, self.keyid = crypto.new_profile_key()
            self.pw_rec = crypto.wrap_password(self.key, self.keyid, password) if password else None
            self.password = password
            self.rotated = True
            self.touch()

    def verify_password(self, password: str) -> bool:
        return hmac.compare_digest(crypto.derive(password, self.kdf), self.key)


@dataclass
class Profile:
    """Profil klienta na liście w programie. ``file`` jest None, gdy nie udało się go otworzyć."""
    id: str
    meta: dict                       # wpis w osobistym sejfie: nazwa, ścieżka, ewentualnie hasło profilu
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


def _unb64(s: str | None) -> bytes | None:
    try:
        return crypto.unb64(s) if s else None
    except (ValueError, TypeError):
        return None


class Session:
    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg if cfg is not None else {}
        self.main: VaultFile | None = None
        self.profiles: dict[str, Profile] = {}
        self.upgraded = False  # czy przy odblokowaniu przeniesiono sejf na Argon2id

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
        """Wymagania dla hasła głównego: co najmniej 10 znaków i ocena „Silne”."""
        if len(pw) < MIN_PASSWORD:
            return (f"Hasło główne musi mieć co najmniej {MIN_PASSWORD} znaków. Najlepiej 4–5 losowych słów, "
                    "np. „wiosło kubek mapa dziesięć”.")
        if strength(pw)[0] < 4:
            return ("Hasło główne jest za słabe. Użyj kilku losowych słów albo dłuższego hasła z cyframi "
                    "i znakami specjalnymi.")
        if pw != repeat:
            return "Hasła się różnią. Wpisz to samo hasło w obu polach."
        return None

    @staticmethod
    def check_profile_password(pw: str) -> str | None:
        if len(pw) < MIN_PROFILE_PASSWORD:
            return f"Hasło profilu musi mieć co najmniej {MIN_PROFILE_PASSWORD} znaków. Najlepiej użyj losowego."
        return None

    def create(self, path: str, password: str) -> None:
        self.main = VaultFile.create("vault", path, new_vault(), password)
        self.profiles = {}
        self._ensure_identity()

    def unlock(self, path: str, password: str) -> None:
        self.main = VaultFile.open("vault", path, password)
        self.upgraded = False
        if not crypto.kdf_is_current(self.main.kdf):  # przeniesienie z PBKDF2 na Argon2id
            self.main.rekey(password)
            self.upgraded = True
        self._ensure_identity()
        if self.main.dirty:
            self.main.save()
        self._load_profile_list()

    def _ensure_identity(self) -> None:
        if not (self.data.get("identity") or {}).get("priv"):
            try:
                name = getpass.getuser() or "Użytkownik"
            except Exception:  # noqa: BLE001 – brak nazwy użytkownika w systemie
                name = "Użytkownik"
            self.data["identity"] = {**crypto.new_identity(name), "created": now_iso()}
            self.main.touch()
            self.main.save()

    @property
    def identity(self) -> dict:
        return self.data["identity"]

    def my_code(self) -> str:
        return crypto.identity_code(self.identity)

    def set_my_name(self, name: str) -> None:
        name = name.strip() or "Użytkownik"
        self.identity["name"] = name
        self.main.touch()
        for p in self.profiles.values():  # nazwa widoczna na listach osób w profilach
            if p.file:
                for m in p.data.get("members") or []:
                    if m["id"] == self.identity["kid"] and m.get("name") != name:
                        m["name"], m["updated"] = name, now_iso()
                        p.file.touch()

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
        """Otwiera profile kluczem tej osoby albo zapamiętanym hasłem. Wołane w tle."""
        for p in list(self.profiles.values()):
            if (only is not None and p.id not in only) or p.file is not None:
                continue
            self._open_profile(p)

    def _me_member(self) -> dict:
        i = self.identity
        t = now_iso()
        return {"id": i["kid"], "name": i["name"], "pub": i["pub"], "added": t, "updated": t, "added_by": i["kid"]}

    def _is_member(self, data: dict) -> bool:
        return any(m["id"] == self.identity["kid"] for m in data.get("members") or [])

    def _open_file(self, path: str, meta: dict | None, password: str | None) -> VaultFile:
        pw = password if password is not None else (meta or {}).get("password")
        f = VaultFile.open("profile", path, password=pw, key=_unb64((meta or {}).get("key")),
                           salt=_unb64((meta or {}).get("salt")), identity=self.identity)
        if not f.v2:  # profil zapisany przez wersję 3.1 lub starszą: przenosimy do nowego formatu
            self._upgrade_profile(f, pw)
        elif not self._is_member(f.data):  # weszliśmy hasłem: dopisujemy siebie do osób z dostępem
            f.data.setdefault("members", []).append(self._me_member())
            self.log_file(f, "dołączył do profilu (hasłem)")
            f.touch()
            f.save()
        return f

    def _upgrade_profile(self, f: VaultFile, password: str | None) -> None:
        f.key, f.keyid = crypto.new_profile_key()
        f.kdf = None
        f.password = password
        f.pw_rec = crypto.wrap_password(f.key, f.keyid, password) if password else None
        f.data["members"] = [self._me_member()]
        f.data["access"] = {"password": bool(password), "updated": now_iso()}
        self.log_file(f, "przeniósł profil do nowego formatu (klucze osób)")
        f.touch()
        f.rotated = True
        f.save(force=True)

    def _open_profile(self, p: Profile) -> None:
        meta = p.meta
        try:
            f = self._open_file(p.path, meta, None)
        except FileNotFoundError:
            p.error, p.message = "missing", "Nie znaleziono pliku profilu. Mógł zostać przeniesiony albo usunięty."
            return
        except (PasswordChanged, crypto.WrongPassword, crypto.NoAccess):
            p.error = "password"
            p.message = ("Nie masz już dostępu do tego profilu: ktoś zmienił jego hasło albo odebrał Ci dostęp. "
                         "Wpisz aktualne hasło profilu albo poproś osobę z dostępem, żeby dodała Cię ponownie.")
            return
        except crypto.VaultError as e:
            p.error, p.message = "corrupt", str(e)
            return
        except OSError as e:
            p.error, p.message = "missing", f"Nie udało się otworzyć pliku: {e.strerror or e}"
            return
        p.file, p.error, p.message = f, "", ""
        self._sync_meta(meta, f)

    def _sync_meta(self, meta: dict, f: VaultFile) -> None:
        changed = False
        for key in ("key", "salt"):  # klucze starych profili nie są już potrzebne
            if meta.pop(key, None) is not None:
                changed = True
        if not (f.data.get("access") or {}).get("password") and meta.pop("password", None) is not None:
            changed = True  # dostęp hasłem wyłączony: nie trzymamy niepotrzebnego hasła
        if f.password and (f.data.get("access") or {}).get("password") and meta.get("password") != f.password:
            meta["password"] = f.password
            changed = True
        if meta.get("name") != f.data["name"]:
            meta["name"] = f.data["name"]
            changed = True
        if changed:
            meta["updated"] = now_iso()
            self.main.touch()

    def _remember(self, f: VaultFile) -> Profile:
        pid = f.data["id"]
        meta = self._meta(pid)
        if meta is None:
            meta = {"id": pid}
            self._keyring().append(meta)
        meta.update(name=f.data["name"], path=f.path, updated=now_iso())
        self._sync_meta(meta, f)
        self.data.get("deleted", {}).pop(pid, None)
        self.cfg.setdefault("paths", {}).pop(pid, None)
        p = Profile(pid, meta, f.path, file=f)
        self.profiles[pid] = p
        self.profiles = dict(sorted(self.profiles.items(), key=lambda kv: kv[1].name.lower()))
        self.main.touch()
        self.main.save()
        return p

    def create_profile(self, path: str, name: str, password: str | None = None, info: dict | None = None) -> Profile:
        if os.path.exists(path):
            raise FileExistsError("Plik o tej nazwie już istnieje. Wybierz inną nazwę.")
        data = new_profile(name, info)
        data["members"] = [self._me_member()]
        data["access"] = {"password": bool(password), "updated": now_iso()}
        f = VaultFile.create_profile(path, data, self.identity, password)
        self.log_file(f, "utworzył profil")
        f.touch()
        f.save()
        return self._remember(f)

    def add_profile(self, path: str, password: str | None = None) -> Profile:
        """Dodaje istniejący profil: bez hasła, gdy ktoś już dodał tę osobę, inaczej hasłem profilu."""
        return self._remember(self._open_file(path, None, password))

    def relink_profile(self, pid: str, path: str | None = None, password: str | None = None) -> Profile:
        """Wskazuje nowe położenie pliku albo nowe hasło profilu."""
        p = self.profiles[pid]
        new_path = path or p.path
        f = self._open_file(new_path, p.meta, password)
        if f.data.get("id") != pid:
            raise crypto.VaultError("To jest plik innego profilu klienta.")
        if path:
            p.meta["path"] = path
            self.cfg.setdefault("paths", {})[pid] = path
        p.file, p.path, p.error, p.message = f, new_path, "", ""
        self._sync_meta(p.meta, f)
        p.meta["updated"] = now_iso()
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

    # --- osoby z dostępem i hasło profilu ----------------------------------------------------
    def members(self, pid: str) -> list[dict]:
        return list(self.profiles[pid].data.get("members") or [])

    def password_access(self, pid: str) -> bool:
        return bool((self.profiles[pid].data.get("access") or {}).get("password"))

    def add_member(self, pid: str, code: str) -> dict:
        member = crypto.parse_identity_code(code)
        f = self.profiles[pid].file
        if any(m["id"] == member["kid"] for m in f.data.get("members") or []):
            raise crypto.VaultError(f"{member['name']} ma już dostęp do tego profilu.")
        t = now_iso()
        m = {"id": member["kid"], "name": member["name"], "pub": member["pub"], "added": t, "updated": t,
             "added_by": self.identity["kid"]}
        f.data.setdefault("members", []).append(m)
        f.data.get("deleted", {}).pop(m["id"], None)
        self.log_file(f, "dodał osobę", member["name"])
        f.touch()
        f.save()
        return m

    def remove_member(self, pid: str, kid: str) -> None:
        """Odbiera dostęp: usuwa osobę, wymienia klucz profilu i wyłącza dostęp hasłem
        (ta osoba mogła znać hasło)."""
        if kid == self.identity["kid"]:
            raise crypto.VaultError("Nie możesz odebrać dostępu sobie. Żeby przestać korzystać z profilu, "
                                    "usuń go z programu.")
        p = self.profiles[pid]
        f = p.file
        member = next((m for m in f.data.get("members") or [] if m["id"] == kid), None)
        if member is None:
            return
        f.data["members"] = [m for m in f.data["members"] if m["id"] != kid]
        f.data.setdefault("deleted", {})[kid] = now_iso()
        f.data["access"] = {"password": False, "updated": now_iso()}
        f.rotate(None)
        self.log_file(f, "odebrał dostęp", member.get("name", ""))
        f.save()
        self._sync_meta(p.meta, f)
        self.main.save()

    def set_password_access(self, pid: str, password: str | None) -> None:
        """Włącza dostęp hasłem z nowym hasłem albo go wyłącza. Za każdym razem wymienia klucz profilu."""
        p = self.profiles[pid]
        f = p.file
        f.data["access"] = {"password": bool(password), "updated": now_iso()}
        f.rotate(password)
        self.log_file(f, "zmienił hasło profilu" if password else "wyłączył dostęp hasłem")
        f.save()
        if password:
            p.meta["password"] = password
        self._sync_meta(p.meta, f)
        p.meta["updated"] = now_iso()
        self.main.touch()
        self.main.save()

    def change_profile_password(self, pid: str, new_password: str) -> None:
        self.set_password_access(pid, new_password)

    def profile_password(self, pid: str) -> str:
        return self.profiles[pid].meta.get("password") or ""

    def update_profile_info(self, pid: str, name: str, info: dict) -> None:
        p = self.profiles[pid]
        p.file.data["name"] = name
        p.file.data["info"] = {**info, "updated": now_iso()}
        self.log_file(p.file, "zmienił dane klienta")
        p.file.touch()
        p.meta["name"] = name
        p.meta["updated"] = now_iso()
        self.main.touch()

    # --- dziennik zmian ------------------------------------------------------------------------
    def log_file(self, f: VaultFile, action: str, detail: str = "", entry: dict | None = None) -> None:
        log = f.data.setdefault("log", [])
        log.append({"id": new_id(), "at": now_iso(), "kid": self.identity["kid"], "who": self.identity["name"],
                    "action": action, "detail": detail, "eid": entry["id"] if entry else "",
                    "title": entry["title"] if entry else ""})
        if len(log) > LOG_LIMIT:
            del log[: len(log) - LOG_LIMIT]

    def log(self, sid: str, action: str, entry: dict | None = None, detail: str = "") -> None:
        """Zapis w dzienniku profilu (dla „Moich haseł” nic nie robi)."""
        if sid == ME:
            return
        f = self.source(sid)
        if f:
            self.log_file(f, action, detail, entry)
            f.touch()

    def check_profiles(self) -> dict[str, str]:
        out = {}
        for p in self.profiles.values():
            if p.file:
                r = p.file.check_external()
                if r == "password":
                    p.file, p.error = None, "password"
                    p.message = ("Nie masz już dostępu do tego profilu: ktoś zmienił jego hasło albo odebrał Ci "
                                 "dostęp. Wpisz aktualne hasło profilu albo poproś o ponowne dodanie.")
                elif r == "missing":
                    p.error, p.message = "missing", "Nie znaleziono pliku profilu. Mógł zostać przeniesiony albo usunięty."
                elif p.error == "missing":
                    p.error, p.message = "", ""
                if p.file:
                    before = dict(p.meta)
                    self._sync_meta(p.meta, p.file)
                    if p.meta != before:
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
        self.log(src, "przeniósł wpis do innego miejsca", entry)
        self.log(dst, "przeniósł wpis tutaj", entry)
        s.touch()
        d.touch()
