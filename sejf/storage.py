"""Zapis plików i ustawień programu (nie haseł)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def read_text(path: str | os.PathLike) -> tuple[str, int]:
    """Zwraca treść pliku i znacznik czasu ostatniej zmiany."""
    p = Path(path)
    with open(p, "rb") as f:
        raw = f.read()
        mtime = os.fstat(f.fileno()).st_mtime_ns
    return raw.decode("utf-8-sig"), mtime


def mtime_of(path: str | os.PathLike) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def write_atomic(path: str | os.PathLike, text: str) -> int:
    """Zapisuje plik tak, żeby przerwany zapis nie zostawił uszkodzonego sejfu.

    Najpierw powstaje plik tymczasowy obok docelowego, potem zastępuje oryginał.
    Jeśli dysk w chmurze nie pozwala na podmianę, zapisuje bezpośrednio.
    """
    p = Path(path)
    data = text.encode("utf-8")
    tmp = p.with_name(p.name + ".zapis")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        with open(p, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    return os.stat(p).st_mtime_ns


def config_dir() -> Path:
    override = os.environ.get("SEJF_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Sejf"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "sejf"


def load_config() -> dict:
    try:
        with open(config_dir() / "config.json", encoding="utf-8") as f:
            cfg = json.load(f)
            return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "config.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
